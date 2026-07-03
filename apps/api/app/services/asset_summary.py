"""素材审核汇总（PR-03B）：真实后端统计 + ai_overall_status 派生。

不允许前端逐镜头计算。批量加载素材的镜头 / AI 分析 / 审核状态，在后端聚合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from clipmind_shared.models import (
    AIAnalysisRun,
    AIShotAnalysis,
    Asset,
    Product,
    Shot,
    ShotReviewState,
    ShotTag,
    Tag,
)
from clipmind_shared.models.enums import (
    ACTIVE_AI_RUN_STATUSES,
    AIShotAnalysisStatus,
    ReviewStatus,
    ShotStatus,
    TagSource,
    TagType,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class AssetSummary:
    asset_id: int
    total_shots: int = 0
    ai_unanalyzed_count: int = 0
    ai_running_count: int = 0
    ai_failed_count: int = 0
    pending_review_count: int = 0
    unreviewed_count: int = 0
    confirmed_count: int = 0
    modified_count: int = 0
    rejected_count: int = 0
    unable_count: int = 0
    stale_review_count: int = 0
    risk_shot_count: int = 0
    primary_product: dict[str, Any] | None = None
    related_products: list[dict[str, Any]] = field(default_factory=list)
    ai_overall_status: str = "not_started"


def _overall_status(s: AssetSummary, *, ai_running: bool, ai_done: int) -> str:
    reviewed = s.confirmed_count + s.modified_count + s.rejected_count + s.unable_count
    if s.total_shots == 0:
        return "not_started"
    if ai_running:
        return "running"
    if ai_done == 0:
        return "not_started"
    if reviewed == s.total_shots:
        return "completed"
    if (s.confirmed_count + s.modified_count) > 0:
        return "partially_reviewed"
    if s.pending_review_count > 0 or s.unreviewed_count > 0:
        return "pending_review"
    if s.ai_failed_count == ai_done and reviewed == 0:
        return "failed"
    return "mixed"


async def compute_summary(db: AsyncSession, asset: Asset) -> AssetSummary:
    summary = AssetSummary(asset_id=asset.id)

    shots = list(
        (
            await db.execute(
                select(Shot).where(
                    Shot.asset_id == asset.id,
                    Shot.status == ShotStatus.READY,
                    Shot.retired_at.is_(None),
                )
            )
        ).scalars().all()
    )
    summary.total_shots = len(shots)
    shot_ids = [s.id for s in shots]

    ai_by_shot: dict[int, AIShotAnalysis] = {}
    if shot_ids:
        for a in (
            await db.execute(
                select(AIShotAnalysis).where(AIShotAnalysis.shot_id.in_(shot_ids))
            )
        ).scalars().all():
            ai_by_shot[a.shot_id] = a

    review_by_shot: dict[int, ShotReviewState] = {}
    if shot_ids:
        for r in (
            await db.execute(
                select(ShotReviewState).where(ShotReviewState.shot_id.in_(shot_ids))
            )
        ).scalars().all():
            # 仅当前代次的审核状态
            review_by_shot[r.shot_id] = r

    # active RISK 标签（按来源）用于 projection-first 的有效风险统计
    risk_by_shot: dict[int, set[str]] = {}
    if shot_ids:
        for sid, src in (
            await db.execute(
                select(ShotTag.shot_id, ShotTag.source)
                .join(Tag, Tag.id == ShotTag.tag_id)
                .where(
                    ShotTag.shot_id.in_(shot_ids),
                    ShotTag.active.is_(True),
                    Tag.tag_type == TagType.RISK,
                )
            )
        ).all():
            risk_by_shot.setdefault(sid, set()).add(src.value)

    ai_done = 0
    for shot in shots:
        ai = ai_by_shot.get(shot.id)
        review = review_by_shot.get(shot.id)
        if ai is None:
            summary.ai_unanalyzed_count += 1
        else:
            ai_done += 1
            if ai.status == AIShotAnalysisStatus.FAILED:
                summary.ai_failed_count += 1

        # 审核状态计数（仅当前代次）
        same_gen = review is not None and review.shot_generation == shot.generation
        rs = review.review_status if same_gen else None
        if rs == ReviewStatus.CONFIRMED:
            summary.confirmed_count += 1
        elif rs == ReviewStatus.MODIFIED:
            summary.modified_count += 1
        elif rs == ReviewStatus.REJECTED:
            summary.rejected_count += 1
        elif rs == ReviewStatus.UNABLE:
            summary.unable_count += 1
        elif rs == ReviewStatus.PENDING_REVIEW:
            summary.pending_review_count += 1
        else:
            summary.unreviewed_count += 1

        # stale：审核绑定代次与当前不一致
        if review is not None and review.shot_generation != shot.generation:
            summary.stale_review_count += 1

        # 有效风险（projection-first）：排除 rejected/unable；有效来源的 active RISK 标签
        if rs not in (ReviewStatus.REJECTED, ReviewStatus.UNABLE):
            eff_src = (
                TagSource.HUMAN.value
                if rs in (ReviewStatus.CONFIRMED, ReviewStatus.MODIFIED)
                else TagSource.AI.value
            )
            if eff_src in risk_by_shot.get(shot.id, set()):
                summary.risk_shot_count += 1

    # 是否有活动 AI 运行
    active_run = (
        await db.execute(
            select(AIAnalysisRun.id).where(
                AIAnalysisRun.asset_id == asset.id,
                AIAnalysisRun.status.in_(list(ACTIVE_AI_RUN_STATUSES)),
            )
        )
    ).first()
    ai_running = active_run is not None

    # 产品
    if asset.primary_product_id is not None:
        p = await db.get(Product, asset.primary_product_id)
        if p is not None:
            summary.primary_product = {"id": p.id, "name": p.name, "brand": p.brand}

    summary.ai_overall_status = _overall_status(summary, ai_running=ai_running, ai_done=ai_done)
    return summary
