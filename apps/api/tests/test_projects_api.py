"""PR-06A 项目 API 测试（需要 TEST_DATABASE_URL）。

覆盖：Project CRUD、乐观锁、归档守卫、素材/镜头/产品成员（批量/移除/重排）、
可见镜头并集、统计、脚本 attach/detach、删除安全（删关联不删实体）。
"""

from __future__ import annotations

import os

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    Product,
    ScriptExport,
    ScriptProject,
    ScriptSegment,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AssetStatus,
    ExportStatus,
    ScriptStatus,
    ShotStatus,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


# ---------------- seed 助手 ----------------


async def _seed_asset(session, *, filename="片段 A.mp4") -> Asset:
    sd = SourceDirectory(
        name="d",
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
        width=1920,
        height=1080,
        video_codec="h264",
        audio_codec="aac",
        status=AssetStatus.INDEXED,
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


async def _seed_shot(session, asset, *, seq=1, status=ShotStatus.READY) -> Shot:
    shot = Shot(
        asset_id=asset.id,
        generation=1,
        sequence_no=seq,
        start_time=0.0,
        end_time=2.0,
        duration=2.0,
        detector_type="fixed",
        status=status,
        keyframe_path=f"keyframes/{asset.id}-{seq}.jpg",
        proxy_path=f"proxies/{asset.id}-{seq}.mp4",
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    return shot


async def _seed_product(session, *, name="ProductA") -> Product:
    p = Product(name=name, normalized_name=name.lower())
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def _seed_script(session, *, name="脚本A", project_id=None) -> ScriptProject:
    sp = ScriptProject(
        name=name,
        raw_script="raw",
        script_hash=f"hash-{name}",
        status=ScriptStatus.PARSED,
        project_id=project_id,
    )
    session.add(sp)
    await session.commit()
    await session.refresh(sp)
    return sp


async def _create_project(client, name="项目A", description=None):
    r = await client.post("/api/projects", json={"name": name, "description": description})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------- Project CRUD / 乐观锁 ----------------


async def test_create_and_get_project(client):
    body = await _create_project(client, name="  夏季广告  ", description="desc")
    assert body["name"] == "夏季广告"  # strip
    assert body["status"] == "active"
    assert body["lock_version"] == 1
    assert body["archived_at"] is None
    pid = body["id"]
    g = await client.get(f"/api/projects/{pid}")
    assert g.status_code == 200
    assert g.json()["id"] == pid


async def test_create_empty_name_rejected(client):
    r = await client.post("/api/projects", json={"name": "   "})
    assert r.status_code == 422


async def test_empty_project_allowed_and_stats_zero(client):
    pid = (await _create_project(client))["id"]
    s = await client.get(f"/api/projects/{pid}/stats")
    assert s.status_code == 200
    data = s.json()
    assert data["asset_count"] == 0
    assert data["visible_shot_count"] == 0
    assert data["collection_count"] == 0


async def test_duplicate_names_allowed(client):
    a = await _create_project(client, name="同名")
    b = await _create_project(client, name="同名")
    assert a["id"] != b["id"]


async def test_no_delete_endpoint(client):
    pid = (await _create_project(client))["id"]
    r = await client.delete(f"/api/projects/{pid}")
    assert r.status_code == 405  # Method Not Allowed：本阶段无删除接口


async def test_update_optimistic_lock(client):
    p = await _create_project(client)
    pid = p["id"]
    # 正确版本：改名成功，lock_version+1
    r = await client.patch(f"/api/projects/{pid}", json={"lock_version": 1, "name": "新名"})
    assert r.status_code == 200
    assert r.json()["name"] == "新名"
    assert r.json()["lock_version"] == 2
    # 过期版本：409
    r2 = await client.patch(f"/api/projects/{pid}", json={"lock_version": 1, "name": "X"})
    assert r2.status_code == 409


async def test_update_rejects_unknown_field(client):
    p = await _create_project(client)
    r = await client.patch(
        f"/api/projects/{p['id']}", json={"lock_version": 1, "status": "archived"}
    )
    assert r.status_code == 422  # extra=forbid


async def test_list_pagination_and_status_filter(client):
    ids = [(await _create_project(client, name=f"P{i}"))["id"] for i in range(3)]
    # 归档其中一个
    await client.post(f"/api/projects/{ids[0]}/archive", json={"lock_version": 1})
    r = await client.get("/api/projects", params={"page": 1, "page_size": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    ra = await client.get("/api/projects", params={"status": "archived"})
    assert ra.json()["total"] == 1
    rac = await client.get("/api/projects", params={"status": "active"})
    assert rac.json()["total"] == 2


# ---------------- 归档 / 恢复 ----------------


async def test_archive_unarchive_and_guard(client, session):
    asset = await _seed_asset(session)
    pid = (await _create_project(client))["id"]
    # 归档
    r = await client.post(f"/api/projects/{pid}/archive", json={"lock_version": 1})
    assert r.status_code == 200
    assert r.json()["status"] == "archived"
    assert r.json()["archived_at"] is not None
    lv = r.json()["lock_version"]
    # 归档后仍可读取
    assert (await client.get(f"/api/projects/{pid}")).status_code == 200
    assert (await client.get(f"/api/projects/{pid}/stats")).status_code == 200
    # 归档后写操作 409：改名、加成员
    assert (
        await client.patch(f"/api/projects/{pid}", json={"lock_version": lv, "name": "x"})
    ).status_code == 409
    assert (
        await client.post(
            f"/api/projects/{pid}/assets/batch", json={"ids": [asset.id]}
        )
    ).status_code == 409
    # 恢复
    u = await client.post(f"/api/projects/{pid}/unarchive", json={"lock_version": lv})
    assert u.status_code == 200
    assert u.json()["status"] == "active"
    assert u.json()["archived_at"] is None


async def test_archive_idempotent_and_lock_conflict(client):
    pid = (await _create_project(client))["id"]
    r1 = await client.post(f"/api/projects/{pid}/archive", json={"lock_version": 1})
    assert r1.status_code == 200
    # 幂等：再次归档（任意 lock_version）返回已归档
    r2 = await client.post(f"/api/projects/{pid}/archive", json={"lock_version": 999})
    assert r2.status_code == 200
    assert r2.json()["status"] == "archived"


# ---------------- 成员：批量 / 重复 / 缺失 / 移除 ----------------


async def test_batch_add_assets_partial(client, session):
    asset1 = await _seed_asset(session, filename="a1.mp4")
    asset2 = await _seed_asset(session, filename="a2.mp4")
    pid = (await _create_project(client))["id"]
    # 加入 asset1, asset2, 一个不存在的 id, 以及重复 asset1
    r = await client.post(
        f"/api/projects/{pid}/assets/batch",
        json={"ids": [asset1.id, asset2.id, 999999, asset1.id]},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["completed"]) == {asset1.id, asset2.id}
    assert body["failed"][0]["id"] == 999999
    assert body["skipped"] == []  # 同一请求内去重，不算 skipped
    # 再次加入 asset1 → skipped（重复成员幂等）
    r2 = await client.post(
        f"/api/projects/{pid}/assets/batch", json={"ids": [asset1.id]}
    )
    assert r2.json()["skipped"] == [asset1.id]
    assert r2.json()["completed"] == []


async def test_remove_asset_keeps_entity(client, session):
    asset = await _seed_asset(session)
    pid = (await _create_project(client))["id"]
    await client.post(f"/api/projects/{pid}/assets/batch", json={"ids": [asset.id]})
    d = await client.delete(f"/api/projects/{pid}/assets/{asset.id}")
    assert d.status_code == 204
    # 关联不存在 → 404
    d2 = await client.delete(f"/api/projects/{pid}/assets/{asset.id}")
    assert d2.status_code == 404
    # 实体仍在
    assert await session.get(Asset, asset.id) is not None


async def test_reorder_assets(client, session):
    a1 = await _seed_asset(session, filename="r1.mp4")
    a2 = await _seed_asset(session, filename="r2.mp4")
    a3 = await _seed_asset(session, filename="r3.mp4")
    pid = (await _create_project(client))["id"]
    await client.post(
        f"/api/projects/{pid}/assets/batch", json={"ids": [a1.id, a2.id, a3.id]}
    )
    # 重排：必须覆盖全部成员，用项目 lock_version
    r = await client.post(
        f"/api/projects/{pid}/assets/reorder",
        json={"ids": [a3.id, a1.id, a2.id], "lock_version": 1},
    )
    assert r.status_code == 200
    assert r.json()["lock_version"] == 2
    # 顺序生效
    lst = await client.get(f"/api/projects/{pid}/assets")
    order = [it["asset"]["id"] for it in lst.json()["items"]]
    assert order == [a3.id, a1.id, a2.id]
    # 不完整集合 → 422
    bad = await client.post(
        f"/api/projects/{pid}/assets/reorder",
        json={"ids": [a1.id], "lock_version": 2},
    )
    assert bad.status_code == 422
    # 过期 lock_version → 409
    conflict = await client.post(
        f"/api/projects/{pid}/assets/reorder",
        json={"ids": [a1.id, a2.id, a3.id], "lock_version": 1},
    )
    assert conflict.status_code == 409


async def test_batch_add_products_and_shots(client, session):
    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset, seq=1)
    product = await _seed_product(session)
    pid = (await _create_project(client))["id"]
    rp = await client.post(
        f"/api/projects/{pid}/products/batch", json={"ids": [product.id]}
    )
    assert rp.json()["completed"] == [product.id]
    rs = await client.post(f"/api/projects/{pid}/shots/batch", json={"ids": [shot.id]})
    assert rs.json()["completed"] == [shot.id]
    # 产品列表
    lp = await client.get(f"/api/projects/{pid}/products")
    assert lp.json()["total"] == 1
    # 移除产品不删 Product
    await client.delete(f"/api/projects/{pid}/products/{product.id}")
    assert await session.get(Product, product.id) is not None


# ---------------- 可见镜头并集 ----------------


async def test_visible_shots_union_dedup(client, session):
    asset = await _seed_asset(session)
    s_asset1 = await _seed_shot(session, asset, seq=1)
    s_asset2 = await _seed_shot(session, asset, seq=2)
    # 一个独立资产的镜头用于显式加入
    asset2 = await _seed_asset(session, filename="b.mp4")
    s_explicit = await _seed_shot(session, asset2, seq=1)
    pid = (await _create_project(client))["id"]
    # 加 asset（带来 s_asset1, s_asset2）
    await client.post(f"/api/projects/{pid}/assets/batch", json={"ids": [asset.id]})
    # 显式加入 s_explicit + 同时显式加入 s_asset1（已经因 asset 可见 → 并集去重）
    await client.post(
        f"/api/projects/{pid}/shots/batch", json={"ids": [s_explicit.id, s_asset1.id]}
    )
    # 集合再加入 s_asset2（已可见）+ s_explicit（已可见）
    cr = await client.post(
        f"/api/projects/{pid}/collections", json={"name": "C"}
    )
    cid = cr.json()["id"]
    await client.post(
        f"/api/collections/{cid}/shots/batch",
        json={"ids": [s_asset2.id, s_explicit.id]},
    )
    # 可见镜头 = {s_asset1, s_asset2, s_explicit} 去重 = 3
    stats = (await client.get(f"/api/projects/{pid}/stats")).json()
    assert stats["visible_shot_count"] == 3
    assert stats["explicit_shot_count"] == 2  # project_shot 行数
    # source 过滤
    all_shots = await client.get(f"/api/projects/{pid}/shots", params={"source": "all"})
    assert all_shots.json()["total"] == 3
    asset_src = await client.get(f"/api/projects/{pid}/shots", params={"source": "asset"})
    assert asset_src.json()["total"] == 2
    explicit_src = await client.get(
        f"/api/projects/{pid}/shots", params={"source": "explicit"}
    )
    assert explicit_src.json()["total"] == 2


# ---------------- 统计 ----------------


async def test_stats_match_facts(client, session):
    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset, seq=1)
    product = await _seed_product(session)
    pid = (await _create_project(client))["id"]
    await client.post(f"/api/projects/{pid}/assets/batch", json={"ids": [asset.id]})
    await client.post(f"/api/projects/{pid}/products/batch", json={"ids": [product.id]})
    # 脚本 + 段落（1 锁定 + 1 gap）+ 完成的导出
    script = await _seed_script(session, project_id=pid)
    session.add(
        ScriptSegment(
            script_project_id=script.id,
            order_index=0,
            segment_text="t",
            locked_shot_id=shot.id,
            match_status="matched",
        )
    )
    session.add(
        ScriptSegment(
            script_project_id=script.id,
            order_index=1,
            segment_text="t2",
            match_status="gap",
        )
    )
    session.add(
        ScriptExport(
            script_project_id=script.id,
            export_uuid="u-1",
            status=ExportStatus.COMPLETED,
            export_format="csv",
            queued_at=utcnow(),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    await session.commit()
    data = (await client.get(f"/api/projects/{pid}/stats")).json()
    assert data["asset_count"] == 1
    assert data["product_count"] == 1
    assert data["script_count"] == 1
    assert data["active_script_count"] == 1
    assert data["locked_segment_count"] == 1
    assert data["gap_segment_count"] == 1
    assert data["completed_script_export_count"] == 1
    assert data["visible_shot_count"] == 1


# ---------------- 脚本归属 ----------------


async def test_script_attach_detach(client, session):
    script = await _seed_script(session)  # project_id NULL（历史脚本）
    assert script.project_id is None
    pid = (await _create_project(client))["id"]
    a = await client.post(f"/api/projects/{pid}/scripts/{script.id}")
    assert a.status_code == 200
    await session.refresh(script)
    assert script.project_id == pid
    # 列表
    lst = await client.get(f"/api/projects/{pid}/scripts")
    assert lst.json()["total"] == 1
    # detach
    d = await client.delete(f"/api/projects/{pid}/scripts/{script.id}")
    assert d.status_code == 200
    await session.refresh(script)
    assert script.project_id is None
    # detach 不属于本项目的脚本 → 404
    d2 = await client.delete(f"/api/projects/{pid}/scripts/{script.id}")
    assert d2.status_code == 404


async def test_attach_archived_project_409(client, session):
    script = await _seed_script(session)
    pid = (await _create_project(client))["id"]
    await client.post(f"/api/projects/{pid}/archive", json={"lock_version": 1})
    r = await client.post(f"/api/projects/{pid}/scripts/{script.id}")
    assert r.status_code == 409


async def test_attach_missing_script_404(client):
    pid = (await _create_project(client))["id"]
    r = await client.post(f"/api/projects/{pid}/scripts/999999")
    assert r.status_code == 404
