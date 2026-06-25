"""镜头后端筛选（PR-03B.1：projection-first）。

正常列表筛选只走结构化投影，不再扫描 JSONB：
- 内容标签（scene/action/shot_type/marketing/quality/risk）→ 有效 ShotTag（EXISTS）。
  有效来源：confirmed/modified 且未 stale → human 标签；否则 → ai 标签（latest 成功分析投影）。
- review_status/stale → shot_review_state（按当前 generation 联接）。
- has_ai_result → ai_shot_analysis。
- product_id → shot_review_state.confirmed_product_id（人工确认产品；AI 候选不作正式筛选）。
- rejected/unable 默认排除（除非 include_excluded）。
JSONB 仅用于详情/对照/审计/投影重建，不在此处做 fallback。
数据库层 WHERE + 分页 + 稳定排序。
"""

from __future__ import annotations

from typing import Any

from clipmind_shared.models import AIShotAnalysis, Shot, ShotReviewState, ShotTag, Tag
from clipmind_shared.models.enums import ReviewStatus, ShotStatus, TagType
from sqlalchemy import Text, and_, case, cast, exists, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

_HUMAN = (ReviewStatus.CONFIRMED.value, ReviewStatus.MODIFIED.value)
_EXCLUDED = (ReviewStatus.REJECTED.value, ReviewStatus.UNABLE.value)
_CONTENT = (
    ("scene", TagType.SCENE),
    ("action", TagType.ACTION),
    ("shot_type", TagType.SHOT_TYPE),
    ("marketing_use", TagType.MARKETING),
    ("quality", TagType.QUALITY),
    ("risk", TagType.RISK),
)


def _base():
    # ShotReviewState 仅联接当前 generation 的审核行
    return (
        select(Shot)
        .outerjoin(AIShotAnalysis, AIShotAnalysis.shot_id == Shot.id)
        .outerjoin(
            ShotReviewState,
            and_(
                ShotReviewState.shot_id == Shot.id,
                ShotReviewState.shot_generation == Shot.generation,
            ),
        )
        .where(Shot.status == ShotStatus.READY)
    )


def _effective_source():
    """当前 shot 的有效标签来源：human（已审核未 stale）否则 ai。"""
    return case(
        (
            and_(
                ShotReviewState.review_status.in_(_HUMAN),
                ShotReviewState.stale_at.is_(None),
            ),
            literal("human"),
        ),
        else_=literal("ai"),
    )


def _tag_exists(ttype: TagType, value: str, eff_source):
    return exists(
        select(ShotTag.id)
        .join(Tag, Tag.id == ShotTag.tag_id)
        .where(
            ShotTag.shot_id == Shot.id,
            ShotTag.active.is_(True),
            cast(ShotTag.source, Text) == eff_source,
            Tag.tag_type == ttype,
            Tag.tag_name == value,
        )
    )


async def filter_shots(
    db: AsyncSession,
    *,
    asset_id: int | None = None,
    review_status: ReviewStatus | None = None,
    has_ai_result: bool | None = None,
    stale: bool | None = None,
    product_id: int | None = None,
    scene: str | None = None,
    action: str | None = None,
    shot_type: str | None = None,
    marketing_use: str | None = None,
    quality: str | None = None,
    risk: str | None = None,
    include_excluded: bool = False,
    sort: str = "sequence",
    page: int = 1,
    page_size: int = 24,
) -> tuple[list[Shot], int]:
    conds: list[Any] = []

    if asset_id is not None:
        conds.append(Shot.asset_id == asset_id)
    if review_status is not None:
        conds.append(ShotReviewState.review_status == review_status)
    if has_ai_result is True:
        conds.append(AIShotAnalysis.id.isnot(None))
    elif has_ai_result is False:
        conds.append(AIShotAnalysis.id.is_(None))
    if stale is True:
        conds.append(
            and_(
                ShotReviewState.id.isnot(None),
                ShotReviewState.shot_generation != Shot.generation,
            )
        )
    if product_id is not None:
        conds.append(ShotReviewState.confirmed_product_id == product_id)
    if not include_excluded:
        conds.append(
            or_(
                ShotReviewState.id.is_(None),
                ShotReviewState.shot_generation != Shot.generation,
                ShotReviewState.review_status.notin_(_EXCLUDED),
            )
        )

    eff_source = _effective_source()
    values = (scene, action, shot_type, marketing_use, quality, risk)
    for value, (_key, ttype) in zip(values, _CONTENT, strict=True):
        if value:
            conds.append(_tag_exists(ttype, value, eff_source))

    where = and_(*conds) if conds else None
    base = _base()
    if where is not None:
        base = base.where(where)

    count_stmt = select(func.count()).select_from(base.order_by(None).subquery())
    total = int((await db.execute(count_stmt)).scalar() or 0)

    if sort == "newest":
        base = base.order_by(Shot.created_at.desc(), Shot.id.desc())
    elif sort == "confidence":
        base = base.order_by(AIShotAnalysis.confidence.desc().nullslast(), Shot.id.asc())
    else:  # sequence
        base = base.order_by(Shot.asset_id.asc(), Shot.sequence_no.asc(), Shot.id.asc())

    base = base.limit(page_size).offset((page - 1) * page_size)
    rows = list((await db.execute(base)).scalars().all())
    return rows, total
