"""PR-E 使用感知排序与硬过滤（纯逻辑，可单测；docs/USAGE_AWARE_SEARCH.md）。

铁律：
- 使用信息只调整候选的过滤与排序，**不伪造语义相关性**：
  ``final_score = base_relevance + adjustment``，|adjustment| ≤ ADJUSTMENT_CAP < 1，
  语义相关性保持主要信号（明显低相关不可仅因未使用越位——relevance guard 测试锁定）；
- default 模式 adjustment ≡ 0（排序、分数与旧实现完全一致）；
- legacy 只认 accepted 且惩罚显著弱于正式 confirmed；pending/rejected/conflict
  与 proposed/suspected 的 adjustment 一律为 0；
- 使用次数为 0 不产生 count penalty；时间缺失不产生 recent penalty；
- 相同输入结果确定（tie-break: final↓, base↓, shot_id↑）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import HTTPException

from app.services.usage_feature_service import UsageFeatures

# 调整总量上限（绝对值）：保证相关性主导
ADJUSTMENT_CAP = 0.35
# 单权重服务器安全范围
WEIGHT_MIN = 0.0
WEIGHT_MAX = 0.20
LEGACY_WEIGHT_MAX = 0.05   # legacy 惩罚显著弱于正式 confirmed
DECAY_DAYS_MIN = 1.0
DECAY_DAYS_MAX = 365.0

USAGE_MODES = (
    "default",
    "prefer_unused",
    "only_never_confirmed",
    "exclude_high_frequency",
    "least_recently_used",
)
USAGE_SCOPES = ("shot", "asset", "combined")
WEIGHT_PRESETS = ("balanced", "strong_unused", "relevance_first")


@dataclass(frozen=True)
class UsageWeights:
    """一组经校验的安全权重（预设或受约束的请求级 override）。"""

    weight_unused: float = 0.06
    weight_count: float = 0.05
    weight_recent: float = 0.05
    weight_asset: float = 0.02
    weight_legacy: float = 0.02
    weight_lru: float = 0.05        # least_recently_used 模式的久未使用奖励
    decay_days: float = 30.0


PRESETS: dict[str, UsageWeights] = {
    # 均衡：未使用适度奖励 + 高频/近期适度惩罚 + legacy 弱提示
    "balanced": UsageWeights(),
    # 强未使用优先：奖励与惩罚都放大（仍受 cap 约束）
    "strong_unused": UsageWeights(
        weight_unused=0.12, weight_count=0.10, weight_recent=0.08,
        weight_asset=0.04, weight_legacy=0.03, weight_lru=0.08,
    ),
    # 相关性优先：只保留极轻调整、legacy 零参与
    "relevance_first": UsageWeights(
        weight_unused=0.02, weight_count=0.02, weight_recent=0.02,
        weight_asset=0.01, weight_legacy=0.0, weight_lru=0.02,
    ),
}


def _check_weight(name: str, value: float, upper: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{name} 非法") from exc
    if math.isnan(v) or math.isinf(v):
        raise HTTPException(status_code=422, detail=f"{name} 不允许 NaN/Infinity")
    if not (WEIGHT_MIN <= v <= upper):
        raise HTTPException(
            status_code=422, detail=f"{name} 超出安全范围 [{WEIGHT_MIN},{upper}]"
        )
    return v


def resolve_weights(preset: str, override: dict | None) -> UsageWeights:
    """预设 + 受约束的请求级 override（越权/NaN/Inf → 422）。"""
    if preset not in WEIGHT_PRESETS:
        raise HTTPException(status_code=422, detail=f"不支持的排序预设: {preset}")
    base = PRESETS[preset]
    if not override:
        return base
    allowed = {
        "weight_unused", "weight_count", "weight_recent",
        "weight_asset", "weight_legacy", "weight_lru", "decay_days",
    }
    unknown = set(override) - allowed
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"不支持的权重字段: {','.join(sorted(unknown))}"
        )
    values = {
        "weight_unused": base.weight_unused,
        "weight_count": base.weight_count,
        "weight_recent": base.weight_recent,
        "weight_asset": base.weight_asset,
        "weight_legacy": base.weight_legacy,
        "weight_lru": base.weight_lru,
        "decay_days": base.decay_days,
    }
    for key, raw in override.items():
        if key == "decay_days":
            try:
                v = float(raw)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="decay_days 非法") from exc
            if math.isnan(v) or math.isinf(v) or not (DECAY_DAYS_MIN <= v <= DECAY_DAYS_MAX):
                raise HTTPException(
                    status_code=422,
                    detail=f"decay_days 超出范围 [{DECAY_DAYS_MIN},{DECAY_DAYS_MAX}]",
                )
            values[key] = v
        elif key == "weight_legacy":
            values[key] = _check_weight(key, raw, LEGACY_WEIGHT_MAX)
        else:
            values[key] = _check_weight(key, raw, WEIGHT_MAX)
    return UsageWeights(**values)


@dataclass
class UsageReason:
    code: str
    adjustment: float
    message: str


@dataclass
class UsageAdjustment:
    shot_id: int
    base_score: float
    adjustment: float = 0.0
    final_score: float = 0.0
    reasons: list[UsageReason] = field(default_factory=list)


def compute_adjustment(
    f: UsageFeatures,
    *,
    weights: UsageWeights,
    mode: str,
    scope: str,
    include_legacy_unknown: bool,
    now: datetime,
) -> tuple[float, list[UsageReason]]:
    """单候选调整量（确定性；default 模式恒 0）。"""
    if mode == "default":
        return 0.0, []
    reasons: list[UsageReason] = []
    adj = 0.0
    shot_signals = scope in ("shot", "combined")
    asset_signals = scope in ("asset", "combined")

    if shot_signals and f.shot_confirmed_usage_count == 0:
        bonus = weights.weight_unused
        if bonus > 0:
            adj += bonus
            reasons.append(UsageReason(
                "shot_never_used", round(bonus, 4), "该镜头从未被正式成片使用"
            ))
    if shot_signals and f.shot_confirmed_usage_count > 0 and weights.weight_count > 0:
        pen = weights.weight_count * math.log1p(f.shot_confirmed_usage_count)
        adj -= pen
        reasons.append(UsageReason(
            "shot_used_multiple_times" if f.shot_confirmed_usage_count > 1 else "shot_used_once",
            round(-pen, 4),
            f"该镜头已被 {f.shot_confirmed_usage_count} 条成片确认使用",
        ))
    days = f.days_since_last_confirmed_use(now)
    if shot_signals and days is not None and weights.weight_recent > 0:
        pen = weights.weight_recent * math.exp(-days / weights.decay_days)
        if pen > 1e-6:
            adj -= pen
            reasons.append(UsageReason(
                "shot_recently_used", round(-pen, 4),
                f"该镜头最近 {int(days)} 天内被使用过",
            ))
    if mode == "least_recently_used" and shot_signals and weights.weight_lru > 0:
        # 从未使用 = 最久未使用（有明确位置）；时间缺失不当错误
        lru_factor = 1.0 if days is None else 1.0 - math.exp(-days / weights.decay_days)
        bonus = weights.weight_lru * lru_factor
        if bonus > 1e-6:
            adj += bonus
            reasons.append(UsageReason(
                "least_recently_used_bonus", round(bonus, 4),
                "久未使用（相关性相近时优先）" if days is not None else "从未使用（优先）",
            ))
    if asset_signals and f.asset_distinct_final_video_count > 0 and weights.weight_asset > 0:
        pen = weights.weight_asset * math.log1p(f.asset_distinct_final_video_count)
        adj -= pen
        reasons.append(UsageReason(
            "asset_reused_across_videos", round(-pen, 4),
            f"同一素材已被 {f.asset_distinct_final_video_count} 条成片复用",
        ))
    if (
        include_legacy_unknown
        and f.accepted_legacy_evidence_count > 0
        and weights.weight_legacy > 0
    ):
        pen = weights.weight_legacy  # 固定弱惩罚（不随条数放大——弱证据不精确计数）
        adj -= pen
        reasons.append(UsageReason(
            "legacy_used_unknown_hint", round(-pen, 4),
            "该素材历史上可能使用过（次数未知）",
        ))

    # 总量截断（保证相关性主导）
    if adj > ADJUSTMENT_CAP:
        adj = ADJUSTMENT_CAP
    elif adj < -ADJUSTMENT_CAP:
        adj = -ADJUSTMENT_CAP
    return adj, reasons


def hard_filter_predicate(
    *,
    mode: str,
    max_confirmed_usage_count: int | None,
    min_days_since_last_use: int | None,
    exclude_recently_used_days: int | None,
    now: datetime,
):
    """返回候选保留判定（True=保留）。hard filter 一律按 Shot 口径。

    - only_never_confirmed：shot confirmed==0（accepted legacy **不**被排除——
      它不等于 confirmed，由 UI 单独提示）；
    - exclude_high_frequency：shot confirmed <= max（必须显式提供阈值）；
    - min_days_since_last_use / exclude_recently_used_days：二者语义一致，
      取更严格（更大天数）；从未使用视为满足。
    """
    recent_days = max(
        [d for d in (min_days_since_last_use, exclude_recently_used_days) if d is not None],
        default=None,
    )

    def keep(f: UsageFeatures) -> bool:
        if mode == "only_never_confirmed" and f.shot_confirmed_usage_count != 0:
            return False
        if mode == "exclude_high_frequency" and max_confirmed_usage_count is not None:
            if f.shot_confirmed_usage_count > max_confirmed_usage_count:
                return False
        if recent_days is not None:
            days = f.days_since_last_confirmed_use(now)
            if days is not None and days < recent_days:
                return False
        return True

    return keep


def has_hard_filter(
    mode: str,
    max_confirmed_usage_count: int | None,
    min_days_since_last_use: int | None,
    exclude_recently_used_days: int | None,
) -> bool:
    return (
        mode in ("only_never_confirmed", "exclude_high_frequency")
        or min_days_since_last_use is not None
        or exclude_recently_used_days is not None
    )
