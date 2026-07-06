"""AAP：批量分析编排 + 全局处理概览（零迁移，全部走已有表）。

批量分析 = 循环调用既有幂等 dispatch（request_analysis / request_ai_analysis），
不建 job 表；进度用 /processing/overview 表达。绝不隐式全库：调用方必须给
asset_ids 或 source_directory_id。
"""

from __future__ import annotations

from datetime import UTC, datetime

from clipmind_shared.models import (
    AIAnalysisRun,
    AICallLog,
    AIShotAnalysis,
    Asset,
    MediaProcessingRun,
    ScanRun,
    Shot,
    ShotSearchDocument,
)
from clipmind_shared.models.enums import (
    AIRunStatus,
    AssetStatus,
    MediaRunStatus,
    ScanRunStatus,
    ShotStatus,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.schemas.processing import (
    BatchAnalyzeIn,
    BatchAnalyzeOut,
    ProcessingConfigOut,
    ProcessingOverviewOut,
    ProcessingTotals,
    QueueCounts,
)
from app.services import ai_dispatch, shot_dispatch


def _ready_shot_exists():
    return (
        select(Shot.id)
        .where(
            Shot.asset_id == Asset.id,
            Shot.status == ShotStatus.READY,
            Shot.retired_at.is_(None),
        )
        .exists()
    )


def _unlabeled_ready_shot_exists():
    analyzed = select(AIShotAnalysis.id).where(AIShotAnalysis.shot_id == Shot.id).exists()
    return (
        select(Shot.id)
        .where(
            Shot.asset_id == Asset.id,
            Shot.status == ShotStatus.READY,
            Shot.retired_at.is_(None),
            ~analyzed,
        )
        .exists()
    )


async def batch_analyze(db: AsyncSession, payload: BatchAnalyzeIn) -> BatchAnalyzeOut:
    base = select(Asset).where(Asset.media_kind == "video")
    if payload.asset_ids:
        base = base.where(Asset.id.in_(payload.asset_ids))
    if payload.source_directory_id is not None:
        base = base.where(Asset.source_directory_id == payload.source_directory_id)

    # 按 stage 收敛目标：shots=无可用镜头的 INDEXED；ai=存在未打标可用镜头
    stage_filters = []
    if "shots" in payload.stages:
        stage_filters.append(
            (Asset.status == AssetStatus.INDEXED) & ~_ready_shot_exists()
        )
    if "ai" in payload.stages:
        stage_filters.append(_unlabeled_ready_shot_exists())
    if stage_filters:
        cond = stage_filters[0]
        for f in stage_filters[1:]:
            cond = cond | f
        base = base.where(cond)

    rows = (
        (await db.execute(base.order_by(Asset.id).limit(payload.max_items + 1)))
        .scalars()
        .all()
    )
    truncated = len(rows) > payload.max_items
    targets = list(rows[: payload.max_items])

    enqueued_shots = 0
    enqueued_ai = 0
    skipped_active = 0
    skipped_ineligible = 0

    for asset in targets:
        handled = False
        if (
            "shots" in payload.stages
            and asset.status == AssetStatus.INDEXED
        ):
            has_ready = await db.scalar(
                select(func.count(Shot.id)).where(
                    Shot.asset_id == asset.id,
                    Shot.status == ShotStatus.READY,
                    Shot.retired_at.is_(None),
                )
            )
            if not has_ready:
                existing = await shot_dispatch.get_active_media_run(db, asset.id)
                if existing is not None:
                    skipped_active += 1
                else:
                    await shot_dispatch.request_analysis(db, asset)
                    enqueued_shots += 1
                handled = True
        if not handled and "ai" in payload.stages:
            unlabeled = await db.scalar(
                select(func.count(Shot.id)).where(
                    Shot.asset_id == asset.id,
                    Shot.status == ShotStatus.READY,
                    Shot.retired_at.is_(None),
                    ~select(AIShotAnalysis.id)
                    .where(AIShotAnalysis.shot_id == Shot.id)
                    .exists(),
                )
            )
            if unlabeled:
                existing_ai = await ai_dispatch.get_active_ai_run(db, asset.id)
                if existing_ai is not None:
                    skipped_active += 1
                else:
                    await ai_dispatch.request_ai_analysis(db, asset)
                    enqueued_ai += 1
                handled = True
        if not handled:
            skipped_ineligible += 1

    return BatchAnalyzeOut(
        matched=len(targets),
        enqueued_shots=enqueued_shots,
        enqueued_ai=enqueued_ai,
        skipped_active=skipped_active,
        skipped_ineligible=skipped_ineligible,
        truncated=truncated,
    )


async def _queue_counts(db: AsyncSession, model, queued_status, running_status) -> QueueCounts:
    queued = await db.scalar(
        select(func.count()).select_from(model).where(model.status == queued_status)
    )
    running = await db.scalar(
        select(func.count()).select_from(model).where(model.status == running_status)
    )
    return QueueCounts(queued=int(queued or 0), running=int(running or 0))


async def overview(db: AsyncSession) -> ProcessingOverviewOut:
    settings = get_settings()
    scan = await _queue_counts(db, ScanRun, ScanRunStatus.QUEUED, ScanRunStatus.RUNNING)
    shots = await _queue_counts(
        db, MediaProcessingRun, MediaRunStatus.QUEUED, MediaRunStatus.RUNNING
    )
    ai = await _queue_counts(db, AIAnalysisRun, AIRunStatus.QUEUED, AIRunStatus.RUNNING)

    videos_total = await db.scalar(
        select(func.count()).select_from(Asset).where(
            Asset.media_kind == "video",
            Asset.status.in_([AssetStatus.INDEXED, AssetStatus.SHOT_SPLIT]),
        )
    )
    videos_with_shots = await db.scalar(
        select(func.count(func.distinct(Shot.asset_id))).where(
            Shot.status == ShotStatus.READY, Shot.retired_at.is_(None)
        )
    )
    shots_ready = await db.scalar(
        select(func.count()).select_from(Shot).where(
            Shot.status == ShotStatus.READY, Shot.retired_at.is_(None)
        )
    )
    shots_ai_labeled = await db.scalar(
        select(func.count(func.distinct(AIShotAnalysis.shot_id)))
    )
    images_total = await db.scalar(
        select(func.count()).select_from(Asset).where(
            Asset.media_kind == "image",
            Asset.status == AssetStatus.INDEXED,
        )
    )
    searchable_docs = await db.scalar(
        select(func.count()).select_from(ShotSearchDocument).where(
            ShotSearchDocument.is_searchable.is_(True)
        )
    )
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    ai_spent_today = await db.scalar(
        select(func.coalesce(func.sum(AICallLog.est_cost), 0.0)).where(
            AICallLog.created_at >= day_start
        )
    )

    return ProcessingOverviewOut(
        scan=scan,
        shots=shots,
        ai=ai,
        totals=ProcessingTotals(
            videos_total=int(videos_total or 0),
            videos_with_shots=int(videos_with_shots or 0),
            shots_ready=int(shots_ready or 0),
            shots_ai_labeled=int(shots_ai_labeled or 0),
            images_total=int(images_total or 0),
            searchable_docs=int(searchable_docs or 0),
        ),
        config=ProcessingConfigOut(
            auto_analyze_on_scan=settings.auto_analyze_on_scan,
            auto_ai_after_shots=settings.auto_ai_after_shots,
            scan_interval_minutes=settings.scan_interval_minutes,
            ai_daily_budget=settings.ai_daily_budget,
            ai_spent_today=float(ai_spent_today or 0.0),
        ),
    )
