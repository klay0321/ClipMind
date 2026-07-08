"""OBS 可观测性测试（需要 TEST_DATABASE_URL）。

锁定：单素材 trace 六环节（图片健康链 / 图片缺 AI=lagging / 图片驳回=excluded
而非故障 / 视频缺文档=lagging / 视频 AI failed）；trace 404；管线健康计数口径
（播种滞后数据后非零）；Redis 不可达时队列深度全 None 降级不 500。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIShotAnalysis,
    Asset,
    AssetImageAnalysis,
    AssetImageReviewState,
    AssetSearchDocument,
    MediaProcessingRun,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AIShotAnalysisStatus,
    AssetStatus,
    MediaRunStatus,
    ReviewStatus,
    SearchDocumentStatus,
    SearchEmbeddingStatus,
    ShotStatus,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)

AI_RESULT = {
    "one_line": "一段桌面充电演示。",
    "search_keywords": ["充电"],
    "confidence": 0.9,
}


async def _seed_asset(session, *, media_kind: str) -> Asset:
    tag = uuid.uuid4().hex[:8]
    ext = "jpg" if media_kind == "image" else "mp4"
    sd = SourceDirectory(
        name=f"obs-{tag}", mount_path="/app/source", include_extensions=[ext],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    asset = Asset(
        source_directory_id=sd.id, relative_path=f"{tag}.{ext}",
        normalized_relative_path=f"{tag}.{ext}", filename=f"{tag}.{ext}", extension=ext,
        file_size=10, media_kind=media_kind, status=AssetStatus.INDEXED,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
        poster_path="posters/p.webp" if media_kind == "image" else None,
    )
    session.add(asset)
    await session.commit()
    return asset


def _stage(body: dict, name: str) -> dict:
    return next(s for s in body["stages"] if s["stage"] == name)


async def test_trace_404(client):
    resp = await client.get("/api/assets/999999/trace")
    assert resp.status_code == 404


async def test_trace_image_healthy_chain(client, session):
    """图片全绿链：scan/derive/ai/review/document 均 ok（AI 临时生效可搜）。"""
    asset = await _seed_asset(session, media_kind="image")
    session.add(
        AssetImageAnalysis(
            asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
            parsed_result=AI_RESULT, input_fingerprint=uuid.uuid4().hex,
        )
    )
    session.add(
        AssetSearchDocument(
            asset_id=asset.id, media_kind="image", effective_source="ai",
            search_document="桌面充电", normalized_document="桌面充电",
            search_document_hash="h1", document_template_version=1,
            document_status=SearchDocumentStatus.INDEXED,
            embedding_status=SearchEmbeddingStatus.COMPLETED,
            is_searchable=True, retry_count=0, indexed_at=utcnow(),
        )
    )
    await session.commit()

    resp = await client.get(f"/api/assets/{asset.id}/trace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["media_kind"] == "image"
    assert [s["stage"] for s in body["stages"]] == [
        "scan", "derive", "ai", "review", "document", "embedding",
    ]
    assert _stage(body, "scan")["status"] == "ok"
    assert _stage(body, "derive")["status"] == "ok"
    assert _stage(body, "ai")["status"] == "ok"
    review = _stage(body, "review")
    assert review["status"] == "ok"
    assert review["detail"]["effective_source"] == "ai"
    assert _stage(body, "document")["status"] == "ok"
    # 无视觉向量 → embedding 环节如实报 lagging（以图搜图不覆盖）
    assert _stage(body, "embedding")["status"] == "lagging"


async def test_trace_image_missing_ai_is_lagging(client, session):
    """图片缺 AI：ai 环节 lagging 且 hint 指向下一步；document 也未建。"""
    asset = await _seed_asset(session, media_kind="image")
    resp = await client.get(f"/api/assets/{asset.id}/trace")
    body = resp.json()
    ai = _stage(body, "ai")
    assert ai["status"] == "lagging"
    assert "AI" in ai["hint"]
    assert _stage(body, "document")["status"] == "lagging"


async def test_trace_image_rejected_is_excluded_not_failure(client, session):
    """驳回后：review/document 标 excluded（决定而非故障），绝不标 failed。"""
    asset = await _seed_asset(session, media_kind="image")
    session.add(
        AssetImageAnalysis(
            asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
            parsed_result=AI_RESULT, input_fingerprint=uuid.uuid4().hex,
        )
    )
    session.add(
        AssetImageReviewState(
            asset_id=asset.id, review_status=ReviewStatus.REJECTED, lock_version=1,
        )
    )
    session.add(
        AssetSearchDocument(
            asset_id=asset.id, media_kind="image", effective_source=None,
            search_document="", normalized_document="",
            search_document_hash="h2", document_template_version=1,
            document_status=SearchDocumentStatus.EXCLUDED,
            embedding_status=SearchEmbeddingStatus.PENDING,
            is_searchable=False, retry_count=0,
        )
    )
    await session.commit()

    body = (await client.get(f"/api/assets/{asset.id}/trace")).json()
    assert _stage(body, "review")["status"] == "excluded"
    assert _stage(body, "document")["status"] == "excluded"
    assert all(s["status"] != "failed" for s in body["stages"])


async def test_trace_video_missing_docs_and_failed_ai(client, session):
    """视频：ready 镜头一个 AI failed → ai 环节 failed；缺文档 → document lagging。"""
    asset = await _seed_asset(session, media_kind="video")
    session.add(
        MediaProcessingRun(
            asset_id=asset.id, run_uuid=uuid.uuid4().hex,
            status=MediaRunStatus.COMPLETED, generation=1,
            started_at=utcnow(), finished_at=utcnow(),
        )
    )
    await session.flush()
    s1 = Shot(
        asset_id=asset.id, generation=1, sequence_no=1, start_time=0.0,
        end_time=5.0, duration=5.0, detector_type="fixed", status=ShotStatus.READY,
        keyframe_path="k.webp", thumbnail_path="t.webp", proxy_path="p.mp4",
    )
    s2 = Shot(
        asset_id=asset.id, generation=1, sequence_no=2, start_time=5.0,
        end_time=9.0, duration=4.0, detector_type="fixed", status=ShotStatus.READY,
        keyframe_path="k.webp", thumbnail_path="t.webp", proxy_path="p.mp4",
    )
    session.add_all([s1, s2])
    await session.flush()
    session.add(
        AIShotAnalysis(
            shot_id=s1.id, asset_id=asset.id, status=AIShotAnalysisStatus.FAILED,
            provider="fake", model="m", input_fingerprint="fp1", schema_version=1,
        )
    )
    await session.commit()

    body = (await client.get(f"/api/assets/{asset.id}/trace")).json()
    assert _stage(body, "derive")["status"] == "ok"
    ai = _stage(body, "ai")
    assert ai["status"] == "failed"
    assert ai["detail"]["missing"] == 1
    doc = _stage(body, "document")
    assert doc["status"] == "lagging"
    assert doc["detail"]["missing"] == 2


async def test_pipeline_health_counters(client, session):
    """播种滞后数据后计数非零；Redis 由测试环境决定，键必须齐全。"""
    # 无镜头的视频 + 无 AI 的图片（两项滞后）
    await _seed_asset(session, media_kind="video")
    await _seed_asset(session, media_kind="image")

    resp = await client.get("/api/system/pipeline-health")
    assert resp.status_code == 200
    body = resp.json()
    counters = body["counters"]
    for key in (
        "assets_no_shots", "shots_ai_missing", "ai_failed", "img_ai_missing",
        "runs_stuck_running", "shot_docs_missing", "shot_docs_degraded",
        "asset_docs_missing", "visual_emb_failed",
    ):
        assert key in counters, key
    assert counters["assets_no_shots"] >= 1
    assert counters["img_ai_missing"] >= 1
    assert counters["asset_docs_missing"] >= 2
    # 队列键齐全；值为 int（Redis 可达）或 None（不可达降级，不允许 500）
    assert set(body["queues"]) == {"default", "scan", "media", "ai", "search", "export"}
    for v in body["queues"].values():
        assert v is None or isinstance(v, int)
