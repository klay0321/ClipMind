"""PM 产品素材关系测试（需要 TEST_DATABASE_URL）。

锁定：单个/批量绑定（部分失败明细）、primary 自动换主、重复 409、
merged/archived 守卫、variant 归属校验、Shot 继承/覆盖、历史 Shot 可查、
未标注过滤、图片 media_kind、搜索 hard filter、fake provider 禁写
visual_suggestion_confirmed、legacy asset_product 零改动。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    ProductFamily,
    ProductMediaLink,
    ProductVariant,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import AssetStatus, CatalogStatus, ShotStatus
from sqlalchemy import select

from app import config as app_config

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


async def _seed_sd(session) -> SourceDirectory:
    sd = SourceDirectory(
        name=f"pm-{uuid.uuid4().hex[:8]}", mount_path="/app/source",
        include_extensions=["mp4", "png"], exclude_patterns=[],
        recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    return sd


async def _seed_asset(session, sd, rel, *, kind="video") -> Asset:
    a = Asset(
        source_directory_id=sd.id, relative_path=rel,
        normalized_relative_path=rel.lower(), filename=rel.rsplit("/", 1)[-1],
        extension=rel.rsplit(".", 1)[-1], media_kind=kind, file_size=1,
        duration=10.0 if kind == "video" else None, status=AssetStatus.INDEXED,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(a)
    await session.commit()
    await session.refresh(a)
    return a


async def _seed_shot(session, asset, seq=1, *, retired=False) -> Shot:
    s = Shot(
        asset_id=asset.id, generation=1, sequence_no=seq,
        start_time=float(seq - 1), end_time=float(seq), duration=1.0,
        detector_type="fixed", status=ShotStatus.READY,
        retired_at=utcnow() if retired else None,
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


async def _seed_family(session, code, *, status=CatalogStatus.ACTIVE) -> ProductFamily:
    fam = ProductFamily(code=code, normalized_code=code.lower(),
                        name_zh=f"产品{code}", status=status)
    session.add(fam)
    await session.commit()
    await session.refresh(fam)
    return fam


async def _link(client, body, expect=201):
    r = await client.post("/api/product-media/links", json=body)
    assert r.status_code == expect, r.text
    return r.json()


# ---------------- 单个关系 / primary / 守卫 ----------------


async def test_create_primary_related_and_swap(client, session):
    sd = await _seed_sd(session)
    a = await _seed_asset(session, sd, f"v-{uuid.uuid4().hex[:6]}.mp4")
    f1 = await _seed_family(session, f"PM{uuid.uuid4().hex[:6]}")
    f2 = await _seed_family(session, f"PN{uuid.uuid4().hex[:6]}")

    l1 = await _link(client, {"target_type": "asset", "target_id": a.id,
                              "family_id": f1.id, "role": "primary"})
    assert l1["role"] == "primary" and l1["origin"] == "manual"
    assert l1["actor_label"]  # 记录操作者标签
    l2 = await _link(client, {"target_type": "asset", "target_id": a.id,
                              "family_id": f2.id, "role": "related"})
    # 换主：f2 设 primary → f1 自动降 related
    r = await client.patch(f"/api/product-media/links/{l2['id']}",
                           json={"role": "primary"})
    assert r.status_code == 200
    links = (await client.get(f"/api/product-media/assets/{a.id}/links")).json()
    roles = {x["family_id"]: x["role"] for x in links}
    assert roles[f2.id] == "primary" and roles[f1.id] == "related"
    # 重复关系 409
    await _link(client, {"target_type": "asset", "target_id": a.id,
                         "family_id": f1.id}, expect=409)


async def test_archived_merged_guard_and_variant_check(client, session):
    sd = await _seed_sd(session)
    a = await _seed_asset(session, sd, f"g-{uuid.uuid4().hex[:6]}.mp4")
    archived = await _seed_family(session, f"AR{uuid.uuid4().hex[:6]}",
                                  status=CatalogStatus.ARCHIVED)
    merged = await _seed_family(session, f"MG{uuid.uuid4().hex[:6]}",
                                status=CatalogStatus.MERGED)
    await _link(client, {"target_type": "asset", "target_id": a.id,
                         "family_id": archived.id}, expect=409)
    await _link(client, {"target_type": "asset", "target_id": a.id,
                         "family_id": merged.id}, expect=409)
    # variant 归属校验
    f1 = await _seed_family(session, f"VA{uuid.uuid4().hex[:6]}")
    f2 = await _seed_family(session, f"VB{uuid.uuid4().hex[:6]}")
    v2 = ProductVariant(family_id=f2.id, code=f"v{uuid.uuid4().hex[:5]}",
                        normalized_code=f"v{uuid.uuid4().hex[:5]}", name_zh="型号")
    session.add(v2)
    await session.commit()
    await session.refresh(v2)
    await _link(client, {"target_type": "asset", "target_id": a.id,
                         "family_id": f1.id, "variant_id": v2.id}, expect=422)


# ---------------- Shot 继承 / 覆盖 / 历史 ----------------


async def test_shot_inheritance_and_override(client, session):
    sd = await _seed_sd(session)
    a = await _seed_asset(session, sd, f"i-{uuid.uuid4().hex[:6]}.mp4")
    s1 = await _seed_shot(session, a, 1)
    s2 = await _seed_shot(session, a, 2)
    fam_v = await _seed_family(session, f"IV{uuid.uuid4().hex[:6]}")
    fam_s = await _seed_family(session, f"IS{uuid.uuid4().hex[:6]}")

    await _link(client, {"target_type": "asset", "target_id": a.id,
                         "family_id": fam_v.id, "role": "primary"})
    # s1 继承视频级
    view1 = (await client.get(f"/api/product-media/shots/{s1.id}/links")).json()
    assert view1["effective_source"] == "asset_inherited"
    assert [x["family_id"] for x in view1["effective"]] == [fam_v.id]
    # s2 覆盖为独立产品
    await _link(client, {"target_type": "shot", "target_id": s2.id,
                         "family_id": fam_s.id, "role": "primary"})
    view2 = (await client.get(f"/api/product-media/shots/{s2.id}/links")).json()
    assert view2["effective_source"] == "shot_override"
    assert [x["family_id"] for x in view2["effective"]] == [fam_s.id]
    assert [x["family_id"] for x in view2["inherited"]] == [fam_v.id]  # 视频级仍可见


async def test_historical_shot_links_visible(client, session):
    sd = await _seed_sd(session)
    a = await _seed_asset(session, sd, f"h-{uuid.uuid4().hex[:6]}.mp4")
    old_shot = await _seed_shot(session, a, 1, retired=True)
    fam = await _seed_family(session, f"HS{uuid.uuid4().hex[:6]}")
    await _link(client, {"target_type": "shot", "target_id": old_shot.id,
                         "family_id": fam.id})
    view = (await client.get(f"/api/product-media/shots/{old_shot.id}/links")).json()
    assert view["is_historical"] is True
    assert view["effective"][0]["family_id"] == fam.id  # 历史关系可查


# ---------------- 批量 ----------------


async def test_bulk_partial_failure_detail(client, session):
    sd = await _seed_sd(session)
    a1 = await _seed_asset(session, sd, f"b1-{uuid.uuid4().hex[:6]}.mp4")
    a2 = await _seed_asset(session, sd, f"b2-{uuid.uuid4().hex[:6]}.png", kind="image")
    fam = await _seed_family(session, f"BK{uuid.uuid4().hex[:6]}")
    await _link(client, {"target_type": "asset", "target_id": a1.id,
                         "family_id": fam.id})  # a1 预先绑定 → 批量中 skipped
    r = await client.post("/api/product-media/links/bulk", json={
        "items": [
            {"target_type": "asset", "target_id": a1.id},
            {"target_type": "asset", "target_id": a2.id},
            {"target_type": "asset", "target_id": 99999999},
        ],
        "family_id": fam.id, "role": "related",
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["completed"]) == 1  # 只有 a2 成功——绝不虚报整批
    assert len(body["skipped"]) == 1    # 重复 → skipped
    assert len(body["failed"]) == 1     # 不存在 → failed
    # 空选择 422
    r2 = await client.post("/api/product-media/links/bulk",
                           json={"items": [], "family_id": fam.id})
    assert r2.status_code == 422


# ---------------- 未标注 / 图片 ----------------


async def test_unassigned_queues_and_media_kind(client, session):
    sd = await _seed_sd(session)
    img = await _seed_asset(session, sd, f"u-{uuid.uuid4().hex[:6]}.png", kind="image")
    vid = await _seed_asset(session, sd, f"u-{uuid.uuid4().hex[:6]}.mp4")
    shot = await _seed_shot(session, vid, 1)
    fam = await _seed_family(session, f"UQ{uuid.uuid4().hex[:6]}")

    imgs = (await client.get("/api/product-media/unassigned?kind=image&page_size=100")).json()
    assert any(i["asset_id"] == img.id for i in imgs["items"])
    shots = (await client.get("/api/product-media/unassigned?kind=shot&page_size=100")).json()
    assert any(i["shot_id"] == shot.id for i in shots["items"])
    # 绑定 asset 后：继承语义下 shot 不再算未标注
    await _link(client, {"target_type": "asset", "target_id": vid.id,
                         "family_id": fam.id})
    shots2 = (await client.get("/api/product-media/unassigned?kind=shot&page_size=100")).json()
    assert not any(i["shot_id"] == shot.id for i in shots2["items"])
    # 图片拆镜头被拒
    r = await client.post(f"/api/assets/{img.id}/analyze-shots")
    assert r.status_code == 422


# ---------------- 搜索 hard filter ----------------


async def test_search_product_filters(client, session):
    from clipmind_shared.models import ShotSearchDocument
    from clipmind_shared.models.enums import (
        SearchDocumentStatus,
        SearchEmbeddingStatus,
    )

    sd = await _seed_sd(session)
    a1 = await _seed_asset(session, sd, f"s1-{uuid.uuid4().hex[:6]}.mp4")
    a2 = await _seed_asset(session, sd, f"s2-{uuid.uuid4().hex[:6]}.mp4")
    s1 = await _seed_shot(session, a1, 1)
    s2 = await _seed_shot(session, a2, 1)
    for sh in (s1, s2):
        session.add(ShotSearchDocument(
            shot_id=sh.id, shot_generation=1, asset_id=sh.asset_id,
            document_status=SearchDocumentStatus.INDEXED,
            embedding_status=SearchEmbeddingStatus.DEGRADED,
            is_searchable=True, search_document="pm 过滤 测试",
            normalized_document="pm 过滤 测试",
        ))
    await session.commit()
    fam = await _seed_family(session, f"SF{uuid.uuid4().hex[:6]}")
    await _link(client, {"target_type": "asset", "target_id": a1.id,
                         "family_id": fam.id})

    async def search(extra):
        r = await client.post("/api/search/shots", json={
            "query": "", "search_mode": "lexical", "page": 1, "page_size": 100,
            **extra,
        })
        assert r.status_code == 200, r.text
        return {i["shot_id"] for i in r.json()["items"]}

    with_fam = await search({"product_family_id": fam.id})
    assert s1.id in with_fam and s2.id not in with_fam  # hard filter（含继承）
    unassigned = await search({"unassigned_only": True})
    assert s2.id in unassigned and s1.id not in unassigned
    assigned = await search({"has_product_assignment": True})
    assert s1.id in assigned and s2.id not in assigned
    # 排序语义不变：不带过滤时两者都在（分数不受产品影响）
    base = await search({})
    assert {s1.id, s2.id} <= base


# ---------------- 视觉候选来源守卫 / legacy 兼容 ----------------


async def test_visual_confirm_requires_local_provider(client, session, monkeypatch):
    settings = app_config.get_settings()
    monkeypatch.setattr(settings, "visual_embedding_provider", "fake")
    sd = await _seed_sd(session)
    a = await _seed_asset(session, sd, f"vc-{uuid.uuid4().hex[:6]}.mp4")
    fam = await _seed_family(session, f"VC{uuid.uuid4().hex[:6]}")
    # fake provider 下 visual_suggestion_confirmed 拒绝
    await _link(client, {"target_type": "asset", "target_id": a.id,
                         "family_id": fam.id,
                         "origin": "visual_suggestion_confirmed"}, expect=422)
    # local provider 下允许
    monkeypatch.setattr(settings, "visual_embedding_provider", "local")
    out = await _link(client, {"target_type": "asset", "target_id": a.id,
                               "family_id": fam.id,
                               "origin": "visual_suggestion_confirmed"})
    assert out["origin"] == "visual_suggestion_confirmed"


async def test_legacy_asset_product_untouched(client, session):
    """新关系读写不触碰 legacy asset_product 表。"""
    from sqlalchemy import text

    before = (await session.execute(text("SELECT count(*) FROM asset_product"))).scalar()
    sd = await _seed_sd(session)
    a = await _seed_asset(session, sd, f"lg-{uuid.uuid4().hex[:6]}.mp4")
    fam = await _seed_family(session, f"LG{uuid.uuid4().hex[:6]}")
    link = await _link(client, {"target_type": "asset", "target_id": a.id,
                                "family_id": fam.id})
    r = await client.delete(f"/api/product-media/links/{link['id']}")
    assert r.status_code == 204
    after = (await session.execute(text("SELECT count(*) FROM asset_product"))).scalar()
    assert before == after
    # 删除后确实移除
    rows = (
        await session.execute(
            select(ProductMediaLink).where(ProductMediaLink.id == link["id"])
        )
    ).scalar_one_or_none()
    assert rows is None
