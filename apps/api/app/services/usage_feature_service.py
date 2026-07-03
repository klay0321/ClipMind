"""PR-E 使用特征批量投影（docs/USAGE_AWARE_SEARCH.md；零新表零迁移）。

冻结语义：
- Shot 正式特征只来源于 status=confirmed 的 FinalVideoUsage；正式次数 =
  **不同 Final Video 去重**后的 confirmed usage 数（多 occurrence 不加次数）；
- Asset 聚合按 asset_id；区分"当前 Shot 从未使用但同 Asset 其他 Shot 用过"
  ——绝不把 Asset 次数当作每个 Shot 的次数；
- legacy 只用 review_status=accepted（pending/rejected/conflict 一律 0 参与）；
  accepted legacy 不增加正式次数；
- proposed/suspected 只作展示计数（pending_formal_count），不进正式特征；
- 批量查询（固定 4 条聚合 SQL，绝不逐结果查库）；UTC；无记录零值；
  历史（retired）Shot 的正式血缘仍参与自身与 Asset 统计。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from clipmind_shared.models import (
    FinalVideoUsage,
    LegacyUsageEvidence,
    Shot,
)
from clipmind_shared.models.enums import FinalVideoUsageStatus, ShotStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# usage_state 白名单（优先级从高到低）
USAGE_STATES = (
    "confirmed_used",
    "legacy_used_unknown",
    "usage_needs_review",
    "never_confirmed_used",
)


@dataclass
class UsageFeatures:
    """单 Shot 的使用特征（保留全部原始字段，状态只是派生便签）。"""

    shot_id: int
    asset_id: int | None = None
    # Shot 级（confirmed only；去重成片）
    shot_confirmed_usage_count: int = 0
    shot_distinct_final_video_count: int = 0
    shot_last_confirmed_used_at: datetime | None = None
    # Asset 级
    asset_confirmed_usage_count: int = 0
    asset_distinct_final_video_count: int = 0
    asset_used_shot_count: int = 0
    asset_total_current_shot_count: int = 0
    asset_last_confirmed_used_at: datetime | None = None
    # legacy（accepted only）与待确认（仅展示）
    accepted_legacy_evidence_count: int = 0
    pending_formal_count: int = 0
    # 派生状态（不丢原始字段）
    usage_state: str = "never_confirmed_used"

    def days_since_last_confirmed_use(self, now: datetime) -> float | None:
        if self.shot_last_confirmed_used_at is None:
            return None
        ts = self.shot_last_confirmed_used_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return max(0.0, (now - ts).total_seconds() / 86400.0)


def _derive_state(f: UsageFeatures) -> str:
    if f.shot_confirmed_usage_count > 0:
        return "confirmed_used"
    if f.accepted_legacy_evidence_count > 0:
        return "legacy_used_unknown"
    if f.pending_formal_count > 0:
        return "usage_needs_review"
    return "never_confirmed_used"


async def batch_features(
    db: AsyncSession, shot_ids: list[int]
) -> dict[int, UsageFeatures]:
    """批量投影：固定 4 条聚合 SQL（与候选数无关），返回全量 shot_id 映射。"""
    if not shot_ids:
        return {}
    ids = list(dict.fromkeys(shot_ids))
    out: dict[int, UsageFeatures] = {sid: UsageFeatures(shot_id=sid) for sid in ids}

    # ① shot → asset 映射（不过滤 retired：历史 Shot 统计自身血缘）
    shot_rows = (
        await db.execute(select(Shot.id, Shot.asset_id).where(Shot.id.in_(ids)))
    ).all()
    asset_ids = {aid for _, aid in shot_rows}
    for sid, aid in shot_rows:
        out[sid].asset_id = aid

    # ② Shot 级 confirmed（去重成片 = 正式次数；occurrence 天然不计）
    shot_usage = (
        await db.execute(
            select(
                FinalVideoUsage.source_shot_id,
                func.count(func.distinct(FinalVideoUsage.final_video_id)),
                func.max(FinalVideoUsage.confirmed_at),
            )
            .where(
                FinalVideoUsage.source_shot_id.in_(ids),
                FinalVideoUsage.status == FinalVideoUsageStatus.CONFIRMED,
            )
            .group_by(FinalVideoUsage.source_shot_id)
        )
    ).all()
    for sid, distinct_fv, last_at in shot_usage:
        f = out[sid]
        f.shot_distinct_final_video_count = int(distinct_fv)
        f.shot_confirmed_usage_count = int(distinct_fv)  # 冻结口径：去重成片数
        f.shot_last_confirmed_used_at = last_at

    # ②b 待确认（proposed/suspected；仅展示，不进正式特征）
    pending_rows = (
        await db.execute(
            select(FinalVideoUsage.source_shot_id, func.count(FinalVideoUsage.id))
            .where(
                FinalVideoUsage.source_shot_id.in_(ids),
                FinalVideoUsage.status.in_(
                    [FinalVideoUsageStatus.PROPOSED, FinalVideoUsageStatus.SUSPECTED]
                ),
            )
            .group_by(FinalVideoUsage.source_shot_id)
        )
    ).all()
    for sid, cnt in pending_rows:
        out[sid].pending_formal_count = int(cnt)

    if asset_ids:
        # ③ Asset 级聚合（confirmed）+ 当前代次镜头总数
        asset_usage = {
            aid: (int(fv), int(used_shots), last_at)
            for aid, fv, used_shots, last_at in (
                await db.execute(
                    select(
                        FinalVideoUsage.source_asset_id,
                        func.count(func.distinct(FinalVideoUsage.final_video_id)),
                        func.count(func.distinct(FinalVideoUsage.source_shot_id)),
                        func.max(FinalVideoUsage.confirmed_at),
                    )
                    .where(
                        FinalVideoUsage.source_asset_id.in_(asset_ids),
                        FinalVideoUsage.status == FinalVideoUsageStatus.CONFIRMED,
                    )
                    .group_by(FinalVideoUsage.source_asset_id)
                )
            ).all()
        }
        current_counts = {
            aid: int(cnt)
            for aid, cnt in (
                await db.execute(
                    select(Shot.asset_id, func.count(Shot.id))
                    .where(
                        Shot.asset_id.in_(asset_ids),
                        Shot.status == ShotStatus.READY,
                        Shot.retired_at.is_(None),
                    )
                    .group_by(Shot.asset_id)
                )
            ).all()
        }
        # ④ legacy accepted（asset 级；其余状态一律不计）
        legacy_counts = {
            aid: int(cnt)
            for aid, cnt in (
                await db.execute(
                    select(LegacyUsageEvidence.asset_id, func.count(LegacyUsageEvidence.id))
                    .where(
                        LegacyUsageEvidence.asset_id.in_(asset_ids),
                        LegacyUsageEvidence.review_status == "accepted",
                    )
                    .group_by(LegacyUsageEvidence.asset_id)
                )
            ).all()
        }
        for f in out.values():
            if f.asset_id is None:
                continue
            au = asset_usage.get(f.asset_id)
            if au:
                f.asset_distinct_final_video_count = au[0]
                f.asset_confirmed_usage_count = au[0]  # 同口径：去重成片数
                f.asset_used_shot_count = au[1]
                f.asset_last_confirmed_used_at = au[2]
            f.asset_total_current_shot_count = current_counts.get(f.asset_id, 0)
            f.accepted_legacy_evidence_count = legacy_counts.get(f.asset_id, 0)

    for f in out.values():
        f.usage_state = _derive_state(f)
    return out


@dataclass
class UsageQueryStats:
    """可观测性：一次搜索中的特征投影统计（日志/测试用，不含真实查询内容）。"""

    feature_query_count: int = 4
    projected_shot_count: int = 0
    elapsed_ms: int = 0
    extra: dict = field(default_factory=dict)
