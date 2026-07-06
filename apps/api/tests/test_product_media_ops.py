"""OPS 运营效率增强测试（需要 TEST_DATABASE_URL）。

锁定：批量候选注入与分组（按建议产品/目录、无候选桶、显式 targets 上限）、
操作事件记录（single/bulk 含 operation_id）、撤销语义（只撤未被修改的；
已修改/已删保留明细；重复撤销 409；不支持类型 422）、覆盖状态派生、
审计 append-only（undo 也是事件行）。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    ProductFamily,
    ProductMediaOperation,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import AssetStatus, CatalogStatus, ShotStatus
from sqlalchemy import select

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


async def _seed_sd(session) -> SourceDirectory:
    sd = SourceDirectory(
        name=f"ops-{uuid.uuid4().hex[:8]}", mount_path="/app/source",
        include_extensions=["mp4", "png"], exclude_patterns=[],
        recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    return sd


async def _seed_asset(session, sd, rel, *, kind="image") -> Asset:
    a = Asset(
        source_directory_id=sd.id, relative_path=rel,
        normalized_relative_path=rel.lower(), filename=rel.rsplit("/", 1)[-1],
        extension=rel.rsplit(".", 1)[-1], media_kind=kind, file_size=1,
        duration=None if kind == "image" else 10.0, status=AssetStatus.INDEXED,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(a)
    await session.commit()
    await session.refresh(a)
    return a


async def _seed_family(session, code, name=None) -> ProductFamily:
    fam = ProductFamily(code=code, normalized_code=code.lower(),
                        name_zh=name or f"产品{code}", status=CatalogStatus.ACTIVE)
    session.add(fam)
    await session.commit()
    await session.refresh(fam)
    return fam


# ---------------- 分组队列（批量候选注入） ----------------


async def test_grouped_queue_by_suggestion_and_directory(client, session):
    tag = uuid.uuid4().hex[:6]
    sd = await _seed_sd(session)
    fam = await _seed_family(session, f"OPS{tag}", name=f"运营产品{tag}")
    # 3 张图在含产品名的目录下、2 张在无关目录
    for i in range(3):
        await _seed_asset(session, sd, f"图库/运营产品{tag}/p{i}-{tag}.png")
    for i in range(2):
        await _seed_asset(session, sd, f"杂项{tag}/x{i}-{tag}.png")

    r = await client.get(
        "/api/product-media/unassigned/groups?kind=image&group_by=suggested_family"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    by_key = {g["key"]: g for g in body["groups"]}
    fam_group = by_key.get(f"family:{fam.id}")
    assert fam_group is not None and fam_group["count"] == 3
    assert fam_group["suggested"][0]["family_id"] == fam.id  # 组级建议
    assert len(fam_group["targets"]) == 3  # 显式 targets（绝不隐式全库）
    assert all(p["suggestions"] for p in fam_group["preview"])  # 候选已注入
    assert "none" in by_key and by_key["none"]["count"] >= 2  # 无候选桶单列

    r2 = await client.get(
        "/api/product-media/unassigned/groups?kind=image&group_by=directory"
    )
    dirs = {g["label"] for g in r2.json()["groups"]}
    assert any(f"运营产品{tag}" in d for d in dirs)
    # 未知分组方式 422
    r3 = await client.get("/api/product-media/unassigned/groups?kind=image&group_by=x")
    assert r3.status_code == 422


# ---------------- 操作审计 + 撤销 ----------------


async def test_bulk_operation_recorded_and_undo(client, session):
    tag = uuid.uuid4().hex[:6]
    sd = await _seed_sd(session)
    fam = await _seed_family(session, f"UDO{tag}")
    a1 = await _seed_asset(session, sd, f"u1-{tag}.png")
    a2 = await _seed_asset(session, sd, f"u2-{tag}.png")
    a3 = await _seed_asset(session, sd, f"u3-{tag}.png")

    r = await client.post("/api/product-media/links/bulk", json={
        "items": [{"target_type": "asset", "target_id": a.id} for a in (a1, a2, a3)],
        "family_id": fam.id, "role": "related",
    })
    body = r.json()
    op_id = body["operation_id"]
    assert op_id and len(body["completed"]) == 3
    link_ids = [c["link_id"] for c in body["completed"]]

    ops = (await client.get("/api/product-media/operations")).json()
    row = next(o for o in ops["items"] if o["id"] == op_id)
    assert row["kind"] == "bulk_link" and row["completed_count"] == 3
    assert row["undoable"] is True and row["actor_label"]

    # 其中一条被后续修改（换 primary）→ 撤销时必须保留
    modified = link_ids[1]
    pr = await client.patch(f"/api/product-media/links/{modified}",
                            json={"role": "primary"})
    assert pr.status_code == 200

    u = await client.post(f"/api/product-media/operations/{op_id}/undo")
    assert u.status_code == 200, u.text
    res = u.json()
    assert res["removed_count"] == 2 and res["kept_count"] == 1
    assert res["kept"][0]["link_id"] == modified
    # 被修改的关系仍在；其余已删
    left = (await client.get(f"/api/product-media/assets/{a2.id}/links")).json()
    assert len(left) == 1
    gone = (await client.get(f"/api/product-media/assets/{a1.id}/links")).json()
    assert gone == []
    # append-only：undo 自身是事件行；原事件标记 undone 且不可再撤
    ops2 = (await client.get("/api/product-media/operations")).json()
    kinds = [o["kind"] for o in ops2["items"][:3]]
    assert "undo" in kinds
    row2 = next(o for o in ops2["items"] if o["id"] == op_id)
    assert row2["undone_at"] and row2["undoable"] is False
    again = await client.post(f"/api/product-media/operations/{op_id}/undo")
    assert again.status_code == 409
    # undo 事件本身不可撤销
    undo_row = next(o for o in ops2["items"] if o["kind"] == "undo")
    bad = await client.post(f"/api/product-media/operations/{undo_row['id']}/undo")
    assert bad.status_code == 422


async def test_single_link_operation_and_audit_rows(client, session):
    tag = uuid.uuid4().hex[:6]
    sd = await _seed_sd(session)
    fam = await _seed_family(session, f"SGL{tag}")
    a = await _seed_asset(session, sd, f"s-{tag}.png")
    before = len(
        list((await session.execute(select(ProductMediaOperation))).scalars())
    )
    r = await client.post("/api/product-media/links", json={
        "target_type": "asset", "target_id": a.id, "family_id": fam.id,
    })
    assert r.status_code == 201
    rows = list((await session.execute(select(ProductMediaOperation))).scalars())
    assert len(rows) == before + 1
    assert rows[-1].kind == "single_link" and rows[-1].created_link_ids


# ---------------- 覆盖状态派生 ----------------


async def test_coverage_status_generic_rules(client, session):
    tag = uuid.uuid4().hex[:6]
    sd = await _seed_sd(session)
    fam = await _seed_family(session, f"COV{tag}")
    # 只有 1 张图片：缺参考图/缺视频/缺可用 Shot/没有最终成片
    img = await _seed_asset(session, sd, f"c-{tag}.png")
    await client.post("/api/product-media/links", json={
        "target_type": "asset", "target_id": img.id, "family_id": fam.id,
    })
    summary = (await client.get("/api/product-media/summary")).json()
    row = next(x for x in summary if x["family_id"] == fam.id)
    assert row["image_count"] == 1
    assert "缺参考图" in row["coverage_gaps"]
    assert "缺视频" in row["coverage_gaps"]
    assert row["coverage_status"] != "资料较完整"
    # 补视频 + Shot：对应缺口消失
    vid = await _seed_asset(session, sd, f"c-{tag}.mp4", kind="video")
    shot = Shot(asset_id=vid.id, generation=1, sequence_no=1, start_time=0.0,
                end_time=1.0, duration=1.0, detector_type="fixed",
                status=ShotStatus.READY)
    session.add(shot)
    await session.commit()
    await client.post("/api/product-media/links", json={
        "target_type": "asset", "target_id": vid.id, "family_id": fam.id,
    })
    summary2 = (await client.get("/api/product-media/summary")).json()
    row2 = next(x for x in summary2 if x["family_id"] == fam.id)
    assert "缺视频" not in row2["coverage_gaps"]
    assert "缺可用 Shot" not in row2["coverage_gaps"]
    assert "没有最终成片" in row2["coverage_gaps"]
