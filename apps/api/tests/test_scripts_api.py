"""PR-05 Gate A 脚本 API / 服务测试（需要 TEST_DATABASE_URL）。

覆盖：创建 + 内容哈希幂等、拆段（fake 确定性）、读取、改名、单段编辑乐观锁、需求变更标记候选过期、
locked_shot_id 校验、段落重排、锁定段落重新拆段保护（force）、404/409/422。
"""

from __future__ import annotations

import pytest_asyncio
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Asset, Shot, SourceDirectory
from clipmind_shared.models.enums import AssetStatus, ShotStatus


@pytest_asyncio.fixture
async def seeded_shot(session) -> int:
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.flush()
    asset = Asset(
        source_directory_id=sd.id, relative_path="s.mp4", normalized_relative_path="s.mp4",
        filename="s.mp4", extension="mp4", file_size=1, status=AssetStatus.SHOT_SPLIT,
        width=720, height=1280, duration=8.0, orientation="portrait",
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.flush()
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=1, start_time=0.0, end_time=5.0,
        duration=5.0, detector_type="fixed", status=ShotStatus.READY,
    )
    session.add(shot)
    await session.commit()
    return shot.id


_SCRIPT = "痛点开场，旅行最怕吹风机难用。\n\n产品卖点：轻便手持，不超过5秒展示。\n\n下单引导"


async def _create(client, name="测试脚本", raw=_SCRIPT):
    r = await client.post("/api/scripts", json={"name": name, "raw_script": raw})
    return r


async def _parse_fake(client, sid, force=False):
    return await client.post(
        f"/api/scripts/{sid}/parse", params={"force": str(force).lower()},
        json={"parser": "fake"},
    )


async def test_create_script(client):
    r = await _create(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "draft"
    assert body["parse_status"] == "pending"
    assert body["segment_count"] == 0


async def test_create_idempotent_same_hash(client):
    a = await _create(client, name="A")
    b = await _create(client, name="B", raw=_SCRIPT)
    assert a.json()["id"] == b.json()["id"]  # 同内容复用，不重复创建


async def test_parse_creates_segments(client):
    sid = (await _create(client)).json()["id"]
    r = await _parse_fake(client, sid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parse_status"] == "ok"
    assert body["status"] == "parsed"
    assert body["parser_provider"] == "fake"
    assert body["segment_count"] >= 3
    assert [s["order_index"] for s in body["segments"]] == list(range(len(body["segments"])))


async def test_get_detail_ordered(client):
    sid = (await _create(client)).json()["id"]
    await _parse_fake(client, sid)
    r = await client.get(f"/api/scripts/{sid}")
    assert r.status_code == 200
    segs = r.json()["segments"]
    assert segs == sorted(segs, key=lambda s: s["order_index"])


async def test_update_name(client):
    sid = (await _create(client)).json()["id"]
    r = await client.patch(f"/api/scripts/{sid}", json={"name": "改名了"})
    assert r.status_code == 200
    assert r.json()["name"] == "改名了"


async def test_segment_optimistic_lock(client):
    sid = (await _create(client)).json()["id"]
    seg = (await _parse_fake(client, sid)).json()["segments"][0]
    # 正确 lock_version → 成功并自增
    r = await client.patch(
        f"/api/scripts/{sid}/segments/{seg['id']}",
        json={"lock_version": seg["lock_version"], "visual_requirement": "室内手持吹风机特写"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["lock_version"] == seg["lock_version"] + 1
    assert r.json()["candidates_stale"] is True  # 需求变更 → 候选过期
    # 旧 lock_version → 409
    r2 = await client.patch(
        f"/api/scripts/{sid}/segments/{seg['id']}",
        json={"lock_version": seg["lock_version"], "visual_requirement": "x"},
    )
    assert r2.status_code == 409


async def test_segment_locked_shot_validation(client, seeded_shot):
    sid = (await _create(client)).json()["id"]
    seg = (await _parse_fake(client, sid)).json()["segments"][0]
    # 不存在的镜头 → 422
    bad = await client.patch(
        f"/api/scripts/{sid}/segments/{seg['id']}",
        json={"lock_version": seg["lock_version"], "locked_shot_id": 99999999},
    )
    assert bad.status_code == 422
    # 有效镜头 → 200
    ok = await client.patch(
        f"/api/scripts/{sid}/segments/{seg['id']}",
        json={"lock_version": seg["lock_version"], "locked_shot_id": seeded_shot},
    )
    assert ok.status_code == 200
    assert ok.json()["locked_shot_id"] == seeded_shot


async def test_structured_requirements_whitelist(client):
    sid = (await _create(client)).json()["id"]
    seg = (await _parse_fake(client, sid)).json()["segments"][0]
    r = await client.patch(
        f"/api/scripts/{sid}/segments/{seg['id']}",
        json={
            "lock_version": seg["lock_version"],
            "structured_requirements": {"scenes": ["室内", "室内"], "DROP_TABLE": "shot"},
        },
    )
    assert r.status_code == 200, r.text
    sr = r.json()["structured_requirements"]
    assert sr == {"scenes": ["室内"]}  # 未知键丢弃、列表去重


async def test_reorder(client):
    sid = (await _create(client)).json()["id"]
    segs = (await _parse_fake(client, sid)).json()["segments"]
    ids = [s["id"] for s in segs]
    reversed_ids = list(reversed(ids))
    r = await client.post(
        f"/api/scripts/{sid}/segments/reorder", json={"segment_ids": reversed_ids}
    )
    assert r.status_code == 200, r.text
    new = r.json()["segments"]
    assert [s["id"] for s in new] == reversed_ids
    assert [s["order_index"] for s in new] == list(range(len(new)))


async def test_reorder_invalid_set(client):
    sid = (await _create(client)).json()["id"]
    segs = (await _parse_fake(client, sid)).json()["segments"]
    ids = [s["id"] for s in segs][:-1]  # 缺一个 → 非法
    r = await client.post(f"/api/scripts/{sid}/segments/reorder", json={"segment_ids": ids})
    assert r.status_code == 422


async def test_reparse_locked_requires_force(client, seeded_shot):
    sid = (await _create(client)).json()["id"]
    seg = (await _parse_fake(client, sid)).json()["segments"][0]
    # 锁定一个段落
    await client.patch(
        f"/api/scripts/{sid}/segments/{seg['id']}",
        json={"lock_version": seg["lock_version"], "locked_shot_id": seeded_shot},
    )
    # 无 force 重新拆段 → 409
    blocked = await _parse_fake(client, sid, force=False)
    assert blocked.status_code == 409
    # force=true → 允许（锁定被替换）
    forced = await _parse_fake(client, sid, force=True)
    assert forced.status_code == 200


async def test_not_found_and_empty(client):
    assert (await client.get("/api/scripts/99999999")).status_code == 404
    miss = await client.post("/api/scripts/99999999/parse", json={"parser": "fake"})
    assert miss.status_code == 404
    empty = await client.post("/api/scripts", json={"name": "x", "raw_script": "   "})
    assert empty.status_code == 422
    # 段落更新多余字段被拒（extra="forbid"）
    sid = (await _create(client)).json()["id"]
    seg = (await _parse_fake(client, sid)).json()["segments"][0]
    bad = await client.patch(
        f"/api/scripts/{sid}/segments/{seg['id']}",
        json={"lock_version": seg["lock_version"], "evil": "x"},
    )
    assert bad.status_code == 422
