"""VIS-AUTO Celery 任务（search 队列）：视觉嵌入索引 + 自动产品候选。

- visual_index_target：单目标（asset 海报 / shot 关键帧 / reference 原图）
  算向量并（asset/shot 且开关开时）就地重算候选；embedder 不可达记 failed，
  绝不阻塞主链、绝不写产品归属。
- sweep_visual_index：兜底扫描（缺嵌入 / failed 恢复 / 参考集变化致候选
  水位落后），批量入队 visual_index_target。由 scan 任务尾部触发。
"""

from __future__ import annotations

import logging
from typing import Any

from clipmind_shared.constants import (
    QUEUE_SEARCH,
    TASK_SWEEP_VISUAL_INDEX,
    TASK_VISUAL_INDEX_TARGET,
)

from clipmind_worker.celery_app import celery_app
from clipmind_worker.config import get_settings
from clipmind_worker.db import SessionLocal
from clipmind_worker.vision.indexer import (
    _load_confusion_pairs,  # noqa: PLC2701
    build_visual_provider,
    load_family_ref_vectors,
    refresh_candidates,
    sweep_targets,
    upsert_embedding,
)

_logger = logging.getLogger(__name__)


@celery_app.task(name=TASK_VISUAL_INDEX_TARGET, bind=True, acks_late=True, max_retries=2)
def visual_index_target(self, target_type: str, target_id: int) -> dict[str, Any]:  # noqa: ANN001
    settings = get_settings()
    provider = build_visual_provider(settings)
    with SessionLocal() as session:
        emb, status = upsert_embedding(session, settings, provider, target_type, target_id)
        result: dict[str, Any] = {
            "target": f"{target_type}:{target_id}", "embedding": status,
        }
        if emb is None:
            session.commit()
            return result
        if (
            settings.visual_auto_candidates
            and target_type in ("asset", "shot")
            and emb.status == "completed"
        ):
            families, revision = load_family_ref_vectors(session, settings, provider)
            if emb.candidates_ref_revision != revision:
                pairs = _load_confusion_pairs(session)
                result["candidates"] = refresh_candidates(
                    session, settings, emb,
                    families=families, revision=revision, confusion_pairs=pairs,
                )
        session.commit()
        return result


@celery_app.task(name=TASK_SWEEP_VISUAL_INDEX, bind=True, acks_late=True)
def sweep_visual_index(self) -> dict[str, Any]:  # noqa: ANN001
    settings = get_settings()
    provider = build_visual_provider(settings)
    with SessionLocal() as session:
        plan = sweep_targets(session, settings, provider)
    enqueued = 0
    for asset_id in plan["assets"]:
        celery_app.send_task(
            TASK_VISUAL_INDEX_TARGET, args=["asset", asset_id], queue=QUEUE_SEARCH
        )
        enqueued += 1
    for shot_id in plan["shots"]:
        celery_app.send_task(
            TASK_VISUAL_INDEX_TARGET, args=["shot", shot_id], queue=QUEUE_SEARCH
        )
        enqueued += 1
    for ref_id in plan["references"]:
        celery_app.send_task(
            TASK_VISUAL_INDEX_TARGET, args=["reference", ref_id], queue=QUEUE_SEARCH
        )
        enqueued += 1
    for target_type, target_id in plan["stale_candidates"]:
        celery_app.send_task(
            TASK_VISUAL_INDEX_TARGET, args=[target_type, target_id], queue=QUEUE_SEARCH
        )
        enqueued += 1
    return {
        "enqueued": enqueued,
        "assets": len(plan["assets"]),
        "shots": len(plan["shots"]),
        "references": len(plan["references"]),
        "stale": len(plan["stale_candidates"]),
    }


def enqueue_visual_index(target_type: str, target_id: int) -> None:
    """给其他任务用的 best-effort 入队钩子（失败只记日志，不影响主流程）。"""
    try:
        celery_app.send_task(
            TASK_VISUAL_INDEX_TARGET, args=[target_type, target_id], queue=QUEUE_SEARCH
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning("视觉索引入队失败（%s:%s）: %s", target_type, target_id, type(exc).__name__)
