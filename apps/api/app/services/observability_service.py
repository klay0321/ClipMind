"""OBS：单素材链路诊断（trace）与全局管线健康（pipeline health）。

纯只读投影：不写任何表、不触发任何任务。目标是把"某个素材为什么搜不到"
从跨 6 个环节的人肉排查，压缩成一次 API 调用；把"全库当前卡在哪"
压缩成一张计数表。

口径与各域服务保持一致（image effective 语义复用 image_review_service；
可搜性以 search document 的 is_searchable 为准）。
"""

from __future__ import annotations

import contextlib
from datetime import timedelta
from typing import Any

import redis.asyncio as aioredis
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIAnalysisRun,
    AIShotAnalysis,
    Asset,
    AssetImageAnalysis,
    AssetImageReviewState,
    AssetSearchDocument,
    MediaProcessingRun,
    ScanRun,
    Shot,
    ShotReviewState,
    ShotSearchDocument,
    VisualMediaEmbedding,
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
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.observability import (
    AssetTraceOut,
    PipelineHealthOut,
    TraceStageOut,
)
from app.services.image_review_service import compute_effective as image_effective

# 卡住判定：运行态超过该时长仍未结束
STUCK_RUN_AFTER = timedelta(hours=2)

# Celery Redis broker 的队列即同名 list；llen 即积压深度
PIPELINE_QUEUES = ("default", "scan", "media", "ai", "search", "export")


def _stage(
    stage: str, title: str, status: str, detail: dict[str, Any], hint: str
) -> TraceStageOut:
    return TraceStageOut(stage=stage, title=title, status=status, detail=detail, hint=hint)


async def _scan_stage(db: AsyncSession, asset: Asset) -> TraceStageOut:
    last_scan = (
        await db.execute(select(ScanRun).order_by(ScanRun.id.desc()).limit(1))
    ).scalar_one_or_none()
    detail: dict[str, Any] = {
        "asset_status": asset.status.value,
        "first_seen_at": asset.first_seen_at.isoformat() if asset.first_seen_at else None,
        "last_seen_at": asset.last_seen_at.isoformat() if asset.last_seen_at else None,
        "last_scan_status": last_scan.status.value if last_scan else None,
    }
    if asset.status == AssetStatus.ERROR:
        return _stage(
            "scan", "扫描与索引", "failed", detail,
            "FFprobe 探测失败——检查文件是否损坏或格式不受支持",
        )
    if asset.status == AssetStatus.SOURCE_MISSING:
        return _stage(
            "scan", "扫描与索引", "failed", detail,
            "源文件缺失——文件可能被移动或删除，等下次扫描 reconcile 或检查 NAS 路径",
        )
    if asset.status == AssetStatus.DISCOVERED:
        return _stage(
            "scan", "扫描与索引", "pending", detail,
            "已发现待探测——等待扫描任务完成 FFprobe",
        )
    return _stage("scan", "扫描与索引", "ok", detail, "已入库索引")


