"""AAP（P0+P1）API 测试（需要 TEST_DATABASE_URL）。

锁定：AI 发起守卫（图片 422 / 无可用镜头 409——假成功修复的 API 层）、
media_kind 透出与筛选、素材行内真实产品名、batch-analyze 语义（显式条件、
按阶段收敛、幂等跳过、绝不隐式全库）、processing overview 结构与计数。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIShotAnalysis,
    Asset,
    ProductFamily,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AIShotAnalysisStatus,
    AssetStatus,
    CatalogStatus,
    ShotStatus,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


async def _seed_sd(session) -> SourceDirectory:
    sd = SourceDirectory(
        name=f"aap-{uuid.uuid4().hex[:8]}", mount_path="/app/source",
        include_extensions=["mp4", "png"], exclude_patterns=[],
        recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    return sd


async def _seed_asset(session, sd, *, kind="video", status=AssetStatus.INDEXED) -> Asset:
    tag = uuid.uuid4().hex[:8]
    ext = "png" if kind == "image" else "mp4"
    a = Asset(
        source_directory_id=sd.id, relative_path=f"{tag}.{ext}",
        normalized_relative_path=f"{tag}.{ext}", filename=f"{tag}.{ext}",
        extension=ext, media_kind=kind, file_size=1,
        duration=None if kind == "image" else 10.0, status=status,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(a)
    await session.commit()
    await session.refresh(a)
    return a


async def _seed_shot(session, asset, seq=1) -> Shot:
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=seq, start_time=0.0,
        end_time=1.0, duration=1.0, detector_type="fixed", status=ShotStatus.READY,
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    return shot


# ---------------- P0：AI 发起守卫（假成功修复） ----------------


async def test_ai_analyze_image_returns_422(client, session):
    sd = await _seed_sd(session)
    img = await _seed_asset(session, sd, kind="image")
    r = await client.post(f"/api/assets/{img.id}/analyze")
    assert r.status_code == 422
    assert "图片" in r.json()["detail"]


async def test_ai_analyze_without_ready_shots_returns_409(client, session):
    sd = await _seed_sd(session)
    vid = await _seed_asset(session, sd)  # INDEXED，无任何镜头
    r = await client.post(f"/api/assets/{vid.id}/analyze")
    assert r.status_code == 409
    assert "拆镜头" in r.json()["detail"]
    # 有可用镜头后放行（202）
    await _seed_shot(session, vid)
    r2 = await client.post(f"/api/assets/{vid.id}/analyze")
    assert r2.status_code == 202


# ---------------- P0：media_kind 透出 + 行内真实产品名 ----------------


async def test_media_kind_filter_and_product_names(client, session):
    sd = await _seed_sd(session)
    vid = await _seed_asset(session, sd)
    img = await _seed_asset(session, sd, kind="image")
    fam = ProductFamily(
        code=f"AAP{uuid.uuid4().hex[:6]}", normalized_code=f"aap{uuid.uuid4().hex[:6]}",
        name_zh="测试产品甲", status=CatalogStatus.ACTIVE,
    )
    session.add(fam)
    await session.commit()
    await session.refresh(fam)
    lr = await client.post("/api/product-media/links", json={
        "target_type": "asset", "target_id": img.id, "family_id": fam.id,
    })
    assert lr.status_code == 201

    r = await client.get(
        f"/api/assets?page=1&page_size=50&media_kind=image&source_directory_id={sd.id}"
    )
    items = r.json()["items"]
    assert [it["id"] for it in items] == [img.id]
    assert items[0]["media_kind"] == "image"
    assert items[0]["product_names"] == ["测试产品甲"]  # 真实绑定，非占位

    r2 = await client.get(
        f"/api/assets?page=1&page_size=50&media_kind=video&source_directory_id={sd.id}"
    )
    ids2 = [it["id"] for it in r2.json()["items"]]
    assert vid.id in ids2 and img.id not in ids2
    # 非法值 422
    r3 = await client.get("/api/assets?page=1&page_size=10&media_kind=audio")
    assert r3.status_code == 422


# ---------------- P1：batch-analyze ----------------


async def test_batch_analyze_requires_explicit_scope(client):
    r = await client.post("/api/assets/batch-analyze", json={"stages": ["shots"]})
    assert r.status_code == 422  # 绝不隐式全库
    r2 = await client.post("/api/assets/batch-analyze", json={
        "asset_ids": [1], "stages": [],
    })
    assert r2.status_code == 422


async def test_batch_analyze_stage_semantics(client, session):
    sd = await _seed_sd(session)
    v_unsplit = await _seed_asset(session, sd)                        # 待拆
    v_unlabeled = await _seed_asset(session, sd, status=AssetStatus.SHOT_SPLIT)
    s2 = await _seed_shot(session, v_unlabeled)                        # 待打标
    v_done = await _seed_asset(session, sd, status=AssetStatus.SHOT_SPLIT)
    s3 = await _seed_shot(session, v_done)
    session.add(AIShotAnalysis(
        shot_id=s3.id, asset_id=v_done.id,
        status=AIShotAnalysisStatus.COMPLETED,
    ))
    img = await _seed_asset(session, sd, kind="image")                 # 图片不参与
    await session.commit()

    r = await client.post("/api/assets/batch-analyze", json={
        "source_directory_id": sd.id, "stages": ["shots", "ai"],
    })
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["enqueued_shots"] == 1   # 只有 v_unsplit
    assert body["enqueued_ai"] == 1      # 只有 v_unlabeled（v_done 已全打标）
    assert body["truncated"] is False

    # 再次提交：v_unsplit 已有活动 media run、v_unlabeled 已有活动 ai run → 幂等跳过
    r2 = await client.post("/api/assets/batch-analyze", json={
        "source_directory_id": sd.id, "stages": ["shots", "ai"],
    })
    body2 = r2.json()
    assert body2["enqueued_shots"] == 0 and body2["enqueued_ai"] == 0
    assert body2["skipped_active"] == 2

    # 显式 asset_ids 形式：图片被条件排除（matched 不含）
    r3 = await client.post("/api/assets/batch-analyze", json={
        "asset_ids": [img.id], "stages": ["shots", "ai"],
    })
    assert r3.json()["matched"] == 0
    assert v_unsplit.id and s2.id  # 场景引用（见上方断言语义）


# ---------------- P1：processing overview ----------------


async def test_processing_overview_counts_and_config(client, session):
    sd = await _seed_sd(session)
    vid = await _seed_asset(session, sd, status=AssetStatus.SHOT_SPLIT)
    await _seed_shot(session, vid)
    r = await client.get("/api/processing/overview")
    assert r.status_code == 200
    body = r.json()
    for key in ("scan", "shots", "ai"):
        assert set(body[key]) == {"queued", "running"}
    assert body["totals"]["videos_total"] >= 1
    assert body["totals"]["videos_with_shots"] >= 1
    assert body["totals"]["shots_ready"] >= 1
    cfg = body["config"]
    assert set(cfg) == {
        "auto_analyze_on_scan", "auto_ai_after_shots", "scan_interval_minutes",
        "ai_daily_budget", "ai_spent_today",
    }
    assert cfg["ai_spent_today"] >= 0.0
