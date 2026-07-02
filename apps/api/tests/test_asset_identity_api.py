"""PR-C 素材身份 / 位置 / 指纹 / 代次 API 测试（需要 TEST_DATABASE_URL）。

覆盖：identity/locations/analysis-generations 端点、指纹任务入队与查询、
Shot 代次保留的 API 语义（默认过滤 retired / 详情可达 / generation 参数 /
血缘与使用次数不受重新分析影响 / retired 不允许新增引用 / 守卫已解除）。
"""

from __future__ import annotations

import os

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    AssetLocation,
    MediaProcessingRun,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import AssetStatus, MediaRunStatus, ShotStatus

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


async def _seed_asset(session, *, filename="src.mp4", with_location=True) -> Asset:
    sd = SourceDirectory(
        name=f"d-{filename}",
        mount_path="/app/source",
        include_extensions=["mp4"],
        exclude_patterns=[],
        recursive=True,
        read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id,
        relative_path=filename,
        normalized_relative_path=filename,
        filename=filename,
        extension="mp4",
        file_size=1000,
        duration=10.0,
        status=AssetStatus.INDEXED,
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    if with_location:
        loc = AssetLocation(
            asset_id=asset.id,
            source_root_id=sd.id,
            relative_path=filename,
            normalized_path=filename,
            location_status="present",
            is_primary=True,
            file_size=1000,
        )
        session.add(loc)
        await session.commit()
    return asset


async def _seed_generation(session, asset, generation, *, retired=False, seqs=(1, 2)):
    run = MediaProcessingRun(
        run_uuid=f"r{asset.id}g{generation}",
        asset_id=asset.id,
        generation=generation,
        status=MediaRunStatus.COMPLETED,
        queued_at=utcnow(),
        finished_at=utcnow(),
    )
    session.add(run)
    shots = []
    for seq in seqs:
        shot = Shot(
            asset_id=asset.id,
            generation=generation,
            sequence_no=seq,
            start_time=float(seq - 1),
            end_time=float(seq),
            duration=1.0,
            detector_type="fixed",
            status=ShotStatus.READY,
            retired_at=utcnow() if retired else None,
            keyframe_path=f"k/{asset.id}-{generation}-{seq}.webp",
            proxy_path=f"p/{asset.id}-{generation}-{seq}.mp4",
        )
        session.add(shot)
        shots.append(shot)
    await session.commit()
    for s in shots:
        await session.refresh(s)
    return shots


# ============================ identity / locations ============================


async def test_identity_and_locations(client, session):
    asset = await _seed_asset(session, filename="id1.mp4")
    asset.quick_fingerprint = "a" * 64
    asset.quick_fingerprint_version = "qfp1"
    asset.full_hash = "b" * 64
    asset.full_hash_algorithm = "sha256"
    asset.fingerprint_state = "full_ready"
    asset.content_size = 1000
    await session.commit()

    r = await client.get(f"/api/assets/{asset.id}/identity")
    assert r.status_code == 200, r.text
    out = r.json()
    # 哈希只返回缩短形式（不暴露完整值）
    assert out["full_hash_short"] == "b" * 12
    assert out["quick_fingerprint_short"] == "a" * 12
    assert out["full_hash_available"] is True
    assert out["location_count"] == 1
    assert out["primary_location"]["relative_path"] == "id1.mp4"
    assert "full_hash\":" not in r.text or ("b" * 64) not in r.text, "不得返回完整哈希"

    r = await client.get(f"/api/assets/{asset.id}/locations")
    assert r.status_code == 200
    locs = r.json()
    assert len(locs) == 1 and locs[0]["is_primary"]
    assert locs[0]["source_root_name"]
    # 404
    assert (await client.get("/api/assets/999999/identity")).status_code == 404


async def test_asset_out_includes_identity_summary(client, session):
    asset = await _seed_asset(session, filename="id2.mp4")
    r = await client.get(f"/api/assets/{asset.id}")
    assert r.status_code == 200
    out = r.json()
    assert out["fingerprint_state"] == "pending"
    assert out["full_hash_available"] is False


# ============================ 指纹任务 ============================


async def test_fingerprint_job_enqueue_and_query(client, session):
    asset = await _seed_asset(session, filename="fp1.mp4")
    r = await client.post(f"/api/assets/{asset.id}/fingerprint", json={"kind": "full"})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["kind"] == "full" and job["status"] == "queued"
    assert job["total_count"] == 1

    r = await client.get(f"/api/assets/fingerprint-jobs/{job['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == job["id"]

    # 批量 + 未知资产 404
    r = await client.post(
        "/api/assets/fingerprints/batch",
        json={"asset_ids": [asset.id], "kind": "quick"},
    )
    assert r.status_code == 202
    r = await client.post(
        "/api/assets/fingerprints/batch",
        json={"asset_ids": [999999], "kind": "quick"},
    )
    assert r.status_code == 404
    # 非法 kind 422
    r = await client.post(f"/api/assets/{asset.id}/fingerprint", json={"kind": "md5"})
    assert r.status_code == 422


# ============================ 代次保留 API 语义 ============================


async def test_generation_filtering_and_history_access(client, session):
    asset = await _seed_asset(session, filename="gen1.mp4")
    old_shots = await _seed_generation(session, asset, 1, retired=True)
    new_shots = await _seed_generation(session, asset, 2, retired=False)

    # 默认（current）只返回第 2 代
    r = await client.get(f"/api/assets/{asset.id}/shots?page=1&page_size=50")
    ids = {s["id"] for s in r.json()["items"]}
    assert ids == {s.id for s in new_shots}
    assert all(s["generation"] == 2 and s["retired"] is False for s in r.json()["items"])

    # generation=1 显式查看历史
    r = await client.get(f"/api/assets/{asset.id}/shots?generation=1")
    ids = {s["id"] for s in r.json()["items"]}
    assert ids == {s.id for s in old_shots}
    assert all(s["retired"] is True for s in r.json()["items"])

    # 非法 generation
    r = await client.get(f"/api/assets/{asset.id}/shots?generation=abc")
    assert r.status_code == 422

    # 全局镜头列表默认不含 retired
    r = await client.get("/api/shots?page=1&page_size=100")
    ids = {s["id"] for s in r.json()["items"]}
    assert not ({s.id for s in old_shots} & ids)

    # 历史 Shot 详情仍可打开（标注 retired）
    r = await client.get(f"/api/shots/{old_shots[0].id}")
    assert r.status_code == 200
    assert r.json()["retired"] is True and r.json()["generation"] == 1

    # analysis-generations 汇总
    r = await client.get(f"/api/assets/{asset.id}/analysis-generations")
    assert r.status_code == 200
    out = r.json()
    assert out["current_generation"] == 2
    gens = {g["generation"]: g for g in out["items"]}
    assert gens[2]["is_current"] and not gens[1]["is_current"]
    assert gens[1]["shot_count"] == 2

    # identity 汇总含代次
    r = await client.get(f"/api/assets/{asset.id}/identity")
    assert r.json()["current_generation"] == 2
    assert r.json()["historical_generation_count"] == 1


async def test_reanalysis_allowed_with_lineage_and_usage_preserved(client, session):
    """有血缘素材可重新分析（PR-B 守卫解除）；retire 不影响使用次数。"""
    src = await _seed_asset(session, filename="gen2.mp4")
    (shot,) = await _seed_generation(session, src, 1, retired=False, seqs=(1,))
    final_asset = await _seed_asset(session, filename="gen2-final.mp4")
    r = await client.post(
        "/api/final-videos", json={"asset_id": final_asset.id, "title": "成片G"}
    )
    fv = r.json()
    r = await client.post(
        f"/api/final-videos/{fv['id']}/usages", json={"source_shot_id": shot.id}
    )
    usage = r.json()
    await client.post(f"/api/final-video-usages/{usage['id']}/confirm")
    r = await client.get(f"/api/shots/{shot.id}/usage-summary")
    assert r.json()["confirmed_usage_count"] == 1

    # 有血缘也允许发起重新分析（202，不再 409）
    r = await client.post(f"/api/assets/{src.id}/analyze-shots")
    assert r.status_code == 202, r.text

    # 模拟 worker 完成代次切换：第 1 代 retire、第 2 代 current
    shot_db = await session.get(Shot, shot.id)
    shot_db.retired_at = utcnow()
    await _seed_generation(session, src, 2, retired=False, seqs=(1, 2))
    await session.commit()

    # 血缘引用与使用次数不变（Usage 继续引用历史 Shot——审计事实）
    r = await client.get(f"/api/shots/{shot.id}/usage-summary")
    assert r.json()["confirmed_usage_count"] == 1
    r = await client.get(f"/api/final-videos/{fv['id']}/lineage")
    assert r.json()["usages"][0]["source_shot_id"] == shot.id
    assert r.json()["usages"][0]["shot"]["retired"] is True

    # retired 镜头不允许**新增**引用
    fa2 = await _seed_asset(session, filename="gen2-final2.mp4")
    r = await client.post("/api/final-videos", json={"asset_id": fa2.id, "title": "成片H"})
    fv2 = r.json()
    r = await client.post(
        f"/api/final-videos/{fv2['id']}/usages", json={"source_shot_id": shot.id}
    )
    assert r.status_code == 409
    assert "历史" in r.json()["detail"]


async def test_asset_summary_counts_only_current_generation(client, session):
    asset = await _seed_asset(session, filename="gen3.mp4")
    await _seed_generation(session, asset, 1, retired=True, seqs=(1, 2, 3))
    await _seed_generation(session, asset, 2, retired=False, seqs=(1,))
    r = await client.get(f"/api/assets/{asset.id}/usage-summary")
    assert r.json()["total_shots"] == 1  # 只算当前代次