async def _derive_stage(db: AsyncSession, asset: Asset) -> TraceStageOut:
    if asset.media_kind == "image":
        detail = {"poster": bool(asset.poster_path)}
        if asset.poster_path:
            return _stage("derive", "派生文件", "ok", detail, "海报（统一格式视觉输入）已生成")
        return _stage(
            "derive", "派生文件", "lagging", detail,
            "海报未生成——AI 视觉输入依赖它，等待 media 队列处理",
        )

    last_run = (
        await db.execute(
            select(MediaProcessingRun)
            .where(MediaProcessingRun.asset_id == asset.id)
            .order_by(MediaProcessingRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    ready_shots = (
        await db.execute(
            select(func.count())
            .select_from(Shot)
            .where(Shot.asset_id == asset.id, Shot.status == ShotStatus.READY)
        )
    ).scalar_one()
    detail = {
        "last_run_status": last_run.status.value if last_run else None,
        "last_run_error": last_run.error_message if last_run else None,
        "generation": last_run.generation if last_run else None,
        "ready_shots": ready_shots,
    }
    if last_run is None:
        return _stage(
            "derive", "拆镜头与派生", "lagging", detail,
            "从未运行拆镜头——到素材详情或处理中心发起分析",
        )
    if last_run.status == MediaRunStatus.FAILED:
        return _stage(
            "derive", "拆镜头与派生", "failed", detail,
            "拆镜头失败——看 error 详情，修复后重新分析",
        )
    if last_run.status in (MediaRunStatus.QUEUED, MediaRunStatus.RUNNING):
        started = last_run.started_at
        if started and (utcnow() - started) > STUCK_RUN_AFTER:
            return _stage(
                "derive", "拆镜头与派生", "failed", detail,
                "运行超 2 小时未结束——media-worker 可能异常，检查容器日志",
            )
        return _stage("derive", "拆镜头与派生", "pending", detail, "拆镜头进行中——等待 media 队列")
    if ready_shots == 0:
        return _stage(
            "derive", "拆镜头与派生", "lagging", detail,
            "运行完成但无就绪镜头——检查该次 run 的镜头明细",
        )
    return _stage("derive", "拆镜头与派生", "ok", detail, f"{ready_shots} 个镜头就绪")


async def _ai_stage(db: AsyncSession, asset: Asset) -> TraceStageOut:
    if asset.media_kind == "image":
        ai = (
            await db.execute(
                select(AssetImageAnalysis).where(AssetImageAnalysis.asset_id == asset.id)
            )
        ).scalar_one_or_none()
        detail = {
            "status": ai.status.value if ai else None,
            "degraded_reason": ai.degraded_reason if ai else None,
        }
        if ai is None:
            return _stage(
                "ai", "AI 理解", "lagging", detail,
                "图片尚无 AI 理解——自动链未触发或 ai 队列积压；可在素材详情手动发起",
            )
        if ai.status == AIShotAnalysisStatus.FAILED:
            return _stage("ai", "AI 理解", "failed", detail, "图片 AI 理解失败——可重新发起")
        if ai.status == AIShotAnalysisStatus.PENDING:
            return _stage("ai", "AI 理解", "pending", detail, "AI 理解进行中")
        return _stage("ai", "AI 理解", "ok", detail, "AI 理解完成")

    rows = (
        await db.execute(
            select(AIShotAnalysis.status, func.count())
            .join(Shot, Shot.id == AIShotAnalysis.shot_id)
            .where(Shot.asset_id == asset.id, Shot.status == ShotStatus.READY)
            .group_by(AIShotAnalysis.status)
        )
    ).all()
    by_status = {s.value: c for s, c in rows}
    ready_shots = (
        await db.execute(
            select(func.count())
            .select_from(Shot)
            .where(Shot.asset_id == asset.id, Shot.status == ShotStatus.READY)
        )
    ).scalar_one()
    analyzed = sum(by_status.values())
    missing = max(0, ready_shots - analyzed)
    last_run = (
        await db.execute(
            select(AIAnalysisRun)
            .where(AIAnalysisRun.asset_id == asset.id)
            .order_by(AIAnalysisRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    detail = {
        "ready_shots": ready_shots,
        "by_status": by_status,
        "missing": missing,
        "last_run_status": last_run.status.value if last_run else None,
        "last_run_error": last_run.error_message if last_run else None,
    }
    if ready_shots == 0:
        return _stage("ai", "AI 理解", "not_applicable", detail, "没有就绪镜头，先完成拆镜头")
    if by_status.get("failed"):
        return _stage(
            "ai", "AI 理解", "failed", detail,
            f"{by_status['failed']} 个镜头 AI 失败——可重新分析",
        )
    if last_run and last_run.status.value in ("queued", "running"):
        return _stage("ai", "AI 理解", "pending", detail, "AI 分析运行中——等待 ai 队列")
    if missing:
        return _stage(
            "ai", "AI 理解", "lagging", detail,
            f"{missing} 个镜头未打标——自动链未触发或需手动发起 AI 分析",
        )
    return _stage("ai", "AI 理解", "ok", detail, f"{analyzed} 个镜头已打标")


async def _review_stage(db: AsyncSession, asset: Asset) -> TraceStageOut:
    if asset.media_kind == "image":
        ai = (
            await db.execute(
                select(AssetImageAnalysis).where(AssetImageAnalysis.asset_id == asset.id)
            )
        ).scalar_one_or_none()
        review = (
            await db.execute(
                select(AssetImageReviewState).where(AssetImageReviewState.asset_id == asset.id)
            )
        ).scalar_one_or_none()
        source, _ = image_effective(ai, review)
        detail = {
            "review_status": review.review_status.value if review else "unreviewed",
            "effective_source": source,
        }
        if source == "rejected":
            return _stage(
                "review", "人工审核", "excluded", detail,
                "已驳回/无法判断——按规则不进搜索（这是决定，不是故障）",
            )
        if source == "none":
            return _stage(
                "review", "人工审核", "not_applicable", detail,
                "尚无可审核的结果（先完成 AI 理解）",
            )
        hint = "人工结果生效" if source == "human" else "AI 结果临时生效（未审核也可搜）"
        return _stage("review", "人工审核", "ok", detail, hint)

    rows = (
        await db.execute(
            select(ShotReviewState.review_status, func.count())
            .join(Shot, Shot.id == ShotReviewState.shot_id)
            .where(Shot.asset_id == asset.id, ShotReviewState.shot_generation == Shot.generation)
            .group_by(ShotReviewState.review_status)
        )
    ).all()
    by_status = {s.value: c for s, c in rows}
    ready_shots = (
        await db.execute(
            select(func.count())
            .select_from(Shot)
            .where(Shot.asset_id == asset.id, Shot.status == ShotStatus.READY)
        )
    ).scalar_one()
    excluded = by_status.get(ReviewStatus.REJECTED.value, 0) + by_status.get(
        ReviewStatus.UNABLE.value, 0
    )
    detail = {"ready_shots": ready_shots, "by_status": by_status, "excluded": excluded}
    if ready_shots and excluded >= ready_shots:
        return _stage(
            "review", "人工审核", "excluded", detail,
            "全部镜头已驳回/无法判断——按规则不进搜索（这是决定，不是故障）",
        )
    hint = "未审核/待审核的镜头以 AI 结果临时生效；已确认/修改的以人工为准"
    return _stage("review", "人工审核", "ok", detail, hint)


async def _document_stage(db: AsyncSession, asset: Asset) -> TraceStageOut:
    asset_doc = (
        await db.execute(
            select(AssetSearchDocument).where(AssetSearchDocument.asset_id == asset.id)
        )
    ).scalar_one_or_none()
    detail: dict[str, Any] = {
        "asset_doc_status": asset_doc.document_status.value if asset_doc else None,
        "asset_doc_searchable": asset_doc.is_searchable if asset_doc else None,
    }
    if asset.media_kind == "image":
        if asset_doc is None:
            return _stage(
                "document", "检索文档", "lagging", detail,
                "素材检索文档未建——等待 search 队列索引或先完成 AI 理解",
            )
        if asset_doc.document_status == SearchDocumentStatus.EXCLUDED:
            return _stage(
                "document", "检索文档", "excluded", detail,
                "文档 excluded——驳回/无有效结果时按规则排除，不进搜索",
            )
        if not asset_doc.is_searchable:
            return _stage(
                "document", "检索文档", "lagging", detail,
                "文档存在但不可搜——等待索引完成",
            )
        return _stage("document", "检索文档", "ok", detail, "图片可被搜索")

    rows = (
        await db.execute(
            select(
                ShotSearchDocument.document_status,
                ShotSearchDocument.is_searchable,
                func.count(),
            )
            .join(
                Shot,
                (Shot.id == ShotSearchDocument.shot_id)
                & (Shot.generation == ShotSearchDocument.shot_generation),
            )
            .where(Shot.asset_id == asset.id, Shot.status == ShotStatus.READY)
            .group_by(ShotSearchDocument.document_status, ShotSearchDocument.is_searchable)
        )
    ).all()
    searchable = sum(c for st, ok, c in rows if ok)
    excluded = sum(c for st, ok, c in rows if st == SearchDocumentStatus.EXCLUDED)
    have_docs = sum(c for _, _, c in rows)
    ready_shots = (
        await db.execute(
            select(func.count())
            .select_from(Shot)
            .where(Shot.asset_id == asset.id, Shot.status == ShotStatus.READY)
        )
    ).scalar_one()
    missing = max(0, ready_shots - have_docs)
    detail.update(
        {
            "ready_shots": ready_shots,
            "shot_docs": have_docs,
            "searchable": searchable,
            "excluded": excluded,
            "missing": missing,
        }
    )
    if ready_shots == 0:
        return _stage("document", "检索文档", "not_applicable", detail, "没有就绪镜头")
    if missing:
        return _stage(
            "document", "检索文档", "lagging", detail,
            f"{missing} 个镜头缺检索文档——等待 search 队列或触发重建",
        )
    if searchable == 0 and excluded:
        return _stage(
            "document", "检索文档", "excluded", detail,
            "全部镜头文档 excluded（驳回/无有效结果）——按规则不进搜索",
        )
    if searchable == 0:
        return _stage("document", "检索文档", "lagging", detail, "有文档但均不可搜——等待索引完成")
    return _stage("document", "检索文档", "ok", detail, f"{searchable} 个镜头可搜")


async def _embedding_stage(db: AsyncSession, asset: Asset) -> TraceStageOut:
    if asset.media_kind == "image":
        text_row = (
            await db.execute(
                select(AssetSearchDocument.embedding_status).where(
                    AssetSearchDocument.asset_id == asset.id
                )
            )
        ).scalar_one_or_none()
        text_detail: dict[str, Any] = {"text_embedding": text_row.value if text_row else None}
        shot_scope = None
    else:
        rows = (
            await db.execute(
                select(ShotSearchDocument.embedding_status, func.count())
                .join(
                    Shot,
                    (Shot.id == ShotSearchDocument.shot_id)
                    & (Shot.generation == ShotSearchDocument.shot_generation),
                )
                .where(Shot.asset_id == asset.id, Shot.status == ShotStatus.READY)
                .group_by(ShotSearchDocument.embedding_status)
            )
        ).all()
        shot_scope = {s.value: c for s, c in rows}
        text_detail = {"shot_text_embeddings": shot_scope}

    vis_rows = (
        await db.execute(
            select(VisualMediaEmbedding.status, func.count())
            .where(
                VisualMediaEmbedding.target_type == "asset",
                VisualMediaEmbedding.target_id == asset.id,
            )
            .group_by(VisualMediaEmbedding.status)
        )
    ).all()
    vis = {s: c for s, c in vis_rows}
    detail = {**text_detail, "visual_asset_embedding": vis}

    if vis.get("failed"):
        return _stage(
            "embedding", "向量", "failed", detail,
            "视觉向量计算失败——看 search-worker 日志后可重算",
        )
    degraded = (shot_scope or {}).get(SearchEmbeddingStatus.DEGRADED.value, 0)
    if degraded:
        return _stage(
            "embedding", "向量", "lagging", detail,
            f"{degraded} 个镜头文本向量降级——仅词法可搜，语义召回受损",
        )
    if asset.media_kind == "image" and not vis:
        return _stage(
            "embedding", "向量", "lagging", detail,
            "视觉向量未计算——以图搜图/视觉候选不覆盖该图，等待 search 队列",
        )
    return _stage("embedding", "向量", "ok", detail, "向量就绪")


async def asset_trace(db: AsyncSession, asset: Asset) -> AssetTraceOut:
    stages = [
        await _scan_stage(db, asset),
        await _derive_stage(db, asset),
        await _ai_stage(db, asset),
        await _review_stage(db, asset),
        await _document_stage(db, asset),
        await _embedding_stage(db, asset),
    ]
    return AssetTraceOut(
        asset_id=asset.id,
        media_kind=asset.media_kind,
        filename=asset.filename,
        stages=stages,
        generated_at=utcnow(),
    )


# 单次往返拿全部计数；键名与 PipelineHealthOut 文档一致
_HEALTH_SQL = text(
    """
SELECT 'assets_no_shots' AS k, count(*) AS v FROM asset a
  WHERE a.media_kind='video' AND a.status='indexed'
    AND NOT EXISTS (SELECT 1 FROM shot s WHERE s.asset_id=a.id)
UNION ALL SELECT 'shots_ai_missing', count(*) FROM shot s
  WHERE s.status='ready'
    AND NOT EXISTS (SELECT 1 FROM ai_shot_analysis x WHERE x.shot_id=s.id)
UNION ALL SELECT 'ai_failed', count(*) FROM ai_shot_analysis WHERE status='failed'
UNION ALL SELECT 'img_ai_missing', count(*) FROM asset a
  WHERE a.media_kind='image' AND a.status='indexed'
    AND NOT EXISTS (SELECT 1 FROM asset_image_analysis x WHERE x.asset_id=a.id)
UNION ALL SELECT 'runs_stuck_running', count(*) FROM ai_analysis_run
  WHERE status='running' AND started_at < now() - interval '2 hours'
UNION ALL SELECT 'shot_docs_missing', count(*) FROM shot s
  WHERE s.status='ready'
    AND NOT EXISTS (SELECT 1 FROM shot_search_document d WHERE d.shot_id=s.id)
UNION ALL SELECT 'shot_docs_degraded', count(*) FROM shot_search_document
  WHERE embedding_status='degraded'
UNION ALL SELECT 'asset_docs_missing', count(*) FROM asset a
  WHERE a.status='indexed'
    AND NOT EXISTS (SELECT 1 FROM asset_search_document d WHERE d.asset_id=a.id)
UNION ALL SELECT 'visual_emb_failed', count(*) FROM visual_media_embedding
  WHERE status='failed'
"""
)


async def _queue_depths(redis_url: str) -> dict[str, int | None]:
    """Celery Redis broker 队列积压；连不上时全部 None（不阻塞健康响应）。"""
    client = aioredis.from_url(redis_url)
    try:
        out: dict[str, int | None] = {}
        for q in PIPELINE_QUEUES:
            out[q] = int(await client.llen(q))
        return out
    except Exception:  # noqa: BLE001 - 观测端点自身不因 Redis 故障 500
        return {q: None for q in PIPELINE_QUEUES}
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


async def pipeline_health(db: AsyncSession, redis_url: str) -> PipelineHealthOut:
    rows = (await db.execute(_HEALTH_SQL)).all()
    counters = {k: int(v) for k, v in rows}
    queues = await _queue_depths(redis_url)
    return PipelineHealthOut(
        counters=counters, queues=queues, generated_at=utcnow()
    )
