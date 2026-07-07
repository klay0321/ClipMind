"""PR-F Gate A：视觉嵌入 Provider 协议与确定性假实现（实验能力）。

冻结边界：模型候选 ≠ 产品确认；高相似度 ≠ 自动绑定；Top-1 ≠ 识别事实。
本模块不写任何产品归属，只产出向量。真实推理由 LocalVisualProvider
（apps/api，HTTP → embedder /visual-embeddings）承担；FakeVisualProvider
仅供单元测试 / API E2E / Playwright / CI 使用，不得用于真实验收，也不得
在 UI 中伪装成真实模型。
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Protocol

FAKE_VISUAL_DIMENSION = 768  # 与 local SigLIP 同维：持久化 Vector 列统一 768
FAKE_VISUAL_MODEL_ID = "fake-visual-deterministic-v1"


@dataclass(frozen=True)
class VisualProviderIdentity:
    provider: str            # fake | local
    model_id: str
    dimension: int
    device: str


class VisualEmbeddingProvider(Protocol):
    """图片 → L2 归一化向量。实现负责全部预处理（解码/缩放/归一化/batch）。

    失败必须抛异常并带明确原因（解码失败绝不产生零向量；缩略图失败不得
    误判为产品不匹配）。同图片同模型重复计算结果必须逐位稳定。
    """

    def embed_images(self, images: list[bytes]) -> list[list[float]]: ...

    def identity(self) -> VisualProviderIdentity: ...


class VisualProviderError(RuntimeError):
    """视觉 Provider 失败（含明确原因；调用方映射为 model_unavailable/4xx）。"""


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class FakeVisualProvider:
    """确定性假视觉嵌入：sha256(图片字节) 展开为固定维度向量后 L2 归一化。

    性质（供测试依赖）：同字节 → 同向量；不同字节 → 几乎必然不同向量；
    字节流中的 ``FAKE:<family-token>:`` 标记控制相似族——含同一 token 的
    图片向量相同（余弦 ≈ 1），不同 token ≈ 正交。标记可在字节流任意位置
    （E2E 可把 token 嵌在合法 PNG 的尾部，图片仍可被真实解码器解析），
    便于构造可预期的候选/混淆/未知场景。
    """

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        if not images:
            return []
        out: list[list[float]] = []
        for raw in images:
            if not raw:
                raise VisualProviderError("空图片字节")
            seed_src = raw
            marker = raw.find(b"FAKE:")
            if marker != -1:
                # FAKE:<token>: token 决定向量（模拟同产品多角度相似）
                parts = raw[marker:].split(b":", 2)
                if len(parts) >= 2 and parts[1]:
                    seed_src = b"FAKE:" + parts[1]
            digest = hashlib.sha256(seed_src).digest()
            vec = [(digest[i % 32] - 127.5) / 127.5 for i in range(FAKE_VISUAL_DIMENSION)]
            out.append(_l2_normalize(vec))
        return out

    def identity(self) -> VisualProviderIdentity:
        return VisualProviderIdentity(
            provider="fake",
            model_id=FAKE_VISUAL_MODEL_ID,
            dimension=FAKE_VISUAL_DIMENSION,
            device="cpu",
        )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """两个已 L2 归一化向量的余弦相似度（点积；防御性夹取 [-1,1]）。"""
    s = sum(x * y for x, y in zip(a, b, strict=True))
    return max(-1.0, min(1.0, s))


# ---------------------------------------------------------------------------
# VIS-AUTO：家族候选判定纯函数（状态机单一实现，API 实验与 worker 自动链共用）
# 状态机（PR-F 冻结）：insufficient_reference → unknown（top1 < min_score）
# → ambiguous（margin 不足；混淆对命中用更严 margin）→ candidate。
# 排序确定：score ↓ → family_id ↑。本函数纯计算，不触库、不写归属。
# ---------------------------------------------------------------------------

_AGG_TOP_K = 3
_PRIMARY_WEIGHT = 1.2
_ANGLE_WEIGHTS = {"package": 0.6, "detail": 0.8}
AGGREGATIONS = ("max", "top_k_mean", "weighted_top_k_mean")


@dataclass(frozen=True)
class RefVector:
    """一张参考图的向量与判定属性（装配层从 DB/缓存供给）。"""

    reference_id: int
    angle: str
    is_primary: bool
    vector: list[float]


@dataclass(frozen=True)
class FamilyRefs:
    """一个产品（family）的参考向量集（已通过资格与最小图数校验）。"""

    family_id: int
    family_code: str
    family_name: str
    refs: list[RefVector]
    reference_count: int          # 合格参考图总数（含未能取到向量的）
    source_levels: list[str]


@dataclass
class FamilyScore:
    family_id: int
    family_code: str
    family_name: str
    score: float
    best_reference_id: int | None
    matched_angles: list[str]
    reference_count: int
    embedded_reference_count: int
    aggregation: str
    source_levels: list[str]


@dataclass
class FamilyDecision:
    decision: str  # candidate | ambiguous | unknown | insufficient_reference
    candidates: list[FamilyScore]
    top1_score: float | None
    top2_score: float | None
    margin: float | None
    confusion_warning: dict | None


def aggregate_similarities(
    sims: list[tuple[float, RefVector]], aggregation: str
) -> float:
    """按聚合策略汇总一个 family 的（相似度, 参考图）对；sims 非空。"""
    values = sorted((s for s, _r in sims), reverse=True)
    if aggregation == "max":
        return values[0]
    if aggregation == "top_k_mean":
        top = values[:_AGG_TOP_K]
        return sum(top) / len(top)
    weighted = sorted(
        (
            s * (_PRIMARY_WEIGHT if r.is_primary else 1.0) * _ANGLE_WEIGHTS.get(r.angle, 1.0)
            for s, r in sims
        ),
        reverse=True,
    )
    top = weighted[:_AGG_TOP_K]
    return max(-1.0, min(1.0, sum(top) / len(top)))


def decide_family_candidates(
    query_vec: list[float],
    families: list[FamilyRefs],
    *,
    min_score: float,
    min_margin: float,
    confusion_margin: float,
    top_k: int = 5,
    aggregation: str = "top_k_mean",
    confusion_pairs: dict[tuple[int, int], dict] | None = None,
) -> FamilyDecision:
    """查询向量 × 各产品参考向量集 → 确定性候选判定。

    confusion_pairs：{(low_family_id, high_family_id): {pair 展示字段}}，
    由装配层预取（active 对）；命中 top1/top2 时用更严 margin 且回填 warning。
    """
    if aggregation not in AGGREGATIONS:
        raise ValueError(f"未知聚合策略: {aggregation}")
    if not families:
        return FamilyDecision("insufficient_reference", [], None, None, None, None)

    scored: list[FamilyScore] = []
    for fam in families:
        sims = [(cosine_similarity(query_vec, r.vector), r) for r in fam.refs]
        if not sims:
            continue  # 参考向量全部缺席 → 该产品缺席本轮（不判不匹配）
        score = aggregate_similarities(sims, aggregation)
        if math.isnan(score) or math.isinf(score):
            continue
        best_sim, best_ref = max(sims, key=lambda t: (t[0], -t[1].reference_id))
        matched = sorted({r.angle for sim, r in sims if sim >= best_sim - 0.05})
        scored.append(
            FamilyScore(
                family_id=fam.family_id,
                family_code=fam.family_code,
                family_name=fam.family_name,
                score=round(score, 6),
                best_reference_id=best_ref.reference_id,
                matched_angles=matched,
                reference_count=fam.reference_count,
                embedded_reference_count=len(sims),
                aggregation=aggregation,
                source_levels=fam.source_levels,
            )
        )
    if not scored:
        return FamilyDecision("insufficient_reference", [], None, None, None, None)

    scored.sort(key=lambda c: (-c.score, c.family_id))  # 确定性
    scored = scored[: max(1, top_k)]
    t1 = scored[0].score
    t2 = scored[1].score if len(scored) > 1 else None
    margin = (t1 - t2) if t2 is not None else None

    if t1 < min_score:
        return FamilyDecision("unknown", scored, t1, t2, margin, None)

    warning = None
    effective_margin = min_margin
    if t2 is not None:
        pair_key = tuple(sorted((scored[0].family_id, scored[1].family_id)))
        pair = (confusion_pairs or {}).get(pair_key)  # type: ignore[arg-type]
        if pair is not None:
            effective_margin = max(min_margin, confusion_margin)
            warning = {**pair, "strict_margin": effective_margin}
        if margin is not None and margin < effective_margin:
            return FamilyDecision("ambiguous", scored, t1, t2, margin, warning)
    return FamilyDecision("candidate", scored, t1, t2, margin, warning)
