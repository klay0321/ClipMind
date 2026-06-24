"""AI 分析调度：以数据库为事实来源创建运行行并入队 ai 队列。

与 shot_dispatch 一致：建行 + flush（部分唯一索引兜底并发）→ commit → 入队 → 回写
celery_task_id；入队失败标 FAILED 并向上抛。
"""

from __future__ import annotations

import uuid

from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import AIAnalysisRun, AIShotAnalysis, Asset
from clipmind_shared.models.enums import (
    ACTIVE_AI_RUN_STATUSES,
    AIRunStatus,
    AIShotAnalysisStatus,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks_client import enqueue_analyze_asset_ai, enqueue_analyze_shot_ai


async def get_active_ai_run(db: AsyncSession, asset_id: int) -> AIAnalysisRun | None:
    stmt = (
        select(AIAnalysisRun)
        .where(
            AIAnalysisRun.asset_id == asset_id,
            AIAnalysisRun.status.in_(list(ACTIVE_AI_RUN_STATUSES)),
        )
        .order_by(AIAnalysisRun.id.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def get_latest_ai_run(db: AsyncSession, asset_id: int) -> AIAnalysisRun | None:
    stmt = (
        select(AIAnalysisRun)
        .where(AIAnalysisRun.asset_id == asset_id)
        .order_by(AIAnalysisRun.id.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def count_completed_analyses(db: AsyncSession, asset_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(AIShotAnalysis)
        .where(
            AIShotAnalysis.asset_id == asset_id,
            AIShotAnalysis.status == AIShotAnalysisStatus.COMPLETED,
        )
    )
    return int((await db.execute(stmt)).scalar() or 0)


async def get_shot_analysis(db: AsyncSession, shot_id: int) -> AIShotAnalysis | None:
    stmt = select(AIShotAnalysis).where(AIShotAnalysis.shot_id == shot_id)
    return (await db.execute(stmt)).scalars().first()


async def latest_ai_run_status_for_assets(
    db: AsyncSession, asset_ids: list[int]
) -> dict[int, str]:
    """各素材最近一次 AI 运行的状态（用于列表展示，单查询批量）。"""
    if not asset_ids:
        return {}
    stmt = (
        select(AIAnalysisRun.asset_id, AIAnalysisRun.status)
        .where(AIAnalysisRun.asset_id.in_(asset_ids))
        .distinct(AIAnalysisRun.asset_id)
        .order_by(AIAnalysisRun.asset_id, AIAnalysisRun.id.desc())
    )
    rows = (await db.execute(stmt)).all()
    return {aid: status.value for aid, status in rows}


async def completed_counts_for_assets(
    db: AsyncSession, asset_ids: list[int]
) -> dict[int, int]:
    """各素材已有 completed AI 结果的镜头数（单查询批量）。"""
    if not asset_ids:
        return {}
    stmt = (
        select(AIShotAnalysis.asset_id, func.count())
        .where(
            AIShotAnalysis.asset_id.in_(asset_ids),
            AIShotAnalysis.status == AIShotAnalysisStatus.COMPLETED,
        )
        .group_by(AIShotAnalysis.asset_id)
    )
    return {aid: int(c) for aid, c in (await db.execute(stmt)).all()}


async def request_ai_analysis(
    db: AsyncSession, asset: Asset, *, only_shot_id: int | None = None
) -> AIAnalysisRun:
    """发起/重试 AI 分析：已有活动运行则幂等返回，否则建运行并入队。"""
    existing = await get_active_ai_run(db, asset.id)
    if existing is not None:
        return existing

    run = AIAnalysisRun(
        run_uuid=uuid.uuid4().hex,
        asset_id=asset.id,
        status=AIRunStatus.QUEUED,
        queued_at=utcnow(),
    )
    db.add(run)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await get_active_ai_run(db, asset.id)
        if existing is not None:
            return existing
        raise

    await db.commit()
    await db.refresh(run)

    try:
        if only_shot_id is not None:
            task_id = enqueue_analyze_shot_ai(run.id, only_shot_id)
        else:
            task_id = enqueue_analyze_asset_ai(run.id)
    except Exception as exc:  # noqa: BLE001
        run.status = AIRunStatus.FAILED
        run.error_message = f"入队失败: {exc}"[:ERROR_MESSAGE_MAX_LEN]
        run.finished_at = utcnow()
        await db.commit()
        raise

    run.celery_task_id = task_id
    await db.commit()
    await db.refresh(run)
    return run
