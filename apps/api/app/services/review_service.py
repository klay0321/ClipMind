"""人工审核服务（PR-03B Gate B 核心）。

保证：
- 显式状态机（非法转换 409）；
- 乐观锁：UPDATE ... WHERE lock_version=旧值，rowcount=0 → 409（数据库层防并发，非 Python 判断）；
- 同一事务内：更新 shot_review_state → 旧 human 标签置 inactive → 创建/复用 Tag → 写新 human
  标签 → 更新 confirmed_product_id → 新增 review_event；任一步失败全部回滚；
- AI 重新分析保护：effective-result 返回 has_newer_ai_result / review_is_stale / stale_reason；
  人工结果不被 AI 覆盖；rejected/unable 无有效结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clipmind_shared.ai.schema import ShotAnalysisResult
from clipmind_shared.constants import AI_SCHEMA_VERSION
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIShotAnalysis,
    ReviewEvent,
    Shot,
    ShotReviewState,
    ShotTag,
    Tag,
)
from clipmind_shared.models.enums import (
    ReviewAction,
    ReviewStatus,
    TagSource,
)
from clipmind_shared.review import (
    InvalidReviewTransition,
    effective_result,
    next_status,
    normalize_name,
    projected_tags,
)
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class ReviewConflict(Exception):
    """乐观锁版本冲突或状态行竞态。"""


class ReviewSchemaError(Exception):
    """confirmed_result 不符合 Schema。"""


@dataclass
class ReviewPayload:
    action: ReviewAction
    lock_version: int
    reviewer_label: str
    source_ai_analysis_id: int | None = None
    shot_generation: int | None = None
    source_input_fingerprint: str | None = None
    comment: str | None = None
    confirmed_result: dict[str, Any] | None = None
    confirmed_product_id: int | None = None


async def get_review_state(
    db: AsyncSession, shot_id: int, generation: int
) -> ShotReviewState | None:
    stmt = select(ShotReviewState).where(
        ShotReviewState.shot_id == shot_id,
        ShotReviewState.shot_generation == generation,
    )
    return (await db.execute(stmt)).scalars().first()


async def get_current_ai(db: AsyncSession, shot_id: int) -> AIShotAnalysis | None:
    stmt = select(AIShotAnalysis).where(AIShotAnalysis.shot_id == shot_id)
    return (await db.execute(stmt)).scalars().first()


@dataclass
class EffectiveView:
    shot_id: int
    review_status: str
    source: str               # human | ai | rejected | unable | none
    confirmed: bool
    searchable: bool
    result: dict[str, Any] | None
    ai_status: str | None     # 当前 AI 分析状态
    has_newer_ai_result: bool
    review_is_stale: bool
    stale_reason: str | None


async def compute_effective(db: AsyncSession, shot: Shot) -> EffectiveView:
    ai = await get_current_ai(db, shot.id)
    review = await get_review_state(db, shot.id, shot.generation)
    ai_parsed = ai.parsed_result if ai else None

    rs = review.review_status.value if review else None
    eff = effective_result(
        ai_parsed,
        review_status=rs,
        confirmed_result=review.confirmed_result if review else None,
    )

    # 区分两类"重新分析"：
    # - generation 改变（重拆镜头，帧变）：人工结果失效（stale），降级为 AI 临时结果；
    # - 同 generation 的 fingerprint 改变（同帧、不同模型/提示）：人工仍有效，仅标 has_newer。
    stale_reason = None
    has_newer = False
    if review is not None:
        cur_fp = ai.input_fingerprint if ai else None
        gen_changed = review.shot_generation != shot.generation
        fp_changed = bool(
            review.source_input_fingerprint
            and cur_fp
            and review.source_input_fingerprint != cur_fp
        )
        if gen_changed:
            stale_reason = "generation_changed"
        elif review.stale_reason:
            stale_reason = review.stale_reason
        if ai is not None:
            has_newer = (review.source_ai_analysis_id != ai.id) or fp_changed
    is_stale = stale_reason is not None
    if eff.source == "human" and is_stale:
        eff = effective_result(ai_parsed, review_status=None, confirmed_result=None)

    return EffectiveView(
        shot_id=shot.id,
        review_status=rs or ReviewStatus.UNREVIEWED.value,
        source=eff.source,
        confirmed=eff.confirmed,
        searchable=eff.searchable,
        result=eff.result,
        ai_status=ai.status.value if ai else None,
        has_newer_ai_result=has_newer,
        review_is_stale=is_stale,
        stale_reason=stale_reason,
    )


async def _get_or_create_tag(db: AsyncSession, tag_type: str, tag_name: str) -> Tag:
    norm = normalize_name(tag_name)
    stmt = select(Tag).where(Tag.tag_type == tag_type, Tag.normalized_name == norm)
    tag = (await db.execute(stmt)).scalars().first()
    if tag is None:
        tag = Tag(tag_type=tag_type, tag_name=tag_name, normalized_name=norm)
        db.add(tag)
        await db.flush()
    return tag


async def _deactivate_human_tags(db: AsyncSession, shot_id: int) -> None:
    await db.execute(
        update(ShotTag)
        .where(
            ShotTag.shot_id == shot_id,
            ShotTag.source == TagSource.HUMAN,
            ShotTag.active.is_(True),
        )
        .values(active=False, updated_at=utcnow())
    )


async def _project_human_tags(
    db: AsyncSession,
    shot_id: int,
    result: dict[str, Any],
    reviewer_label: str,
    source_ai_analysis_id: int | None,
) -> None:
    for tag_type, tag_name in projected_tags(result):
        tag = await _get_or_create_tag(db, tag_type, tag_name)
        db.add(
            ShotTag(
                shot_id=shot_id, tag_id=tag.id, source=TagSource.HUMAN,
                source_ai_analysis_id=source_ai_analysis_id,
                confirmed_by=reviewer_label, confirmed_at=utcnow(), active=True,
            )
        )
    await db.flush()


def _validate_result(result: dict[str, Any] | None) -> dict[str, Any]:
    try:
        return ShotAnalysisResult.model_validate(result or {}).model_dump()
    except ValidationError as exc:  # noqa: TRY003
        raise ReviewSchemaError(str(exc)) from exc


async def apply_review(db: AsyncSession, shot: Shot, payload: ReviewPayload) -> ShotReviewState:
    """事务化执行一次审核动作。失败抛 ReviewConflict/ReviewSchemaError/InvalidReviewTransition。"""
    ai = await get_current_ai(db, shot.id)
    row = await get_review_state(db, shot.id, shot.generation)
    current = row.review_status if row else ReviewStatus.UNREVIEWED

    target = next_status(current, payload.action)  # 非法 → InvalidReviewTransition

    # 确定新的有效结果（confirm=采用 AI；modify=人工编辑；其余=清空）
    new_cr: dict[str, Any] | None = None
    if payload.action == ReviewAction.CONFIRM:
        new_cr = ai.parsed_result if ai else {}
    elif payload.action == ReviewAction.MODIFY:
        new_cr = _validate_result(payload.confirmed_result)

    before = {
        "review_status": current.value,
        "confirmed_result": row.confirmed_result if row else None,
        "confirmed_product_id": row.confirmed_product_id if row else None,
    }
    now = utcnow()
    fields = dict(
        review_status=target,
        confirmed_result=new_cr,
        confirmed_product_id=payload.confirmed_product_id,
        reviewer_label=payload.reviewer_label,
        review_comment=payload.comment,
        reviewed_at=now,
        source_ai_analysis_id=payload.source_ai_analysis_id or (ai.id if ai else None),
        source_input_fingerprint=(
            payload.source_input_fingerprint or (ai.input_fingerprint if ai else None)
        ),
        result_schema_version=AI_SCHEMA_VERSION,
        stale_at=None,
        stale_reason=None,
        updated_at=now,
    )

    if row is not None:
        # 乐观锁：数据库层匹配旧 lock_version
        res = await db.execute(
            update(ShotReviewState)
            .where(
                ShotReviewState.id == row.id,
                ShotReviewState.lock_version == payload.lock_version,
            )
            .values(lock_version=ShotReviewState.lock_version + 1, **fields)
        )
        if res.rowcount == 0:
            raise ReviewConflict("lock_version 不匹配（并发冲突）")
    else:
        if payload.lock_version != 0:
            raise ReviewConflict("审核状态行不存在，lock_version 应为 0")
        db.add(
            ShotReviewState(
                shot_id=shot.id, shot_generation=shot.generation, lock_version=1, **fields
            )
        )
        await db.flush()

    # 投影同步（同一事务）
    await _deactivate_human_tags(db, shot.id)
    if target in (ReviewStatus.CONFIRMED, ReviewStatus.MODIFIED) and new_cr:
        await _project_human_tags(
            db, shot.id, new_cr, payload.reviewer_label, fields["source_ai_analysis_id"]
        )

    db.add(
        ReviewEvent(
            object_type="shot",
            object_id=shot.id,
            shot_id_snapshot=shot.id,
            shot_generation_snapshot=shot.generation,
            source_ai_analysis_id=fields["source_ai_analysis_id"],
            reviewer_label=payload.reviewer_label,
            action=payload.action,
            before_data=before,
            after_data={
                "review_status": target.value,
                "confirmed_result": new_cr,
                "confirmed_product_id": payload.confirmed_product_id,
            },
            comment=payload.comment,
        )
    )
    await db.commit()
    return await get_review_state(db, shot.id, shot.generation)


async def list_review_events(db: AsyncSession, shot_id: int) -> list[ReviewEvent]:
    stmt = (
        select(ReviewEvent)
        .where(ReviewEvent.object_type == "shot", ReviewEvent.object_id == shot_id)
        .order_by(ReviewEvent.id.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


# 重新导出，便于 router 捕获
__all__ = [
    "ReviewPayload",
    "ReviewConflict",
    "ReviewSchemaError",
    "InvalidReviewTransition",
    "apply_review",
    "compute_effective",
    "get_review_state",
    "list_review_events",
    "EffectiveView",
]
