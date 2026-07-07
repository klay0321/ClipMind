"""PR-04 检索文档索引 Celery 任务（search 队列）。

可靠性约定：
- 上游事务提交后才由 API/AI 任务入队（绝不在 flush 后 commit 前发送任务）；
- 索引器幂等：相同内容+同模型跳过重嵌；
- 同一 (shot, generation) 唯一约束下，AI/审核并发触发同镜头重建 → IntegrityError 重试一次
  （第二次 SELECT 命中既有行走更新路径）；
- 瞬时 provider 故障 → Celery 退避重试（有上限）；永久错误记 failed，不无限重试；
- sweeper 兜底扫描漏发/失败的镜头；backfill 脚本可批量修复。
"""

from __future__ import annotations

import logging
from typing import Any

from clipmind_shared.constants import (
    TASK_BACKFILL_SEARCH_DOCS,
    TASK_REBUILD_ASSET_LEVEL_DOC,
    TASK_REBUILD_ASSET_SEARCH_DOCS,
    TASK_REBUILD_SHOT_SEARCH_DOC,
    TASK_SWEEP_SEARCH_DOCS,
)
from clipmind_shared.models import Shot, ShotSearchDocument
from clipmind_shared.models.enums import SearchEmbeddingStatus, ShotStatus
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from clipmind_worker.celery_app import celery_app
from clipmind_worker.config import get_settings
from clipmind_worker.db import SessionLocal
from clipmind_worker.search.asset_indexer import rebuild_asset_level_document
from clipmind_worker.search.indexer import (
    build_embedding_provider,
    ready_shot_ids_for_asset,
    rebuild_shot_document,
    shots_needing_index,
)

_logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


def _backoff(retries: int) -> int:
    return min(2**retries, 60)


def _rebuild_commit(session: Session, shot_id: int, provider, *, force: bool) -> str:  # noqa: ANN001
    """重建并提交单镜头；并发插入冲突时重试一次（改走更新路径）。"""
    try:
        status = rebuild_shot_document(session, shot_id, provider, force_reembed=force)
        session.commit()
        return status
    except IntegrityError:
        session.rollback()
        status = rebuild_shot_document(session, shot_id, provider, force_reembed=force)
        session.commit()
        return status


@celery_app.task(
    name=TASK_REBUILD_SHOT_SEARCH_DOC, bind=True, acks_late=True, max_retries=_MAX_RETRIES
)
def rebuild_shot_search_doc(self, shot_id: int, force_reembed: bool = False) -> dict[str, Any]:  # noqa: ANN001
    provider = build_embedding_provider(get_settings())
    with SessionLocal() as session:
        status = _rebuild_commit(session, shot_id, provider, force=force_reembed)
    if status == "retry":
        raise self.retry(countdown=_backoff(self.request.retries))
    # P2a：镜头文档变化后跟进重建其素材级聚合文档（幂等，内容未变则 skip）
    _enqueue_asset_level(shot_id=shot_id)
    return {"shot_id": shot_id, "status": status}


@celery_app.task(name=TASK_REBUILD_ASSET_SEARCH_DOCS, bind=True, acks_late=True)
def rebuild_asset_search_docs(self, asset_id: int, force_reembed: bool = False) -> dict[str, Any]:  # noqa: ANN001
    provider = build_embedding_provider(get_settings())
    stats: dict[str, int] = {}
    with SessionLocal() as session:
        shot_ids = ready_shot_ids_for_asset(session, asset_id)
        for sid in shot_ids:
            status = _rebuild_commit(session, sid, provider, force=force_reembed)
            stats[status] = stats.get(status, 0) + 1
    # P2a：镜头文档批量重建后跟进素材级聚合文档
    try:
        celery_app.send_task(TASK_REBUILD_ASSET_LEVEL_DOC, args=[asset_id])
    except Exception as exc:  # noqa: BLE001 - sweep 兜底
        _logger.warning("入队素材级聚合失败 asset=%s: %s", asset_id, exc)
    return {"asset_id": asset_id, "total": len(shot_ids), "stats": stats}


