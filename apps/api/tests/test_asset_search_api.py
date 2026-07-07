"""P2a 素材级检索 API 测试（需要 TEST_DATABASE_URL；无 embedding provider → 纯词法路径）。

锁定：词法命中/media_kind 过滤/目录产品过滤/空查询浏览/分页结构/图片 AI 分发守卫。
语义通道与全自动链由 E2E 在真实栈验证。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    AssetSearchDocument,
    ProductFamily,
    ProductMediaLink,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AssetStatus,
    CatalogStatus,
    SearchDocumentStatus,
    SearchEmbeddingStatus,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


async def _seed_sd(session) -> SourceDirectory:
    sd = SourceDirectory(
        name=f"as-{uuid.uuid4().hex[:8]}", mount_path="/app/source",
        include_extensions=["mp4", "png"], exclude_patterns=[],
        recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    return sd


async def _seed_doc(session, sd, *, kind: str, text: str) -> Asset:
    tag = uuid.uuid4().hex[:8]
    ext = "png" if kind == "image" else "mp4"
    a = Asset(
        source_directory_id=sd.id, relative_path=f"{tag}.{ext}",
        normalized_relative_path=f"{tag}.{ext}", filename=f"{tag}.{ext}",
        extension=ext, media_kind=kind, file_size=1,
        duration=None if kind == "image" else 12.0,
        status=AssetStatus.INDEXED if kind == "image" else AssetStatus.SHOT_SPLIT,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(a)
    await session.commit()
    await session.refresh(a)
    session.add(AssetSearchDocument(
        asset_id=a.id, media_kind=kind,
        effective_source="ai" if kind == "image" else "aggregate",
        search_document=text, normalized_document=text.lower(),
        search_document_hash=uuid.uuid4().hex,
        document_status=SearchDocumentStatus.INDEXED,
        embedding_status=SearchEmbeddingStatus.DEGRADED,
        is_searchable=True,
    ))
    await session.commit()
    return a


async def test_lexical_hit_and_media_kind_filter(client, session):
    sd = await _seed_sd(session)
    tag = uuid.uuid4().hex[:6]
    img = await _seed_doc(session, sd, kind="image", text=f"aaps{tag} 银色车载香薰产品白底图")
    vid = await _seed_doc(session, sd, kind="video", text=f"aaps{tag} 车内展示银色香薰的完整视频")

    r = await client.post("/api/search/assets", json={
        "query": f"aaps{tag}", "page": 1, "page_size": 10,
        "source_directory_id": sd.id,
    })
    assert r.status_code == 200, r.text
    ids = [it["asset_id"] for it in r.json()["items"]]
    assert img.id in ids and vid.id in ids

    r2 = await client.post("/api/search/assets", json={
        "query": f"aaps{tag}", "media_kind": "image", "page": 1, "page_size": 10,
        "source_directory_id": sd.id,
    })
    ids2 = [it["asset_id"] for it in r2.json()["items"]]
    assert img.id in ids2 and vid.id not in ids2
    item = next(it for it in r2.json()["items"] if it["asset_id"] == img.id)
    assert item["media_kind"] == "image" and item["document_excerpt"]


async def test_product_family_filter(client, session):
    sd = await _seed_sd(session)
    tag = uuid.uuid4().hex[:6]
    a1 = await _seed_doc(session, sd, kind="image", text=f"产品图甲 {tag}")
    a2 = await _seed_doc(session, sd, kind="image", text=f"产品图乙 {tag}")
    fam = ProductFamily(code=f"ASF{tag}", normalized_code=f"asf{tag}",
                        name_zh=f"过滤产品{tag}", status=CatalogStatus.ACTIVE)
    session.add(fam)
    await session.commit()
    await session.refresh(fam)
    session.add(ProductMediaLink(
        asset_id=a1.id, family_id=fam.id, role="related", origin="manual",
    ))
    await session.commit()

    r = await client.post("/api/search/assets", json={
        "query": f"产品图 {tag}", "product_family_id": fam.id,
        "page": 1, "page_size": 10, "source_directory_id": sd.id,
    })
    ids = [it["asset_id"] for it in r.json()["items"]]
    assert a1.id in ids and a2.id not in ids
    item = next(it for it in r.json()["items"] if it["asset_id"] == a1.id)
    assert f"过滤产品{tag}" in item["product_names"]


async def test_empty_query_browse_and_pagination(client, session):
    sd = await _seed_sd(session)
    for i in range(3):
        await _seed_doc(session, sd, kind="image", text=f"浏览测试图 {i} {uuid.uuid4().hex[:4]}")
    r = await client.post("/api/search/assets", json={
        "query": "", "media_kind": "image", "page": 1, "page_size": 2,
        "source_directory_id": sd.id,
    })
    body = r.json()
    assert body["total"] == 3 and len(body["items"]) == 2
    r2 = await client.post("/api/search/assets", json={
        "query": "", "media_kind": "image", "page": 2, "page_size": 2,
        "source_directory_id": sd.id,
    })
    ids1 = {it["asset_id"] for it in body["items"]}
    ids2 = {it["asset_id"] for it in r2.json()["items"]}
    assert len(ids2) == 1 and not (ids1 & ids2)  # 分页不重不漏


async def test_image_ai_dispatch_guard(client, session):
    """守卫回归：图片有海报可发起（202），无海报 409（不再是一律 422）。"""
    sd = await _seed_sd(session)
    tag = uuid.uuid4().hex[:8]
    img = Asset(
        source_directory_id=sd.id, relative_path=f"{tag}.png",
        normalized_relative_path=f"{tag}.png", filename=f"{tag}.png",
        extension="png", media_kind="image", file_size=1, status=AssetStatus.INDEXED,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(img)
    await session.commit()
    await session.refresh(img)

    r = await client.post(f"/api/assets/{img.id}/analyze")
    assert r.status_code == 409  # 无海报

    img.poster_path = f"assets/{img.id}/poster.webp"
    await session.commit()
    r2 = await client.post(f"/api/assets/{img.id}/analyze")
    assert r2.status_code == 202, r2.text
