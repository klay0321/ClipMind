"""PR-06A Gate A 补充回归（需要 TEST_DATABASE_URL）。

补齐：输入校验（超长/lock_version<1）、归档 reorder 409、unarchive 幂等、order_index 无空洞、
attach 幂等、detach 守卫与不破坏脚本（hash/候选/锁定）、Project 删除 FK SET NULL/CASCADE、
可见镜头三源去重、产品/审核筛选、stable 分页、ShotOut 不含本机路径、stats 查询数有界。
"""

from __future__ import annotations

import os

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    Collection,
    Product,
    Project,
    ScriptProject,
    ScriptSegment,
    ScriptShotCandidate,
    Shot,
    ShotReviewState,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AssetStatus,
    ReviewStatus,
    ScriptStatus,
    ShotStatus,
)
from sqlalchemy import delete, event, select

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


async def _asset(session, *, filename="x.mp4") -> Asset:
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    a = Asset(
        source_directory_id=sd.id, relative_path=filename, normalized_relative_path=filename,
        filename=filename, extension="mp4", file_size=1, duration=5.0,
        status=AssetStatus.INDEXED, first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(a)
    await session.commit()
    await session.refresh(a)
    return a


async def _shot(session, asset, *, seq=1) -> Shot:
    s = Shot(
        asset_id=asset.id, generation=1, sequence_no=seq, start_time=0.0, end_time=1.0,
        duration=1.0, detector_type="fixed", status=ShotStatus.READY,
        keyframe_path=f"k/{asset.id}-{seq}.jpg", proxy_path=f"p/{asset.id}-{seq}.mp4",
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


async def _product(session, *, name="P") -> Product:
    p = Product(name=name, normalized_name=name.lower())
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def _script(session, *, project_id=None) -> ScriptProject:
    sp = ScriptProject(
        name="脚本", raw_script="raw", script_hash=f"h-{os.urandom(4).hex()}",
        status=ScriptStatus.PARSED, project_id=project_id,
    )
    session.add(sp)
    await session.commit()
    await session.refresh(sp)
    return sp


async def _project(client, name="P"):
    r = await client.post("/api/projects", json={"name": name})
    return r.json()["id"]


# ---------------- 输入校验 ----------------


async def test_long_name_and_desc_422(client):
    assert (await client.post("/api/projects", json={"name": "n" * 201})).status_code == 422
    assert (
        await client.post("/api/projects", json={"name": "ok", "description": "d" * 2001})
    ).status_code == 422


async def test_lock_version_below_one_422(client):
    pid = await _project(client)
    r = await client.patch(f"/api/projects/{pid}", json={"lock_version": 0, "name": "x"})
    assert r.status_code == 422
    ra = await client.post(f"/api/projects/{pid}/archive", json={"lock_version": 0})
    assert ra.status_code == 422


# ---------------- 归档 / 幂等 ----------------


async def test_reorder_archived_409(client, session):
    a1 = await _asset(session, filename="a1.mp4")
    a2 = await _asset(session, filename="a2.mp4")
    pid = await _project(client)
    await client.post(f"/api/projects/{pid}/assets/batch", json={"ids": [a1.id, a2.id]})
    await client.post(f"/api/projects/{pid}/archive", json={"lock_version": 1})
    r = await client.post(
        f"/api/projects/{pid}/assets/reorder",
        json={"ids": [a2.id, a1.id], "lock_version": 2},
    )
    assert r.status_code == 409


async def test_unarchive_idempotent(client):
    pid = await _project(client)
    # 未归档时 unarchive：幂等返回 active（任意 lock_version）
    r = await client.post(f"/api/projects/{pid}/unarchive", json={"lock_version": 1})
    assert r.status_code == 200
    assert r.json()["status"] == "active"


# ---------------- 成员 order_index 无空洞 ----------------


async def test_batch_add_order_index_dense(client, session):
    assets = [await _asset(session, filename=f"o{i}.mp4") for i in range(3)]
    pid = await _project(client)
    await client.post(
        f"/api/projects/{pid}/assets/batch", json={"ids": [a.id for a in assets]}
    )
    # 直接查 project_asset order_index 连续 0..n-1
    from clipmind_shared.models import ProjectAsset

    orders = sorted(
        (await session.execute(
            select(ProjectAsset.order_index).where(ProjectAsset.project_id == pid)
        )).scalars().all()
    )
    assert orders == [0, 1, 2]


# ---------------- 脚本 attach/detach 守卫与保护 ----------------


async def test_attach_idempotent(client, session):
    sp = await _script(session)
    pid = await _project(client)
    r1 = await client.post(f"/api/projects/{pid}/scripts/{sp.id}")
    r2 = await client.post(f"/api/projects/{pid}/scripts/{sp.id}")
    assert r1.status_code == 200 and r2.status_code == 200
    await session.refresh(sp)
    assert sp.project_id == pid


async def test_detach_archived_409(client, session):
    sp = await _script(session)
    pid = await _project(client)
    await client.post(f"/api/projects/{pid}/scripts/{sp.id}")
    await client.post(f"/api/projects/{pid}/archive", json={"lock_version": 1})
    r = await client.delete(f"/api/projects/{pid}/scripts/{sp.id}")
    assert r.status_code == 409


async def test_detach_preserves_script_internals(client, session):
    asset = await _asset(session)
    shot = await _shot(session, asset)
    sp = await _script(session)
    hash_before = sp.script_hash
    seg = ScriptSegment(
        script_project_id=sp.id, order_index=0, segment_text="t",
        locked_shot_id=shot.id, selected_shot_id=shot.id, match_status="matched",
    )
    session.add(seg)
    await session.commit()
    await session.refresh(seg)
    cand = ScriptShotCandidate(
        script_segment_id=seg.id, generation=1, shot_id=shot.id, rank=0, final_score=1.0,
    )
    session.add(cand)
    await session.commit()
    pid = await _project(client)
    await client.post(f"/api/projects/{pid}/scripts/{sp.id}")
    await client.delete(f"/api/projects/{pid}/scripts/{sp.id}")
    await session.refresh(sp)
    await session.refresh(seg)
    assert sp.project_id is None
    assert sp.script_hash == hash_before  # detach 不改 hash
    assert seg.locked_shot_id == shot.id and seg.selected_shot_id == shot.id  # 锁定/选择不变
    assert (await session.get(ScriptShotCandidate, cand.id)) is not None  # 候选不删


# ---------------- Project 删除：FK SET NULL / CASCADE（迁移级行为）----------------


async def test_project_delete_fk_behavior(session):
    """API 无删除接口；此处直接 DB DELETE 验证迁移 FK：关联 CASCADE、脚本 SET NULL、实体存活。"""
    asset = await _asset(session)
    shot = await _shot(session, asset)
    sp = await _script(session)
    proj = Project(name="del", lock_version=1)
    session.add(proj)
    await session.commit()
    await session.refresh(proj)
    from clipmind_shared.models import CollectionShot, ProjectAsset

    session.add(ProjectAsset(project_id=proj.id, asset_id=asset.id, order_index=0))
    coll = Collection(project_id=proj.id, name="c", lock_version=1)
    session.add(coll)
    await session.commit()
    await session.refresh(coll)
    session.add(CollectionShot(collection_id=coll.id, shot_id=shot.id, order_index=0))
    sp.project_id = proj.id
    await session.commit()
    proj_id, coll_id, sp_id, asset_id, shot_id = proj.id, coll.id, sp.id, asset.id, shot.id

    await session.execute(delete(Project).where(Project.id == proj_id))
    await session.commit()
    # 会话 expire_on_commit=False，identity map 仍缓存被 DB 级联删除的行 → 清空后按 id 重查
    session.expunge_all()

    # 关联与集合 CASCADE 消失
    assert (await session.execute(
        select(ProjectAsset).where(ProjectAsset.project_id == proj_id))).first() is None
    assert (await session.get(Collection, coll_id)) is None
    # 脚本 SET NULL 且存活；Asset/Shot 存活
    sp2 = await session.get(ScriptProject, sp_id)
    assert sp2 is not None and sp2.project_id is None
    assert (await session.get(Asset, asset_id)) is not None
    assert (await session.get(Shot, shot_id)) is not None


# ---------------- 可见镜头：三源去重 / 过滤 / 分页 ----------------


async def test_visible_shot_triple_source_dedup(client, session):
    asset = await _asset(session)
    shot = await _shot(session, asset, seq=1)  # asset 派生
    pid = await _project(client)
    await client.post(f"/api/projects/{pid}/assets/batch", json={"ids": [asset.id]})
    await client.post(f"/api/projects/{pid}/shots/batch", json={"ids": [shot.id]})  # 显式
    cid = (await client.post(f"/api/projects/{pid}/collections", json={"name": "c"})).json()["id"]
    await client.post(f"/api/collections/{cid}/shots/batch", json={"ids": [shot.id]})  # 集合
    # 同一 shot 三源 → 计一次
    stats = (await client.get(f"/api/projects/{pid}/stats")).json()
    assert stats["visible_shot_count"] == 1
    allr = await client.get(f"/api/projects/{pid}/shots", params={"source": "all"})
    assert allr.json()["total"] == 1
    assert [s["id"] for s in allr.json()["items"]] == [shot.id]


async def test_visible_shot_product_and_review_filter(client, session):
    asset = await _asset(session)
    s1 = await _shot(session, asset, seq=1)
    await _shot(session, asset, seq=2)  # s2：不绑定产品/审核，应被过滤排除
    product = await _product(session)
    # s1 人工确认产品 + confirmed 审核
    session.add(ShotReviewState(
        shot_id=s1.id, shot_generation=s1.generation, review_status=ReviewStatus.CONFIRMED,
        confirmed_product_id=product.id, result_schema_version=1,
    ))
    await session.commit()
    pid = await _project(client)
    await client.post(f"/api/projects/{pid}/assets/batch", json={"ids": [asset.id]})
    # 产品筛选 → 仅 s1
    rp = await client.get(
        f"/api/projects/{pid}/shots", params={"source": "all", "product_id": product.id})
    assert [s["id"] for s in rp.json()["items"]] == [s1.id]
    # 审核状态筛选 → 仅 s1
    rr = await client.get(
        f"/api/projects/{pid}/shots", params={"source": "all", "review_status": "confirmed"})
    assert [s["id"] for s in rr.json()["items"]] == [s1.id]
    # ShotOut 不含本机路径
    item = rp.json()["items"][0]
    assert "keyframe_path" not in item and "proxy_path" not in item
    assert item["has_keyframe"] is True


async def test_visible_shot_stable_pagination(client, session):
    asset = await _asset(session)
    for i in range(5):
        await _shot(session, asset, seq=i)
    pid = await _project(client)
    await client.post(f"/api/projects/{pid}/assets/batch", json={"ids": [asset.id]})
    p1 = await client.get(
        f"/api/projects/{pid}/shots", params={"source": "all", "page": 1, "page_size": 2})
    p2 = await client.get(
        f"/api/projects/{pid}/shots", params={"source": "all", "page": 2, "page_size": 2})
    ids1 = [s["id"] for s in p1.json()["items"]]
    ids2 = [s["id"] for s in p2.json()["items"]]
    assert len(ids1) == 2 and len(ids2) == 2
    assert set(ids1).isdisjoint(ids2)  # 稳定分页无重叠
    assert p1.json()["total"] == 5


# ---------------- stats 查询数有界（无 N+1）----------------


async def test_stats_query_count_bounded(client, session):
    asset = await _asset(session)
    shots = [await _shot(session, asset, seq=i) for i in range(4)]
    pid = await _project(client)
    await client.post(f"/api/projects/{pid}/assets/batch", json={"ids": [asset.id]})
    for i in range(3):
        cid = (await client.post(
            f"/api/projects/{pid}/collections", json={"name": f"c{i}"})).json()["id"]
        await client.post(
            f"/api/collections/{cid}/shots/batch", json={"ids": [shots[i].id]})

    from app.services import project_service

    count = {"n": 0}

    def _before(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        count["n"] += 1

    event.listen(session.bind.sync_engine, "before_cursor_execute", _before)
    try:
        await project_service.get_project_stats(session, pid)
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", _before)
    # 固定查询：get(project) + 计数 + 可见镜头 ≤ 4（不随成员/集合规模增长）
    assert count["n"] <= 4, f"stats 查询数 {count['n']} 超出有界期望"
