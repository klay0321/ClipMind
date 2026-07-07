"""VIS-AUTO：视觉嵌入索引与自动候选核心（sync，worker 内运行）。

安全边界：只读 data 卷派生图（海报/关键帧/参考图，经 data 根包含校验），
绝不触碰源目录；只写 visual_media_embedding / visual_product_candidate，
绝不写 product_media_link（确认永远走人工通道）。

资格规则与 apps/api/app/services/visual_reference_index.py 的冻结规则一致
（ACTIVE + approved + 质量排除 + 最小合格图数 + 代表角度）；此处为 sync
装配版，从持久化嵌入行取向量而非现场推理。
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass

from clipmind_shared.ai.visual import (
    FakeVisualProvider,
    FamilyRefs,
    RefVector,
    VisualEmbeddingProvider,
    VisualProviderError,
    decide_family_candidates,
)
from clipmind_shared.ai.visual_http import LocalVisualProvider
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    ProductConfusionPair,
    ProductFamily,
    ProductOnboardingReview,
    ProductReferenceAsset,
    ProductSKU,
    ProductVariant,
    Shot,
    VisualMediaEmbedding,
    VisualProductCandidate,
)
from clipmind_shared.models.enums import REFERENCE_MEDIA_TYPES, CatalogStatus, ShotStatus
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipmind_worker.config import WorkerSettings

logger = logging.getLogger(__name__)

# 与 API 侧 visual_reference_index 冻结一致
EXCLUDED_QUALITY = frozenset(
    {"wrong_product", "duplicate", "blurred", "occluded", "low_resolution"}
)
NON_REPRESENTATIVE_ANGLES = frozenset({"detail", "package"})


def build_visual_provider(settings: WorkerSettings) -> VisualEmbeddingProvider:
    mode = (settings.visual_embedding_provider or "fake").strip().lower()
    if mode == "fake":
        return FakeVisualProvider()
    if mode == "local":
        return LocalVisualProvider(
            base_url=settings.visual_embedder_url,
            model_id=settings.visual_model_id,
            device=settings.visual_device,
            batch_size=settings.visual_batch_size,
        )
    raise VisualProviderError(f"未知 VISUAL_EMBEDDING_PROVIDER: {mode}")


@dataclass
class TargetImage:
    rel_path: str
    abs_path: str


def resolve_target_image(
    session: Session, settings: WorkerSettings, target_type: str, target_id: int
) -> TargetImage | None:
    """目标 → data 卷内图片（含包含校验）；无图返回 None（不视为错误）。"""
    rel: str | None = None
    if target_type == "asset":
        asset = session.get(Asset, target_id)
        rel = asset.poster_path if asset is not None else None
    elif target_type == "shot":
        shot = session.get(Shot, target_id)
        rel = shot.keyframe_path if shot is not None else None
    elif target_type == "reference":
        ref = session.get(ProductReferenceAsset, target_id)
        rel = ref.image_path if ref is not None else None
    else:
        raise ValueError(f"未知视觉目标类型: {target_type}")
    if not rel:
        return None
    root_real = os.path.realpath(settings.data_dir)
    abs_path = os.path.realpath(os.path.join(root_real, *rel.split("/")))
    if abs_path != root_real and not abs_path.startswith(root_real + os.sep):
        logger.warning("视觉目标路径越界，拒绝读取（target=%s:%s）", target_type, target_id)
        return None
    if not os.path.isfile(abs_path):
        return None
    return TargetImage(rel_path=rel, abs_path=abs_path)


def upsert_embedding(
    session: Session,
    settings: WorkerSettings,
    provider: VisualEmbeddingProvider,
    target_type: str,
    target_id: int,
) -> tuple[VisualMediaEmbedding | None, str]:
    """计算/复用一条视觉嵌入。返回 (行, 状态)；状态 ∈ ok|cached|no_image|failed。"""
    ident = provider.identity()
    row = session.execute(
        select(VisualMediaEmbedding).where(
            VisualMediaEmbedding.target_type == target_type,
            VisualMediaEmbedding.target_id == target_id,
            VisualMediaEmbedding.provider == ident.provider,
            VisualMediaEmbedding.model_id == ident.model_id,
        )
    ).scalar_one_or_none()

    img = resolve_target_image(session, settings, target_type, target_id)
    if img is None:
        return row, "no_image"
    with open(img.abs_path, "rb") as f:
        raw = f.read()
    sha = hashlib.sha256(raw).hexdigest()

    if row is not None and row.status == "completed" and row.source_sha256 == sha:
        return row, "cached"  # 内容与模型都没变，不重推理

    if row is None:
        row = VisualMediaEmbedding(
            target_type=target_type, target_id=target_id,
            provider=ident.provider, model_id=ident.model_id,
        )
        session.add(row)
    row.source_path = img.rel_path
    row.source_sha256 = sha
    try:
        vec = provider.embed_images([raw])[0]
    except VisualProviderError as exc:
        row.status = "failed"
        row.embedding = None
        row.error_message = str(exc)[:2000]
        # 内容变了但推理失败 → 候选水位清空，恢复后 sweep 会重算
        row.candidates_ref_revision = None
        session.flush()
        return row, "failed"
    row.embedding = vec
    row.dimension = len(vec)
    row.status = "completed"
    row.error_message = None
    # 新内容 → 旧候选决策作废（水位清空；本轮随后就地重算）
    row.candidates_ref_revision = None
    session.flush()
    return row, "ok"


def load_family_ref_vectors(
    session: Session, settings: WorkerSettings, provider: VisualEmbeddingProvider
) -> tuple[list[FamilyRefs], str]:
    """从持久化嵌入行装配各产品参考向量集 + 当前参考集摘要（ref_revision）。

    摘要按（合格参考图, 其向量是否已算得）计算：素材候选先于参考向量算完
    （竞态）时，参考向量补齐会使 revision 变化 → 素材行水位落后 → sweep
    自动重算——否则先算完的素材将永远停在 insufficient 的旧决策上。
    """
    ident = provider.identity()
    fam_rows = session.execute(
        select(ProductFamily, ProductOnboardingReview.status)
        .join(
            ProductOnboardingReview,
            ProductOnboardingReview.family_id == ProductFamily.id,
            isouter=True,
        )
        .where(
            ProductFamily.status == CatalogStatus.ACTIVE,
            ProductFamily.merged_into_id.is_(None),
            ProductFamily.archived_at.is_(None),
        )
        .order_by(ProductFamily.id)
    ).all()
    approved = {f.id: f for f, ob in fam_rows if ob == "approved"}
    if not approved:
        return [], _revision_digest([])

    var_map = {
        vid: fid
        for vid, fid in session.execute(
            select(ProductVariant.id, ProductVariant.family_id).where(
                ProductVariant.family_id.in_(list(approved))
            )
        ).all()
    }
    sku_map = {
        sid: fid
        for sid, fid in session.execute(
            select(ProductSKU.id, ProductSKU.family_id).where(
                ProductSKU.family_id.in_(list(approved))
            )
        ).all()
    }
    refs = list(
        session.execute(
            select(ProductReferenceAsset)
            .where(
                ProductReferenceAsset.state == "active",
                ProductReferenceAsset.archived_at.is_(None),
                ProductReferenceAsset.quality_status.notin_(EXCLUDED_QUALITY),
                ProductReferenceAsset.media_type.in_(REFERENCE_MEDIA_TYPES),
            )
            .order_by(ProductReferenceAsset.id)
        ).scalars()
    )
    by_family: dict[int, list[ProductReferenceAsset]] = {}
    ref_family: dict[int, int] = {}
    for r in refs:
        if r.family_id is not None and r.family_id in approved:
            fid = r.family_id
        elif r.variant_id is not None and r.variant_id in var_map:
            fid = var_map[r.variant_id]
        elif r.sku_id is not None and r.sku_id in sku_map:
            fid = sku_map[r.sku_id]
        else:
            continue
        by_family.setdefault(fid, []).append(r)
        ref_family[r.id] = fid

    emb_rows = {
        (e.target_id): e
        for e in session.execute(
            select(VisualMediaEmbedding).where(
                VisualMediaEmbedding.target_type == "reference",
                VisualMediaEmbedding.target_id.in_(list(ref_family) or [0]),
                VisualMediaEmbedding.provider == ident.provider,
                VisualMediaEmbedding.model_id == ident.model_id,
                VisualMediaEmbedding.status == "completed",
            )
        ).scalars()
    }

    # 摘要 =（合格参考图, 内容 sha, 向量是否已算得）——向量补齐也算参考集变化
    revision = _revision_digest(
        sorted(
            f"{r.id}:{r.sha256 or ''}:{int(r.id in emb_rows)}"
            for r in refs
            if r.id in ref_family
        )
    )

    out: list[FamilyRefs] = []
    for fid, fam_refs in sorted(by_family.items()):
        representative = [r for r in fam_refs if r.angle not in NON_REPRESENTATIVE_ANGLES]
        if len(fam_refs) < settings.visual_min_references or not representative:
            continue  # 资格不足 → 该产品缺席（与 API 冻结规则一致）
        vecs = [
            RefVector(
                reference_id=r.id, angle=r.angle, is_primary=bool(r.is_primary),
                vector=list(emb_rows[r.id].embedding),
            )
            for r in fam_refs
            if r.id in emb_rows and emb_rows[r.id].embedding is not None
        ]
        fam = approved[fid]
        out.append(
            FamilyRefs(
                family_id=fid, family_code=fam.code, family_name=fam.name_zh,
                refs=vecs, reference_count=len(fam_refs),
                source_levels=sorted({
                    "family" if r.family_id else ("variant" if r.variant_id else "sku")
                    for r in fam_refs
                }),
            )
        )
    return out, revision


def _revision_digest(parts: list[str]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _load_confusion_pairs(session: Session) -> dict[tuple[int, int], dict]:
    pairs = session.execute(
        select(ProductConfusionPair).where(
            ProductConfusionPair.target_level == "family",
            ProductConfusionPair.archived_at.is_(None),
        )
    ).scalars()
    out: dict[tuple[int, int], dict] = {}
    for p in pairs:
        key = tuple(sorted((p.left_target_id, p.right_target_id)))
        out[key] = {  # type: ignore[index]
            "pair_id": p.id, "severity": p.severity, "reason": p.reason,
            "distinguishing_features": p.distinguishing_features or [],
        }
    return out


def refresh_candidates(
    session: Session,
    settings: WorkerSettings,
    emb: VisualMediaEmbedding,
    *,
    families: list[FamilyRefs],
    revision: str,
    confusion_pairs: dict[tuple[int, int], dict],
) -> dict:
    """按当前参考集为一条嵌入行重算候选（置换 pending；尊重 dismissed）。"""
    if emb.embedding is None or emb.target_type not in ("asset", "shot"):
        return {"skipped": True}
    decision = decide_family_candidates(
        list(emb.embedding),
        families,
        min_score=settings.visual_min_score,
        min_margin=settings.visual_min_margin,
        confusion_margin=settings.visual_confusion_margin,
        top_k=settings.visual_top_k,
        aggregation="top_k_mean",
        confusion_pairs=confusion_pairs,
    )
    # 人工拒绝过的 (target, family) 不再复活
    dismissed = {
        fid
        for (fid,) in session.execute(
            select(VisualProductCandidate.family_id).where(
                VisualProductCandidate.target_type == emb.target_type,
                VisualProductCandidate.target_id == emb.target_id,
                VisualProductCandidate.status == "dismissed",
            )
        ).all()
    }
    # 置换 pending（派生数据；dismissed/confirmed 不动）
    for old in session.execute(
        select(VisualProductCandidate).where(
            VisualProductCandidate.target_type == emb.target_type,
            VisualProductCandidate.target_id == emb.target_id,
            VisualProductCandidate.status == "pending",
        )
    ).scalars():
        session.delete(old)
    session.flush()

    written = 0
    if decision.decision in ("candidate", "ambiguous"):
        thresholds = {
            "min_score": settings.visual_min_score,
            "min_margin": settings.visual_min_margin,
            "confusion_margin": settings.visual_confusion_margin,
            "min_references": settings.visual_min_references,
            "aggregation": "top_k_mean",
        }
        ident_provider, ident_model = emb.provider, emb.model_id
        # candidate 只落 top1；ambiguous 落难分的前两名（都给人看并标出）
        to_write = decision.candidates[:1] if decision.decision == "candidate" else \
            decision.candidates[:2]
        for c in to_write:
            if c.family_id in dismissed:
                continue
            if c.score < settings.visual_min_score:
                continue  # ambiguous 的第二名也必须过分数线才值得打扰人工
            session.add(
                VisualProductCandidate(
                    target_type=emb.target_type, target_id=emb.target_id,
                    family_id=c.family_id, score=c.score, margin=decision.margin,
                    decision=decision.decision, best_reference_id=c.best_reference_id,
                    provider=ident_provider, model_id=ident_model,
                    thresholds=thresholds, status="pending",
                    source_embedding_id=emb.id,
                )
            )
            written += 1
    emb.candidates_computed_at = utcnow()
    emb.candidates_ref_revision = revision
    session.flush()
    return {"decision": decision.decision, "written": written}


def sweep_targets(session: Session, settings: WorkerSettings, provider) -> dict:  # noqa: ANN001
    """找出需要视觉处理的目标（补嵌入 / 候选水位落后），返回入队清单。

    上限 visual_sweep_batch 防洪峰；调用方负责真正入队。
    """
    ident = provider.identity()
    limit = max(1, settings.visual_sweep_batch)
    existing = select(VisualMediaEmbedding.target_id).where(
        VisualMediaEmbedding.target_type == "asset",
        VisualMediaEmbedding.provider == ident.provider,
        VisualMediaEmbedding.model_id == ident.model_id,
        VisualMediaEmbedding.status == "completed",
    )
    assets = session.execute(
        select(Asset.id)
        .where(
            Asset.media_kind == "image",
            Asset.poster_path.is_not(None),
            Asset.id.notin_(existing),
        )
        .order_by(Asset.id)
        .limit(limit)
    ).scalars().all()

    existing_shot = select(VisualMediaEmbedding.target_id).where(
        VisualMediaEmbedding.target_type == "shot",
        VisualMediaEmbedding.provider == ident.provider,
        VisualMediaEmbedding.model_id == ident.model_id,
        VisualMediaEmbedding.status == "completed",
    )
    shots = session.execute(
        select(Shot.id)
        .where(
            Shot.status == ShotStatus.READY,
            Shot.retired_at.is_(None),
            Shot.keyframe_path.is_not(None),
            Shot.id.notin_(existing_shot),
        )
        .order_by(Shot.id)
        .limit(limit)
    ).scalars().all()

    existing_ref = select(VisualMediaEmbedding.target_id).where(
        VisualMediaEmbedding.target_type == "reference",
        VisualMediaEmbedding.provider == ident.provider,
        VisualMediaEmbedding.model_id == ident.model_id,
        VisualMediaEmbedding.status == "completed",
    )
    references = session.execute(
        select(ProductReferenceAsset.id)
        .where(
            ProductReferenceAsset.state == "active",
            ProductReferenceAsset.archived_at.is_(None),
            ProductReferenceAsset.id.notin_(existing_ref),
        )
        .order_by(ProductReferenceAsset.id)
        .limit(limit)
    ).scalars().all()

    stale: list[tuple[str, int]] = []
    if settings.visual_auto_candidates:
        _families, revision = load_family_ref_vectors(session, settings, provider)
        stale_rows = session.execute(
            select(
                VisualMediaEmbedding.target_type, VisualMediaEmbedding.target_id
            )
            .where(
                VisualMediaEmbedding.target_type.in_(["asset", "shot"]),
                VisualMediaEmbedding.provider == ident.provider,
                VisualMediaEmbedding.model_id == ident.model_id,
                VisualMediaEmbedding.status == "completed",
                (
                    VisualMediaEmbedding.candidates_ref_revision.is_(None)
                    | (VisualMediaEmbedding.candidates_ref_revision != revision)
                ),
            )
            .order_by(VisualMediaEmbedding.id)
            .limit(limit)
        ).all()
        stale = [(t, i) for t, i in stale_rows]

    return {
        "assets": list(assets),
        "shots": list(shots),
        "references": list(references),
        "stale_candidates": stale,
    }
