"""PR-F：视觉候选离线 Benchmark（实验；同步小样本）。

防泄漏（.local/pr-f-a/benchmark-design.md 冻结）：
- 留一法：query 为参考图时，按**内容身份**（sha256 相同视为同一内容，含
  缩略图/副本）把该内容全部参考图从 gallery 临时剔除后再检索；
- gallery 只由参考图构成，Shot 关键帧只作 query（天然无跨集泄漏）；
- Ground Truth 由请求方（人工）提供；目录名/文件名绝不自动当 GT；
- unknown 负样本真实进入评测；样本过少时如实输出 per-family 计数。

输出：整体 + 分组指标 + coverage-accuracy / score / margin 分布，绝不只报
一个 Top-1；不声称统计显著或生产可用。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from clipmind_shared.ai.visual import (
    VisualEmbeddingProvider,
    VisualProviderError,
    cosine_similarity,
)
from clipmind_shared.models import ProductReferenceAsset, Shot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services import files
from app.services.visual_candidate_service import _aggregate
from app.services.visual_reference_index import (
    embed_references,
    load_family_reference_sets,
)


@dataclass
class BenchmarkSample:
    kind: str                      # reference | shot | unknown_reference | unknown_shot
    reference_id: int | None
    shot_id: int | None
    ground_truth_family_id: int | None
    is_unknown: bool
    sample_type: str = ""
    source: str = ""


@dataclass
class SampleOutcome:
    sample_index: int
    decision: str
    predicted_family_id: int | None
    correct_top1: bool | None      # unknown 样本为 None
    rank_of_truth: int | None
    top1_score: float | None
    margin: float | None
    skipped_reason: str | None = None


@dataclass
class BenchmarkReport:
    total_samples: int
    evaluated: int
    skipped: int
    product_samples: int
    unknown_samples: int
    family_count: int
    metrics: dict = field(default_factory=dict)
    per_family: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)
    confusion_matrix: dict = field(default_factory=dict)
    curves: dict = field(default_factory=dict)
    data_gaps: list = field(default_factory=list)
    outcomes: list = field(default_factory=list)


async def run_benchmark(
    db: AsyncSession,
    *,
    samples: list[BenchmarkSample],
    provider: VisualEmbeddingProvider,
    settings: Settings,
    aggregation: str = "top_k_mean",
) -> BenchmarkReport:
    sets = await load_family_reference_sets(
        db, min_references=settings.visual_min_references
    )
    eligible = [s for s in sets if s.eligible]
    all_refs = [r for s in eligible for r in s.references]
    ref_rows = (
        await db.execute(
            select(
                ProductReferenceAsset.id,
                ProductReferenceAsset.sha256,
                ProductReferenceAsset.image_path,
            ).where(ProductReferenceAsset.id.in_([r.reference_id for r in all_refs] or [0]))
        )
    ).all()
    sha_by_ref = {rid: (sha or "") for rid, sha, _p in ref_rows}
    path_by_ref = {rid: p for rid, _s, p in ref_rows}
    ref_vecs = await embed_references(all_refs, provider=provider, sha_by_ref=sha_by_ref)

    ms, mm = settings.visual_min_score, settings.visual_min_margin

    def classify(query_vec, exclude_content_sha: str | None):
        """返回 (decision, ranked[(family_id, score)])——留一法按内容剔除。"""
        scored = []
        for s in eligible:
            sims = [
                (cosine_similarity(query_vec, ref_vecs[r.reference_id]), r)
                for r in s.references
                if r.reference_id in ref_vecs
                and not (
                    exclude_content_sha
                    and sha_by_ref.get(r.reference_id, "") == exclude_content_sha
                )
            ]
            if not sims:
                continue
            scored.append((s.family_id, _aggregate(sims, aggregation)))
        scored.sort(key=lambda t: (-t[1], t[0]))
        if not scored:
            return "insufficient_reference", []
        t1 = scored[0][1]
        t2 = scored[1][1] if len(scored) > 1 else None
        if t1 < ms:
            return "unknown", scored
        if t2 is not None and (t1 - t2) < mm:
            return "ambiguous", scored
        return "candidate", scored

    outcomes: list[SampleOutcome] = []
    for idx, sample in enumerate(samples):
        raw: bytes | None = None
        exclude_sha: str | None = None
        skipped = None
        if sample.reference_id is not None:
            path = path_by_ref.get(sample.reference_id)
            if path is None:
                row = (
                    await db.execute(
                        select(
                            ProductReferenceAsset.image_path, ProductReferenceAsset.sha256
                        ).where(ProductReferenceAsset.id == sample.reference_id)
                    )
                ).first()
                if row:
                    path, exclude_sha = row[0], row[1] or None
            else:
                exclude_sha = sha_by_ref.get(sample.reference_id) or None
            if path is None:
                skipped = "reference_not_found"
            else:
                try:
                    with open(files.resolve_derived(path), "rb") as f:  # noqa: PTH123
                        raw = f.read()
                except Exception:  # noqa: BLE001
                    skipped = "reference_unreadable"
            if raw is not None and not exclude_sha and not sample.is_unknown:
                skipped = "no_content_hash_for_leave_one_out"  # 防自匹配：无法剔除则跳过
        elif sample.shot_id is not None:
            shot = (
                await db.execute(select(Shot).where(Shot.id == sample.shot_id))
            ).scalar_one_or_none()
            if shot is None or not shot.keyframe_path:
                skipped = "shot_keyframe_missing"
            else:
                try:
                    with open(files.resolve_derived(shot.keyframe_path), "rb") as f:  # noqa: PTH123
                        raw = f.read()
                except Exception:  # noqa: BLE001
                    skipped = "shot_keyframe_unreadable"
        else:
            skipped = "no_query_source"

        if skipped:
            outcomes.append(SampleOutcome(idx, "skipped", None, None, None, None, None,
                                          skipped_reason=skipped))
            continue
        try:
            qvec = provider.embed_images([raw])[0]
        except VisualProviderError as exc:
            outcomes.append(SampleOutcome(idx, "model_unavailable", None, None, None,
                                          None, None, skipped_reason=str(exc)))
            continue
        decision, ranked = classify(qvec, exclude_sha)
        pred = ranked[0][0] if ranked else None
        t1 = ranked[0][1] if ranked else None
        margin = (ranked[0][1] - ranked[1][1]) if len(ranked) > 1 else None
        rank_of_truth = None
        correct = None
        if not sample.is_unknown and sample.ground_truth_family_id is not None:
            for rk, (fid, _sc) in enumerate(ranked, start=1):
                if fid == sample.ground_truth_family_id:
                    rank_of_truth = rk
                    break
            correct = bool(ranked) and ranked[0][0] == sample.ground_truth_family_id
        outcomes.append(
            SampleOutcome(idx, decision, pred, correct, rank_of_truth, t1, margin)
        )

    # ---------------- 指标汇总 ----------------
    prod = [
        (s, o) for s, o in zip(samples, outcomes, strict=True)
        if not s.is_unknown and o.decision not in ("skipped", "model_unavailable")
    ]
    unk = [
        (s, o) for s, o in zip(samples, outcomes, strict=True)
        if s.is_unknown and o.decision not in ("skipped", "model_unavailable")
    ]
    evaluated = len(prod) + len(unk)
    metrics: dict = {}
    if prod:
        metrics["top1_accuracy"] = sum(1 for _s, o in prod if o.correct_top1) / len(prod)
        metrics["top3_recall"] = sum(
            1 for _s, o in prod if o.rank_of_truth is not None and o.rank_of_truth <= 3
        ) / len(prod)
        metrics["mrr"] = sum(
            (1.0 / o.rank_of_truth) for _s, o in prod if o.rank_of_truth
        ) / len(prod)
        accepted = [o for _s, o in prod if o.decision == "candidate"]
        metrics["coverage"] = len(accepted) / len(prod)
        metrics["accepted_candidate_accuracy"] = (
            sum(1 for o in accepted if o.correct_top1) / len(accepted) if accepted else None
        )
        metrics["ambiguous_rate"] = sum(
            1 for _s, o in prod if o.decision == "ambiguous"
        ) / len(prod)
    if unk:
        rejected = [o for _s, o in unk if o.decision in ("unknown", "ambiguous")]
        metrics["unknown_rejection_recall"] = len(rejected) / len(unk)
    all_rejected_as_unknown = [
        (s, o) for s, o in prod + unk if o.decision == "unknown"
    ]
    if all_rejected_as_unknown:
        metrics["unknown_rejection_precision"] = sum(
            1 for s, _o in all_rejected_as_unknown if s.is_unknown
        ) / len(all_rejected_as_unknown)

    per_family: dict[int, dict] = {}
    by_truth: dict[int, list[SampleOutcome]] = defaultdict(list)
    for s, o in prod:
        by_truth[s.ground_truth_family_id].append(o)
    for fid, os_ in sorted(by_truth.items()):
        per_family[fid] = {
            "samples": len(os_),
            "recall_top1": sum(1 for o in os_ if o.correct_top1) / len(os_),
        }
    if per_family:
        metrics["macro_recall"] = sum(v["recall_top1"] for v in per_family.values()) / len(
            per_family
        )

    confusion: dict[str, int] = defaultdict(int)
    for s, o in prod:
        if o.predicted_family_id is not None:
            confusion[f"{s.ground_truth_family_id}->{o.predicted_family_id}"] += 1

    # 分组（query source / reference bucket）
    groups: dict[str, dict] = {"by_source": {}, "by_reference_bucket": {}}
    by_kind: dict[str, list] = defaultdict(list)
    for s, o in prod:
        by_kind[s.kind].append(o)
    for kind, os_ in by_kind.items():
        groups["by_source"][kind] = {
            "samples": len(os_),
            "top1_accuracy": sum(1 for o in os_ if o.correct_top1) / len(os_),
        }
    ref_count_by_family = {s.family_id: len(s.references) for s in eligible}
    bucket_stats: dict[str, list] = defaultdict(list)
    for s, o in prod:
        n = ref_count_by_family.get(s.ground_truth_family_id, 0)
        bucket = "1-2" if n <= 2 else ("3-5" if n <= 5 else "6+")
        bucket_stats[bucket].append(o)
    for bucket, os_ in bucket_stats.items():
        groups["by_reference_bucket"][bucket] = {
            "samples": len(os_),
            "top1_accuracy": sum(1 for o in os_ if o.correct_top1) / len(os_),
        }

    # 曲线：coverage-accuracy（min_score 扫描）、score/margin 分布
    curves: dict = {"coverage_accuracy": [], "score_distribution": [],
                    "margin_distribution": []}
    scores_prod = [o.top1_score for _s, o in prod if o.top1_score is not None]
    for step in range(0, 21):
        thr = step / 20.0
        covered = [
            o for _s, o in prod if o.top1_score is not None and o.top1_score >= thr
        ]
        curves["coverage_accuracy"].append({
            "min_score": thr,
            "coverage": len(covered) / len(prod) if prod else 0.0,
            "accuracy": (
                sum(1 for o in covered if o.correct_top1) / len(covered)
                if covered else None
            ),
        })
    curves["score_distribution"] = sorted(round(v, 4) for v in scores_prod)
    curves["margin_distribution"] = sorted(
        round(o.margin, 4) for _s, o in prod if o.margin is not None
    )

    gaps: list[str] = []
    if len(per_family) < 3:
        gaps.append(f"参与评测的产品仅 {len(per_family)} 个，不足以支撑跨产品区分度结论")
    small = [fid for fid, v in per_family.items() if v["samples"] < 5]
    if small:
        gaps.append(f"{len(small)} 个产品样本数 <5，per-family 指标不具统计意义")
    if not unk:
        gaps.append("缺少 unknown 负样本，拒识指标缺席")

    return BenchmarkReport(
        total_samples=len(samples),
        evaluated=evaluated,
        skipped=sum(1 for o in outcomes if o.decision == "skipped"),
        product_samples=len(prod),
        unknown_samples=len(unk),
        family_count=len(eligible),
        metrics=metrics,
        per_family=per_family,
        groups=groups,
        confusion_matrix=dict(confusion),
        curves=curves,
        data_gaps=gaps,
        outcomes=[o.__dict__ for o in outcomes],
    )
