"""Gate B：候选融合与综合评分（纯逻辑，可单测）。

融合方式：**Reciprocal Rank Fusion (RRF) + 在场通道加权均值** 的混合，再叠加有限加权与风险惩罚。

为什么混合：
- RRF 只看**名次**，对量纲不敏感、对缺失通道天然鲁棒——某候选未进向量召回时只是缺这一项
  RRF 贡献，**不会被判 0 分淘汰**（满足 Gate B 契约）；但纯 RRF 丢失分数量纲，会让“两个通道里
  都很弱但都在场”的候选压过“单通道强命中”的候选，违背直觉。
- 故再加一项**在场通道的加权平均原始分**（只对该候选实际有分的通道求平均，缺失通道既不计入
  分母也不判 0），保留量纲信息。
- ``base = RRF_WEIGHT * rrf_norm + SIGNAL_WEIGHT * signal_avg``，两者都归一到 [0,1]。

评分区间约定（对外可读，绝不制造虚假精度）：
- ``semantic_score`` / ``lexical_score`` / ``tag_score`` / ``product_score``：各自 [0,1]，缺失为 None；
- ``final_score``：[0,1]，= 归一化 RRF + 精确产品加权 + 审核加权 + 质量加权 − 风险惩罚；
- 对外展示按整数百分比或一位小数（由 API 层负责），本层只产出 [0,1] 浮点。

稳定排序 tie-breaker（§9.10）：final_score↓, quality↓, 审核（human 优先）, created_at↑, shot_id↑。
全序确定 → 分页切片不重复不丢失。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# RRF 常数（越大越弱化头部名次差异；60 为常用经验值）
RRF_K = 60

# base 中 RRF 与加权均值的占比（和为 1）
RRF_WEIGHT = 0.5
SIGNAL_WEIGHT = 0.5

# 各通道权重（产品精确性最高，向量次之）；同时用于 RRF 与加权均值
CHANNEL_WEIGHTS: dict[str, float] = {
    "product": 1.1,
    "semantic": 1.0,
    "lexical": 0.85,
    "tag": 0.8,
}

# 有限加权 / 惩罚上限
EXACT_PRODUCT_BONUS = 0.12   # 精确 SKU/型号命中
REVIEW_BONUS_MAX = 0.08      # confirmed/modified
QUALITY_WEIGHT = 0.05        # 质量满足贡献
RISK_PENALTY_MAX = 0.20      # 含未排除风险标签（软惩罚；硬排除在 SQL 过滤）


@dataclass
class Candidate:
    """单个候选镜头的融合输入与评分输出。"""

    shot_id: int
    # 各通道原始分（[0,1]，缺失为 None；None 不参与该通道排名，也不被判 0 分）
    semantic_score: float | None = None
    lexical_score: float | None = None
    tag_score: float | None = None
    product_score: float | None = None
    # 加权/惩罚信号
    quality_score: float = 0.0
    exact_product: bool = False
    is_human_effective: bool = False  # confirmed/modified 且未 stale
    review_status: str | None = None
    has_unexcluded_risk: bool = False
    embedding_degraded: bool = False
    created_at: datetime | None = None
    # 输出
    ranks: dict[str, int] = field(default_factory=dict)
    rrf_raw: float = 0.0
    review_bonus: float = 0.0
    risk_penalty: float = 0.0
    final_score: float = 0.0

    def channel_score(self, channel: str) -> float | None:
        return getattr(self, f"{channel}_score")


_CHANNELS = ("product", "semantic", "lexical", "tag")


def _assign_ranks(candidates: list[Candidate], channel: str) -> None:
    """对某通道有分的候选按分数降序赋 1-based 名次（同分用 shot_id 升序确定名次）。"""
    scored = [c for c in candidates if c.channel_score(channel) is not None]
    scored.sort(key=lambda c: (-(c.channel_score(channel) or 0.0), c.shot_id))
    for i, c in enumerate(scored, start=1):
        c.ranks[channel] = i


def _review_rank(c: Candidate) -> int:
    return 0 if c.is_human_effective else 1


def score_candidates(
    candidates: list[Candidate],
    *,
    active_channels: list[str],
    weights: dict[str, float] | None = None,
) -> list[Candidate]:
    """计算 final_score 并返回**稳定全序**排序后的候选列表。

    ``active_channels`` 控制参与 RRF 的通道（如 lexical 模式只含 ["lexical"]）。
    """
    w = {**CHANNEL_WEIGHTS, **(weights or {})}
    active = [ch for ch in _CHANNELS if ch in active_channels]

    for ch in active:
        _assign_ranks(candidates, ch)

    # 理论最大 RRF（在所有 active 通道均排第 1）→ 用于归一到 [0,1]
    rrf_max = sum(w[ch] / (RRF_K + 1) for ch in active) or 1.0

    for c in candidates:
        rrf = 0.0
        signal_sum = 0.0
        signal_wsum = 0.0
        for ch in active:
            rank = c.ranks.get(ch)
            if rank is not None:
                rrf += w[ch] / (RRF_K + rank)
            score = c.channel_score(ch)
            if score is not None:  # 仅在场通道计入加权均值（缺失不判 0，也不入分母）
                signal_sum += w[ch] * max(0.0, min(1.0, score))
                signal_wsum += w[ch]
        c.rrf_raw = rrf
        rrf_norm = rrf / rrf_max  # [0,1]
        signal_avg = (signal_sum / signal_wsum) if signal_wsum > 0 else 0.0  # [0,1]
        base = RRF_WEIGHT * rrf_norm + SIGNAL_WEIGHT * signal_avg

        c.review_bonus = REVIEW_BONUS_MAX if c.is_human_effective else 0.0
        c.risk_penalty = RISK_PENALTY_MAX if c.has_unexcluded_risk else 0.0
        exact = EXACT_PRODUCT_BONUS if c.exact_product else 0.0
        quality = QUALITY_WEIGHT * max(0.0, min(1.0, c.quality_score))

        final = base + exact + c.review_bonus + quality - c.risk_penalty
        c.final_score = max(0.0, min(1.0, final))

    return order_candidates(candidates)


def order_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """稳定全序排序（tie-breaker：final↓ quality↓ human优先 created_at↑ shot_id↑）。"""

    def key(c: Candidate):
        ts = c.created_at.timestamp() if c.created_at is not None else 0.0
        return (-c.final_score, -c.quality_score, _review_rank(c), ts, c.shot_id)

    return sorted(candidates, key=key)


def paginate(items: list, page: int, page_size: int) -> list:
    """对已全序排序的候选做稳定分页切片（越界返回空）。"""
    if page < 1:
        page = 1
    start = (page - 1) * page_size
    return items[start : start + page_size]
