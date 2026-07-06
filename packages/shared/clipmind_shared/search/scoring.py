"""Gate B：候选融合与综合评分（纯逻辑，可单测）。

融合方式：**Reciprocal Rank Fusion (RRF) + 批内归一后的最强信号** 的混合，再叠加有限加权与风险提示。

为什么混合：
- RRF 只看**名次**，对量纲不敏感、对缺失通道天然鲁棒——某候选未进向量召回时只是缺这一项
  RRF 贡献，**不会被判 0 分淘汰**（满足 Gate B 契约）；但纯 RRF 丢失分数量纲，会让“两个通道里
  都很弱但都在场”的候选压过“单通道强命中”的候选，违背直觉。
- 信号项取**批内归一后的最强通道分**（每通道分数先除以本批该通道最大分再取 max）。
  不用跨通道均值：词法 ts_rank（~0.03 量级）与语义余弦（~0.9 量级）量纲不可比，
  均值会让“同时被词法召回”的强语义命中被稀释——命中越多通道分反而越低（真实缺陷，
  已在真实库复现）。归一修量纲，取最强信号保留“单通道强命中”直觉；多通道共识由 RRF 项奖励。
- ``base = RRF_WEIGHT * rrf_norm + SIGNAL_WEIGHT * signal_strength``，两者都归一到 [0,1]。

风险定位：风险标签是“使用该素材时的合规提示”，不是“该素材与查询的相关性”——搜索
“TikTok 镜头”时所有真含 TikTok 的镜头都带“第三方 logo 风险”，若重罚会出现“搜什么就
搜不到什么”（真实库复现的事故）。故 ``RISK_PENALTY_MAX`` 仅保留同分级微调（tie-break 量级），
风险的正式表达是 ``risk_warnings`` 展示 + ``exclude_risks`` 显式硬过滤。

评分区间约定（对外可读，绝不制造虚假精度）：
- ``semantic_score`` / ``lexical_score`` / ``tag_score`` / ``product_score``：各自 [0,1]，缺失为 None；
- ``final_score``：[0,1]，= 归一化 RRF + 精确产品加权 + 审核加权 + 质量加权 − 风险微调；
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

# base 缩放：给加权项留出余量，避免“通道第一名 + 任意加成”一起撞 1.0 上限
# 导致加成失效（clamp 天花板会吞掉 review/exact 加成的排序作用）。
BASE_SCALE = 0.9

# 仅词法做批内 max 归一：ts_rank 无界且量级（~0.03）与语义余弦（~0.9）不可比；
# 语义/标签/产品分数本就是 [0,1] 可比语义，保留原始值（弱就是弱，不虚增）。
_NORMALIZE_CHANNELS = ("lexical",)

# 有限加权 / 惩罚上限
EXACT_PRODUCT_BONUS = 0.12   # 精确 SKU/型号命中
REVIEW_BONUS_MAX = 0.08      # confirmed/modified
QUALITY_WEIGHT = 0.05        # 质量满足贡献
# 风险仅作同分级微调：相关性归相关性，合规提示归 risk_warnings/exclude_risks。
# （曾为 0.20：语义分差常 <0.05，重罚会让“搜 TikTok 找不到含 TikTok 的镜头”）
RISK_PENALTY_MAX = 0.02


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

    # 词法批内最大分（归一分母；其他通道用原始 [0,1] 分，弱就是弱不虚增）
    channel_max: dict[str, float] = {}
    for ch in _NORMALIZE_CHANNELS:
        if ch not in active:
            continue
        best = 0.0
        for c in candidates:
            s = c.channel_score(ch)
            if s is not None and s > best:
                best = s
        channel_max[ch] = best

    for c in candidates:
        rrf = 0.0
        signal_strength = 0.0
        for ch in active:
            rank = c.ranks.get(ch)
            if rank is not None:
                rrf += w[ch] / (RRF_K + rank)
            score = c.channel_score(ch)
            if score is None:
                continue
            if ch in _NORMALIZE_CHANNELS:
                mx = channel_max.get(ch, 0.0)
                score = (score / mx) if mx > 0 else 0.0
            # 最强信号：不做跨通道均值——均值会让“同时被低量纲通道召回”的
            # 强命中被稀释（命中越多通道分反而越低）；多通道共识由 RRF 项奖励。
            norm = max(0.0, min(1.0, score))
            if norm > signal_strength:
                signal_strength = norm
        c.rrf_raw = rrf
        rrf_norm = rrf / rrf_max  # [0,1]
        base = RRF_WEIGHT * rrf_norm + SIGNAL_WEIGHT * signal_strength

        c.review_bonus = REVIEW_BONUS_MAX if c.is_human_effective else 0.0
        c.risk_penalty = RISK_PENALTY_MAX if c.has_unexcluded_risk else 0.0
        exact = EXACT_PRODUCT_BONUS if c.exact_product else 0.0
        quality = QUALITY_WEIGHT * max(0.0, min(1.0, c.quality_score))

        final = BASE_SCALE * base + exact + c.review_bonus + quality - c.risk_penalty
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
