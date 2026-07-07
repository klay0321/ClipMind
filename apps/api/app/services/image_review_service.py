"""IMG-REVIEW：图片素材 AI 理解的人工审核（对齐镜头审核范式）。

与 review_service（镜头）的差异：图片无代次、无 tag 投影（图片检索走
asset_search_document，审核落地 = 触发文档重建让 effective 结果生效）。
状态机 / 乐观锁 / schema 校验 / ReviewEvent 审计完全同款。
"""

from __future__ import annotations

import logging
from typing import Any

from clipmind_shared.ai.schema import ShotAnalysisResult
from clipmind_shared.constants import AI_SCHEMA_VERSION
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    AssetImageAnalysis,
    AssetImageReviewState,
    ReviewEvent,
)
from clipmind_shared.models.enums import (
    AIShotAnalysisStatus,
    ReviewAction,
    ReviewStatus,
)
from clipmind_shared.review.state_machine import next_status
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.review_service import (
    ReviewConflict,
    ReviewPayload,
    ReviewSchemaError,
)

logger = logging.getLogger(__name__)


async def get_image_analysis(db: AsyncSession, asset_id: int) -> AssetImageAnalysis | None:
    return (
        await db.execute(
            select(AssetImageAnalysis).where(AssetImageAnalysis.asset_id == asset_id)
        )
    ).scalar_one_or_none()


async def get_image_review_state(
    db: AsyncSession, asset_id: int
) -> AssetImageReviewState | None:
    return (
        await db.execute(
            select(AssetImageReviewState).where(
                AssetImageReviewState.asset_id == asset_id
            )
        )
    ).scalar_one_or_none()


def compute_effective(
    ai: AssetImageAnalysis | None, review: AssetImageReviewState | None
) -> tuple[str, dict[str, Any] | None]:
    """有效结果解析：人工确认/修改优先；驳回 → 无有效结果；否则 AI。"""
    if review is not None:
        if review.review_status in (ReviewStatus.CONFIRMED, ReviewStatus.MODIFIED):
            return "human", review.confirmed_result
        if review.review_status in (ReviewStatus.REJECTED, ReviewStatus.UNABLE):
            return "rejected", None
    if ai is not None and ai.status == AIShotAnalysisStatus.COMPLETED and ai.parsed_result:
        return "ai", dict(ai.parsed_result)
    return "none", None


def _validate_result(result: dict[str, Any] | None) -> dict[str, Any]:
    # 图片打标复用镜头分析 schema（runner 即如此），审核校验保持同一契约
    try:
        return ShotAnalysisResult.model_validate(result or {}).model_dump()
    except ValidationError as exc:
        raise ReviewSchemaError(str(exc)) from exc


async def apply_image_review(
    db: AsyncSession, asset: Asset, payload: ReviewPayload
) -> AssetImageReviewState:
    """事务化执行一次图片审核动作；提交后由调用方触发搜索文档重建。"""
    ai = await get_image_analysis(db, asset.id)
    row = await get_image_review_state(db, asset.id)
    current = row.review_status if row else ReviewStatus.UNREVIEWED

    target = next_status(current, payload.action)  # 非法 → InvalidReviewTransition

    new_cr: dict[str, Any] | None = None
    if payload.action == ReviewAction.CONFIRM:
        new_cr = ai.parsed_result if ai else {}
    elif payload.action == ReviewAction.MODIFY:
        new_cr = _validate_result(payload.confirmed_result)

    before = {
        "review_status": current.value,
        "confirmed_result": row.confirmed_result if row else None,
    }
    now = utcnow()
    fields = dict(
        review_status=target,
        confirmed_result=new_cr,
        reviewer_label=payload.reviewer_label,
        review_comment=payload.comment,
        reviewed_at=now,
        source_image_analysis_id=payload.source_ai_analysis_id or (ai.id if ai else None),
        source_input_fingerprint=(
            payload.source_input_fingerprint or (ai.input_fingerprint if ai else None)
        ),
        result_schema_version=AI_SCHEMA_VERSION,
        stale_at=None,
        stale_reason=None,
        updated_at=now,
    )

    if row is not None:
        res = await db.execute(
            update(AssetImageReviewState)
            .where(
                AssetImageReviewState.id == row.id,
                AssetImageReviewState.lock_version == payload.lock_version,
            )
            .values(lock_version=AssetImageReviewState.lock_version + 1, **fields)
        )
        if res.rowcount == 0:
            raise ReviewConflict("lock_version 不匹配（并发冲突）")
    else:
        if payload.lock_version != 0:
            raise ReviewConflict("审核状态行不存在，lock_version 应为 0")
        db.add(AssetImageReviewState(asset_id=asset.id, lock_version=1, **fields))
        await db.flush()

    db.add(
        ReviewEvent(
            object_type="asset_image",
            object_id=asset.id,
            source_ai_analysis_id=None,  # 语义为镜头分析 id，图片行不复用（见 after_data）
            reviewer_label=payload.reviewer_label,
            action=payload.action,
            before_data=before,
            after_data={
                "review_status": target.value,
                "confirmed_result": new_cr,
                "source_image_analysis_id": fields["source_image_analysis_id"],
            },
            comment=payload.comment,
        )
    )
    await db.commit()
    return await get_image_review_state(db, asset.id)
