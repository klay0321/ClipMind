"""自动分析衔接（AAP）：扫描 → 拆镜头 → AI 打标的跨队列自动入队。

同步 Session 版，复刻 API 侧 dispatch 的幂等模式（活动 run 幂等返回 +
部分唯一索引 IntegrityError 兜底）。所有入口 best-effort：失败只记日志，
绝不影响宿主任务（与 ai/tasks._enqueue_search_rebuild 同一原则）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from clipmind_shared.constants import (
    ERROR_MESSAGE_MAX_LEN,
    QUEUE_AI,
    QUEUE_MEDIA,
    TASK_ANALYZE_ASSET_AI,
    TASK_ANALYZE_SHOTS,
)
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    ACTIVE_AI_RUN_STATUSES,
    ACTIVE_MEDIA_RUN_STATUSES,
    AIAnalysisRun,
    AICallLog,
    MediaProcessingRun,
)
from clipmind_shared.models.enums import AIRunStatus, MediaRunStatus
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from clipmind_worker.celery_app import celery_app

logger = logging.getLogger(__name__)


def _has_active_media_run(session: Session, asset_id: int) -> bool:
    stmt = select(MediaProcessingRun.id).where(
        MediaProcessingRun.asset_id == asset_id,
        MediaProcessingRun.status.in_(list(ACTIVE_MEDIA_RUN_STATUSES)),
    )
    return session.execute(stmt.limit(1)).first() is not None


def _has_active_ai_run(session: Session, asset_id: int) -> bool:
    stmt = select(AIAnalysisRun.id).where(
        AIAnalysisRun.asset_id == asset_id,
        AIAnalysisRun.status.in_(list(ACTIVE_AI_RUN_STATUSES)),
    )
    return session.execute(stmt.limit(1)).first() is not None


def auto_request_shot_analysis(session: Session, asset_id: int) -> bool:
    """为素材自动入队拆镜头。返回是否新入队（已有活动 run / 冲突 → False）。"""
    if _has_active_media_run(session, asset_id):
        return False
    run = MediaProcessingRun(
        run_uuid=uuid.uuid4().hex,
        asset_id=asset_id,
        status=MediaRunStatus.QUEUED,
        queued_at=utcnow(),
    )
    session.add(run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return False
    try:
        result = celery_app.send_task(TASK_ANALYZE_SHOTS, args=[run.id], queue=QUEUE_MEDIA)
        run.celery_task_id = result.id
        session.commit()
    except Exception as exc:  # noqa: BLE001 - 入队失败标 FAILED，下次扫描兜底重试
        session.rollback()
        run = session.get(MediaProcessingRun, run.id)
        if run is not None:
            run.status = MediaRunStatus.FAILED
            run.error_message = f"自动入队失败: {exc}"[:ERROR_MESSAGE_MAX_LEN]
            run.finished_at = utcnow()
            session.commit()
        logger.warning("自动拆镜头入队失败 asset=%s: %s", asset_id, exc)
        return False
    return True


def auto_request_ai(session: Session, asset_id: int) -> bool:
    """为素材自动入队 AI 打标。返回是否新入队。"""
    if _has_active_ai_run(session, asset_id):
        return False
    run = AIAnalysisRun(
        run_uuid=uuid.uuid4().hex,
        asset_id=asset_id,
        status=AIRunStatus.QUEUED,
        queued_at=utcnow(),
    )
    session.add(run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return False
    try:
        result = celery_app.send_task(TASK_ANALYZE_ASSET_AI, args=[run.id], queue=QUEUE_AI)
        run.celery_task_id = result.id
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        run = session.get(AIAnalysisRun, run.id)
        if run is not None:
            run.status = AIRunStatus.FAILED
            run.error_message = f"自动入队失败: {exc}"[:ERROR_MESSAGE_MAX_LEN]
            run.finished_at = utcnow()
            session.commit()
        logger.warning("自动 AI 打标入队失败 asset=%s: %s", asset_id, exc)
        return False
    return True


def ai_spent_today(session: Session) -> float:
    """今日（UTC 日）AI 已花费（ai_call_log.est_cost 口径，None 记 0）。"""
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = session.execute(
        select(func.coalesce(func.sum(AICallLog.est_cost), 0.0)).where(
            AICallLog.created_at >= day_start
        )
    ).scalar_one()
    return float(total or 0.0)


def ai_budget_exceeded(session: Session, daily_budget: float) -> bool:
    """日预算护栏：仅约束自动路径；daily_budget<=0 表示不限。"""
    if daily_budget <= 0:
        return False
    return ai_spent_today(session) >= daily_budget
