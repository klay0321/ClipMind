"""PR-F：产品视觉候选服务（实验；docs/VISUAL_RECOGNITION.md）。

冻结边界：候选 ≠ 确认；本服务**只读**产品目录与参考图，绝不写
AssetProduct / Shot 产品归属 / Onboarding / FinalVideoUsage / CatalogRevision。

判定状态机（.local/pr-f-a/open-set-design.md）：
model_unavailable → insufficient_reference → unknown（top1 < min_score）
→ ambiguous（margin 不足；confusion pair 命中用更严 margin 且默认不判
confident）→ candidate。排序确定：score ↓ → family_id ↑。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from clipmind_shared.ai.visual import (
    VisualEmbeddingProvider,
    VisualProviderError,
    cosine_similarity,
)
from clipmind_shared.models import ProductConfusionPair, ProductReferenceAsset
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services.visual_reference_index import (
    FamilyReferenceSet,
    embed_references,
    load_family_reference_sets,
)

AGGREGATIONS = ("max", "top_k_mean", "weighted_top_k_mean")
_AGG_TOP_K = 3
# 角度/主图实验系数（只按维度配置，绝不按真实产品名称硬编码）
_PRIMARY_WEIGHT = 1.2
_ANGLE_WEIGHTS = {"package": 0.6, "detail": 0.8}


@dataclass
class FamilyCandidate:
    target_level: str
    target_id: int
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
class CandidateResult:
    decision: str  # candidate | ambiguous | unknown | insufficient_reference | model_unavailable
    candidates: list[FamilyCandidate]
    top1_score: float | None
    top2_score: float | None
    margin: float | None
    thresholds: dict
    aggregation: str
    confusion_warning: dict | None
    unavailable_reason: str | None = None


def _aggregate(
    sims: list[tuple[float, object]], aggregation: str
) -> float:
    """sims: [(similarity, EligibleReference)]，已非空。"""
    values = sorted((s for s, _r in sims), reverse=True)
    if aggregation == "max":
        return values[0]
    if aggregation == "top_k_mean":
        top = values[:_AGG_TOP_K]
        return sum(top) / len(top)
    # weighted_top_k_mean：按 primary/angle 系数加权后取 top-k 均值
    weighted = sorted(
        (
            s * (_PRIMARY_WEIGHT if r.is_primary else 1.0) * _ANGLE_WEIGHTS.get(r.angle, 1.0)
            for s, r in sims
        ),
        reverse=True,
    )
    top = weighted[:_AGG_TOP_K]
    # 夹回 [-1,1]（加权可能溢出 1）
    return max(-1.0, min(1.0, sum(top) / len(top)))


async def _load_confusion_pair(
    db: AsyncSession, fid_a: int, fid_b: int
) -> ProductConfusionPair | None:
    lo, hi = sorted((fid_a, fid_b))
    return (
        await db.execute(
            select(ProductConfusionPair).where(
                ProductConfusionPair.target_level == "family",
                ProductConfusionPair.left_target_id == lo,
                ProductConfusionPair.right_target_id == hi,
                ProductConfusionPair.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def compute_candidates(
    db: AsyncSession,
    *,
    query_image: bytes,
    provider: VisualEmbeddingProvider,
    settings: Settings,
    top_k: int | None = None,
    min_score: float | None = None,
    min_margin: float | None = None,
    aggregation: str = "top_k_mean",
) -> CandidateResult:
    """单张查询图 → Family 级候选（只读；确定性排序）。"""
    if aggregation not in AGGREGATIONS:
        raise ValueError(f"未知聚合策略: {aggregation}")
    k = top_k or settings.visual_top_k
    ms = settings.visual_min_score if min_score is None else min_score
    mm = settings.visual_min_margin if min_margin is None else min_margin
    thresholds = {
        "min_score": ms,
        "min_margin": mm,
        "confusion_margin": settings.visual_confusion_margin,
        "min_references": settings.visual_min_references,
        "calibrated": False,  # 实验性：未经真实 Benchmark 校准
    }

    def _res(decision: str, *, cands=None, t1=None, t2=None, margin=None,
             warning=None, reason=None) -> CandidateResult:
        return CandidateResult(
            decision=decision, candidates=cands or [], top1_score=t1, top2_score=t2,
            margin=margin, thresholds=thresholds, aggregation=aggregation,
            confusion_warning=warning, unavailable_reason=reason,
        )

    sets = await load_family_reference_sets(
        db, min_references=settings.visual_min_references
    )
    eligible: list[FamilyReferenceSet] = [s for s in sets if s.eligible]
    if not eligible:
        return _res("insufficient_reference", reason="没有任何产品达到最小合格参考图数")

    all_refs = [r for s in eligible for r in s.references]
    sha_by_ref = {
        rid: sha or ""
        for rid, sha in (
            await db.execute(
                select(ProductReferenceAsset.id, ProductReferenceAsset.sha256).where(
                    ProductReferenceAsset.id.in_([r.reference_id for r in all_refs])
                )
            )
        ).all()
    }
    try:
        qvec = provider.embed_images([query_image])[0]
        ref_vecs = await embed_references(
            all_refs, provider=provider, sha_by_ref=sha_by_ref
        )
    except VisualProviderError as exc:
        return _res("model_unavailable", reason=str(exc))

    cands: list[FamilyCandidate] = []
    for s in eligible:
        sims = [
            (cosine_similarity(qvec, ref_vecs[r.reference_id]), r)
            for r in s.references
            if r.reference_id in ref_vecs
        ]
        if not sims:
            continue  # 全部图读取失败 → 该产品缺席（不判不匹配）
        score = _aggregate(sims, aggregation)
        if math.isnan(score) or math.isinf(score):
            continue
        best_sim, best_ref = max(sims, key=lambda t: (t[0], -t[1].reference_id))
        matched = sorted({r.angle for sim, r in sims if sim >= best_sim - 0.05})
        cands.append(
            FamilyCandidate(
                target_level="family",
                target_id=s.family_id,
                family_code=s.family_code,
                family_name=s.family_name,
                score=round(score, 6),
                best_reference_id=best_ref.reference_id,
                matched_angles=matched,
                reference_count=len(s.references),
                embedded_reference_count=len(sims),
                aggregation=aggregation,
                source_levels=sorted({r.source_level for r in s.references}),
            )
        )
    if not cands:
        return _res("model_unavailable", reason="参考图特征全部不可用（文件缺失或读取失败）")

    cands.sort(key=lambda c: (-c.score, c.target_id))  # 确定性
    cands = cands[: max(1, k)]
    t1 = cands[0].score
    t2 = cands[1].score if len(cands) > 1 else None
    margin = (t1 - t2) if t2 is not None else None

    if t1 < ms:
        return _res("unknown", cands=cands, t1=t1, t2=t2, margin=margin)

    warning = None
    effective_margin = mm
    if t2 is not None:
        pair = await _load_confusion_pair(db, cands[0].target_id, cands[1].target_id)
        if pair is not None:
            effective_margin = max(mm, settings.visual_confusion_margin)
            warning = {
                "pair_id": pair.id,
                "severity": pair.severity,
                "reason": pair.reason,
                "distinguishing_features": pair.distinguishing_features or [],
                "strict_margin": effective_margin,
            }
        if margin is not None and margin < effective_margin:
            return _res("ambiguous", cands=cands, t1=t1, t2=t2, margin=margin,
                        warning=warning)
    return _res("candidate", cands=cands, t1=t1, t2=t2, margin=margin, warning=warning)