@celery_app.task(name=TASK_SWEEP_SEARCH_DOCS, bind=True, acks_late=True)
def sweep_search_docs(self, limit: int = 200, force_reembed: bool = False) -> dict[str, Any]:  # noqa: ANN001
    provider = build_embedding_provider(get_settings())
    current_version = provider.identity().embedding_version
    stats: dict[str, int] = {}
    with SessionLocal() as session:
        shot_ids = shots_needing_index(
            session, current_embedding_version=current_version, limit=limit
        )
        for sid in shot_ids:
            status = _rebuild_commit(session, sid, provider, force=force_reembed)
            stats[status] = stats.get(status, 0) + 1
    return {"swept": len(shot_ids), "stats": stats}


def _backfill_shot_ids(session: Session, *, only_failed: bool, limit: int) -> list[int]:
    """选出需回填的 READY 镜头 id（only_failed → 仅嵌入 failed 的文档）。"""
    if only_failed:
        stmt = (
            select(Shot.id)
            .join(
                ShotSearchDocument,
                and_(
                    ShotSearchDocument.shot_id == Shot.id,
                    ShotSearchDocument.shot_generation == Shot.generation,
                ),
            )
            .where(
                Shot.status == ShotStatus.READY,
                Shot.retired_at.is_(None),
                ShotSearchDocument.embedding_status == SearchEmbeddingStatus.FAILED,
            )
            .order_by(Shot.id)
            .limit(limit)
        )
    else:
        stmt = (
            select(Shot.id)
            .where(Shot.status == ShotStatus.READY, Shot.retired_at.is_(None))
            .order_by(Shot.id)
            .limit(limit)
        )
    return [int(r[0]) for r in session.execute(stmt).all()]


@celery_app.task(name=TASK_BACKFILL_SEARCH_DOCS, bind=True, acks_late=True)
def backfill_search_docs(  # noqa: ANN001
    self, only_failed: bool = False, force_reembed: bool = False, limit: int = 1000
) -> dict[str, Any]:
    """全量/失败回填（有界批次）。超大库请用 scripts/backfill_search_documents.py。"""
    provider = build_embedding_provider(get_settings())
    stats: dict[str, int] = {}
    with SessionLocal() as session:
        shot_ids = _backfill_shot_ids(session, only_failed=only_failed, limit=limit)
        for sid in shot_ids:
            status = _rebuild_commit(session, sid, provider, force=force_reembed)
            stats[status] = stats.get(status, 0) + 1
    return {
        "processed": len(shot_ids),
        "only_failed": only_failed,
        "force_reembed": force_reembed,
        "limit": limit,
        "maybe_more": len(shot_ids) >= limit,
        "stats": stats,
    }


def _enqueue_asset_level(*, shot_id: int) -> None:
    """按镜头反查素材并入队素材级聚合重建（best-effort）。"""
    try:
        with SessionLocal() as session:
            asset_id = session.execute(
                select(Shot.asset_id).where(Shot.id == shot_id)
            ).scalar_one_or_none()
        if asset_id is not None:
            celery_app.send_task(TASK_REBUILD_ASSET_LEVEL_DOC, args=[int(asset_id)])
    except Exception as exc:  # noqa: BLE001 - sweep 兜底
        _logger.warning("入队素材级聚合失败 shot=%s: %s", shot_id, exc)


def _rebuild_asset_level_commit(session: Session, asset_id: int, provider, *, force: bool) -> str:  # noqa: ANN001
    try:
        status = rebuild_asset_level_document(session, asset_id, provider, force_reembed=force)
        session.commit()
        return status
    except IntegrityError:
        session.rollback()
        status = rebuild_asset_level_document(session, asset_id, provider, force_reembed=force)
        session.commit()
        return status


@celery_app.task(
    name=TASK_REBUILD_ASSET_LEVEL_DOC, bind=True, acks_late=True, max_retries=_MAX_RETRIES
)
def rebuild_asset_level_doc(self, asset_id: int, force_reembed: bool = False) -> dict[str, Any]:  # noqa: ANN001
    """P2a：素材级检索文档重建（图片=分析结果；视频=镜头有效文档聚合）。"""
    provider = build_embedding_provider(get_settings())
    with SessionLocal() as session:
        status = _rebuild_asset_level_commit(session, asset_id, provider, force=force_reembed)
    if status == "retry":
        raise self.retry(countdown=_backoff(self.request.retries))
    return {"asset_id": asset_id, "status": status}
