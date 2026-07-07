"""IMG-SEARCH 以图搜图测试（需要 TEST_DATABASE_URL；FakeVisualProvider）。

锁定：同族向量排前且分数递减；kind 过滤；跨 provider/模型向量不参与；
目标已删除时向量行滞后不报错；403（未开启）/422（类型）边界；零写入。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.ai.visual import FakeVisualProvider
from clipmind_shared.models import (
    Asset,
    Shot,
    SourceDirectory,
    VisualMediaEmbedding,
)
from clipmind_shared.models.enums import AssetStatus, ShotStatus
from sqlalchemy import select

from app import config as app_config

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)

_PROVIDER = FakeVisualProvider()
_IDENT = _PROVIDER.identity()


@pytest.fixture
def visual_settings(monkeypatch):
    settings = app_config.get_settings()
    monkeypatch.setattr(settings, "visual_recognition_enabled", True)
    monkeypatch.setattr(settings, "visual_embedding_provider", "fake")
    return settings


def _vec(marker: str, salt: str = "") -> list[float]:
    return _PROVIDER.embed_images([f"FAKE:{marker}:{salt}".encode()])[0]


async def _seed_asset(session, *, media_kind="image") -> Asset:
    tag = uuid.uuid4().hex[:8]
    sd = SourceDirectory(
        name=f"vs-{tag}", mount_path="/app/source", include_extensions=["jpg"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    from clipmind_shared.db.base import utcnow

    asset = Asset(
        source_directory_id=sd.id, relative_path=f"{tag}.jpg",
        normalized_relative_path=f"{tag}.jpg", filename=f"{tag}.jpg", extension="jpg",
        file_size=10, media_kind=media_kind, status=AssetStatus.INDEXED,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    return asset


async def _seed_shot(session, asset: Asset) -> Shot:
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=1, start_time=0.0, end_time=2.0,
        duration=2.0, detector_type="fixed", status=ShotStatus.READY,
    )
    session.add(shot)
    await session.commit()
    return shot


async def _seed_embedding(
    session, *, target_type: str, target_id: int, marker: str,
    provider: str | None = None, model: str | None = None,
) -> VisualMediaEmbedding:
    row = VisualMediaEmbedding(
        target_type=target_type, target_id=target_id,
        provider=provider or _IDENT.provider, model_id=model or _IDENT.model_id,
        dimension=_IDENT.dimension, embedding=_vec(marker, salt=f"{target_type}{target_id}"),
        status="completed", source_sha256=uuid.uuid4().hex,
    )
    session.add(row)
    await session.commit()
    return row


def _query_file(marker: str):
    return {"file": ("q.png", f"FAKE:{marker}:query".encode(), "image/png")}


async def test_by_image_orders_same_family_first(client, session, visual_settings):
    a_same = await _seed_asset(session)
    a_other = await _seed_asset(session)
    shot_asset = await _seed_asset(session, media_kind="video")
    s_same = await _seed_shot(session, shot_asset)
    await _seed_embedding(session, target_type="asset", target_id=a_same.id, marker="vsA")
    await _seed_embedding(session, target_type="asset", target_id=a_other.id, marker="vsOther")
    await _seed_embedding(session, target_type="shot", target_id=s_same.id, marker="vsA")

    r = await client.post("/api/search/by-image", files=_query_file("vsA"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "fake" and body["total_indexed"] >= 3
    hits = body["hits"]
    top2 = {(h["kind"], h.get("asset_id"), h.get("shot_id")) for h in hits[:2]}
    assert ("asset", a_same.id, None) in top2
    assert ("shot", shot_asset.id, s_same.id) in top2
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert hits[0]["score"] > 0.99  # 同族 ≈ 1
    # 异族排后且分数低
    other = next(h for h in hits if h.get("asset_id") == a_other.id and h["kind"] == "asset")
    assert other["score"] < 0.6


async def test_by_image_kind_filter_and_foreign_model_excluded(
    client, session, visual_settings
):
    a = await _seed_asset(session)
    shot_asset = await _seed_asset(session, media_kind="video")
    s = await _seed_shot(session, shot_asset)
    await _seed_embedding(session, target_type="asset", target_id=a.id, marker="vsK")
    await _seed_embedding(session, target_type="shot", target_id=s.id, marker="vsK")
    # 异 provider/模型向量绝不参与（跨模型距离无意义）
    await _seed_embedding(
        session, target_type="asset", target_id=a.id, marker="vsK",
        provider="local", model="google/siglip-base-patch16-224",
    )

    r = await client.post("/api/search/by-image?kind=shot", files=_query_file("vsK"))
    assert r.status_code == 200
    body = r.json()
    assert all(h["kind"] == "shot" for h in body["hits"])
    r2 = await client.post("/api/search/by-image?kind=asset", files=_query_file("vsK"))
    kinds2 = {h["kind"] for h in r2.json()["hits"]}
    assert kinds2 <= {"asset"}
    # total_indexed 只统计 fake 模型的行
    ids_in_hits = {h.get("asset_id") for h in r2.json()["hits"]}
    assert a.id in ids_in_hits


async def test_by_image_stale_embedding_row_skipped(client, session, visual_settings):
    """目标已删除但向量行滞后：跳过该行，不 500。"""
    a = await _seed_asset(session)
    await _seed_embedding(session, target_type="asset", target_id=a.id, marker="vsDel")
    await session.delete(
        (await session.execute(select(Asset).where(Asset.id == a.id))).scalar_one()
    )
    await session.commit()
    r = await client.post("/api/search/by-image", files=_query_file("vsDel"))
    assert r.status_code == 200
    assert all(h.get("asset_id") != a.id or h["kind"] != "asset" for h in r.json()["hits"])


async def test_by_image_guards(client, session, visual_settings, monkeypatch):
    # 未开启 → 403
    monkeypatch.setattr(visual_settings, "visual_recognition_enabled", False)
    r = await client.post("/api/search/by-image", files=_query_file("vsG"))
    assert r.status_code == 403
    monkeypatch.setattr(visual_settings, "visual_recognition_enabled", True)
    # 非图片类型 → 422
    r2 = await client.post(
        "/api/search/by-image",
        files={"file": ("x.txt", b"not an image", "text/plain")},
    )
    assert r2.status_code == 422
    # 未知 kind → 422
    r3 = await client.post(
        "/api/search/by-image?kind=nope", files=_query_file("vsG")
    )
    assert r3.status_code == 422
