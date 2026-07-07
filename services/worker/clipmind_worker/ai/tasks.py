"""PR-03A AI 分析 Celery 任务（ai 队列）。

与镜头分析任务一致的可靠性约定：
- 互斥：素材级 advisory lock（命名空间 0x4149 "AI"，与扫描 0x4C4D / media 0x4D44 区分）
  + ai_analysis_run 部分唯一索引；
- acks_late 断点恢复；失败标 run FAILED 并恢复 asset 状态；
- 真正的编排在 runner.run_asset_analysis（纯逻辑，可单测）。
"""

from __future__ import annotations

import logging
from typing import Any

from clipmind_shared.constants import (
    ERROR_MESSAGE_MAX_LEN,
    QUEUE_SEARCH,
    TASK_ANALYZE_ASSET_AI,
    TASK_ANALYZE_SHOT_AI,
    TASK_REBUILD_ASSET_LEVEL_DOC,
    TASK_REBUILD_ASSET_SEARCH_DOCS,
    TASK_REBUILD_SHOT_SEARCH_DOC,
)
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import AIAnalysisRun, Asset, Shot
from clipmind_shared.models.enums import AIRunStatus, AssetStatus, ShotStatus
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clipmind_worker.ai.runner import run_asset_analysis, run_image_analysis
from clipmind_worker.celery_app import celery_app
from clipmind_worker.config import get_settings
from clipmind_worker.db import SessionLocal, engine

logger = logging.getLogger(__name__)

ADVISORY_LOCK_NAMESPACE = 0x4149  # "AI"


def _enqueue_search_rebuild(*, asset_id: int | None = None, shot_id: int | None = None) -> None:
    """AI 分析提交后入队检索文档重建。入队失败不影响 AI 任务（sweeper/backfill 兜底）。"""
    try:
        if shot_id is not None:
            celery_app.send_task(TASK_REBUILD_SHOT_SEARCH_DOC, args=[shot_id], queue=QUEUE_SEARCH)
        elif asset_id is not None:
            celery_app.send_task(
                TASK_REBUILD_ASSET_SEARCH_DOCS, args=[asset_id], queue=QUEUE_SEARCH
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("入队检索文档重建失败（将由 sweeper/backfill 兜底）: %s", exc)


def _enqueue_asset_level_doc(asset_id: int) -> None:
    """P2a：素材级检索文档重建（图片分析完成 / 视频镜头文档变化后）。best-effort。"""
    try:
        celery_app.send_task(TASK_REBUILD_ASSET_LEVEL_DOC, args=[asset_id], queue=QUEUE_SEARCH)
    except Exception as exc:  # noqa: BLE001
        logger.warning("入队素材级检索文档重建失败（sweeper 兜底）: %s", exc)


def _truncate(text: str) -> str:
    return text[:ERROR_MESSAGE_MAX_LEN]


def _fail_run(run_id: int, asset_id: int, exc: Exception) -> None:
    with SessionLocal() as session:
        run = session.get(AIAnalysisRun, run_id)
        if run is not None:
            run.status = AIRunStatus.FAILED
            run.error_message = _truncate(str(exc))
            run.finished_at = utcnow()
        asset = session.get(Asset, asset_id)
        if asset is not None:
            has_ready = session.execute(
                select(func.count())
                .select_from(Shot)
                .where(Shot.asset_id == asset_id, Shot.status == ShotStatus.READY)
            ).scalar()
            asset.status = AssetStatus.SHOT_SPLIT if has_ready else AssetStatus.INDEXED
        session.commit()


def _run(run_id: int, *, only_shot_id: int | None, worker_name: str) -> dict[str, Any]:
    settings = get_settings()
    with engine.connect() as conn:
        session = Session(bind=conn)
        try:
            run = session.get(AIAnalysisRun, run_id)
            if run is None:
                return {"error": "ai_run_not_found", "run_id": run_id}
            if run.status != AIRunStatus.QUEUED:
                return {"skipped": True, "reason": f"status={run.status.value}"}
            asset = session.get(Asset, run.asset_id)
            if asset is None:
                run.status = AIRunStatus.FAILED
                run.error_message = "asset_not_found"
                run.finished_at = utcnow()
                session.commit()
                return {"error": "asset_not_found"}

            asset_id = asset.id
            run.worker_name = worker_name
            # 不在取锁前 commit：保持 session 持续持有连接事务，使取锁(exec_driver_sql)
            # 加入同一事务、后续 run_asset_analysis 内的 session.commit() 为真实提交。
            # 若此处 commit，会关闭 session 事务，advisory lock 另起连接级事务，session 改以
            # savepoint 加入，导致取锁后所有 commit 仅释放 savepoint、最终随连接关闭被整体回滚
            # （worker_name 已落库但 status/结果丢失）。对齐 media analyze_shots 的写法。
            locked = conn.exec_driver_sql(
                "SELECT pg_try_advisory_lock(%s, %s)",
                (ADVISORY_LOCK_NAMESPACE, asset_id),
            ).scalar()
            if not locked:
                return {"skipped": True, "reason": "locked"}

            try:
                # P2a：图片素材走图片理解链路（无镜头概念）
                if asset.media_kind == "image":
                    return run_image_analysis(session, run, asset, settings)
                return run_asset_analysis(
                    session, run, asset, settings, only_shot_id=only_shot_id
                )
            except Exception as exc:  # noqa: BLE001 - 记录失败并向上抛交给 Celery
                session.rollback()
                _fail_run(run_id, asset_id, exc)
                raise
            finally:
                conn.exec_driver_sql(
                    "SELECT pg_advisory_unlock(%s, %s)",
                    (ADVISORY_LOCK_NAMESPACE, asset_id),
                )
        finally:
            session.close()


@celery_app.task(name=TASK_ANALYZE_ASSET_AI, bind=True, acks_late=True)
def analyze_asset_ai(self, run_id: int) -> dict[str, Any]:  # noqa: ANN001
    result = _run(run_id, only_shot_id=None, worker_name=self.request.hostname or "")
    # 运行已落库（run_asset_analysis 内 commit）后再入队检索文档重建
    if result.get("asset_id") is not None:
        if result.get("media_kind") == "image":
            # 图片：直接重建素材级文档（无镜头文档）
            _enqueue_asset_level_doc(result["asset_id"])
        else:
            _enqueue_search_rebuild(asset_id=result["asset_id"])
    return result


@celery_app.task(name=TASK_ANALYZE_SHOT_AI, bind=True, acks_late=True)
def analyze_shot_ai(self, run_id: int, shot_id: int) -> dict[str, Any]:  # noqa: ANN001
    result = _run(run_id, only_shot_id=shot_id, worker_name=self.request.hostname or "")
    if result.get("asset_id") is not None:
        _enqueue_search_rebuild(shot_id=shot_id)
    return result
