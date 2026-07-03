"""PR-F：合格参考图筛选与视觉特征内存索引（零迁移；docs/VISUAL_RECOGNITION.md）。

资格规则（.local/pr-f-a/reference-eligibility-design.md 冻结）：
- Family：CatalogStatus.ACTIVE + merged_into_id IS NULL + archived_at IS NULL
  + 最新 ProductOnboardingReview.status == "approved"（无记录 = 不合格）；
- 参考图：state=="active" 且 archived_at IS NULL 且 quality_status 不在
  {wrong_product, duplicate, blurred, occluded, low_resolution}（即仅
  unchecked/qualified）且 media_type ∈ REFERENCE_MEDIA_TYPES；
- Variant/SKU 挂图向上归并计入 Family 参考集（标注 source_level）；
- 模型输入用原图 image_path（缩略图 best-effort 低清，不作模型输入）。

特征缓存：进程内 dict，键 (reference_id, sha256, provider, model_id)——
参考图内容或模型变化自然失效；本阶段参考图量级小（几十~几百），
不建持久索引（Gate B 范围）。缓存不含图片内容本身。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from clipmind_shared.ai.visual import VisualEmbeddingProvider, VisualProviderError
from clipmind_shared.models import (
    ProductFamily,
    ProductOnboardingReview,
    ProductReferenceAsset,
    ProductSKU,
    ProductVariant,
)
from clipmind_shared.models.enums import REFERENCE_MEDIA_TYPES, CatalogStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import files

logger = logging.getLogger(__name__)

EXCLUDED_QUALITY = frozenset(
    {"wrong_product", "duplicate", "blurred", "occluded", "low_resolution"}
)
# detail/package 不能单独代表完整产品（资格判定用）
NON_REPRESENTATIVE_ANGLES = frozenset({"detail", "package"})


@dataclass
class EligibleReference:
    reference_id: int
    family_id: int
    source_level: str          # family | variant | sku（图挂在哪一层）
    source_id: int
    angle: str
    is_primary: bool
    quality_status: str
    image_path: str


@dataclass
class FamilyReferenceSet:
    family_id: int
    family_code: str
    family_name: str
    onboarding_status: str
    references: list[EligibleReference] = field(default_factory=list)
    ineligible_reason: str | None = None  # 不足最小合格图数等

    @property
    def eligible(self) -> bool:
        return self.ineligible_reason is None


# 进程内特征缓存：(reference_id, sha256, provider, model_id) -> vector
_feature_cache: dict[tuple[int, str, str, str], list[float]] = {}


def clear_feature_cache() -> None:
    _feature_cache.clear()


async def load_family_reference_sets(
    db: AsyncSession, *, min_references: int
) -> list[FamilyReferenceSet]:
    """全量装载：approved+active Family 及其合格参考图（含 Variant/SKU 归并）。

    返回含不合格 Family（带 ineligible_reason）供 coverage 展示；
    候选检索只用 eligible 的集合。
    """
    fam_rows = (
        await db.execute(
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
        )
    ).all()
    approved_ids = [f.id for f, ob in fam_rows if ob == "approved"]
    sets: dict[int, FamilyReferenceSet] = {}
    for f, ob in fam_rows:
        sets[f.id] = FamilyReferenceSet(
            family_id=f.id,
            family_code=f.code,
            family_name=f.name_zh,
            onboarding_status=ob or "incomplete",
        )
        if ob != "approved":
            sets[f.id].ineligible_reason = f"onboarding_{ob or 'incomplete'}"

    if approved_ids:
        # variant/sku → family 映射（向上归并）
        var_map = {
            vid: fid
            for vid, fid in (
                await db.execute(
                    select(ProductVariant.id, ProductVariant.family_id).where(
                        ProductVariant.family_id.in_(approved_ids)
                    )
                )
            ).all()
        }
        sku_map = {
            sid: fid
            for sid, fid in (
                await db.execute(
                    select(ProductSKU.id, ProductSKU.family_id).where(
                        ProductSKU.family_id.in_(approved_ids)
                    )
                )
            ).all()
        }
        refs = (
            await db.execute(
                select(ProductReferenceAsset)
                .where(
                    ProductReferenceAsset.state == "active",
                    ProductReferenceAsset.archived_at.is_(None),
                    ProductReferenceAsset.quality_status.notin_(EXCLUDED_QUALITY),
                    ProductReferenceAsset.media_type.in_(REFERENCE_MEDIA_TYPES),
                )
                .order_by(ProductReferenceAsset.id)
            )
        ).scalars()
        for r in refs:
            if r.family_id is not None and r.family_id in sets:
                fid, level, src = r.family_id, "family", r.family_id
            elif r.variant_id is not None and r.variant_id in var_map:
                fid, level, src = var_map[r.variant_id], "variant", r.variant_id
            elif r.sku_id is not None and r.sku_id in sku_map:
                fid, level, src = sku_map[r.sku_id], "sku", r.sku_id
            else:
                continue
            if sets[fid].ineligible_reason:
                continue
            sets[fid].references.append(
                EligibleReference(
                    reference_id=r.id,
                    family_id=fid,
                    source_level=level,
                    source_id=src,
                    angle=r.angle,
                    is_primary=bool(r.is_primary),
                    quality_status=r.quality_status,
                    image_path=r.image_path,
                )
            )

    for s in sets.values():
        if s.ineligible_reason:
            continue
        representative = [
            r for r in s.references if r.angle not in NON_REPRESENTATIVE_ANGLES
        ]
        if len(s.references) < min_references:
            s.ineligible_reason = "insufficient_reference"
        elif not representative:
            s.ineligible_reason = "insufficient_reference"  # 仅 detail/package 不能代表产品
    return sorted(sets.values(), key=lambda s: s.family_id)


def _read_reference_bytes(image_path: str) -> bytes:
    """安全读取参考图原图（data_dir 包含校验，只读打开）。"""
    abs_path = files.resolve_derived(image_path)
    with open(abs_path, "rb") as f:  # noqa: PTH123
        return f.read()


async def embed_references(
    references: list[EligibleReference],
    *,
    provider: VisualEmbeddingProvider,
    sha_by_ref: dict[int, str],
) -> dict[int, list[float]]:
    """批量取参考图向量（带进程内缓存；miss 才读文件+推理）。

    单张失败（文件缺失/解码失败）记为跳过并在返回中缺席——调用方据
    reference_count 差异展示；绝不用零向量顶替。
    """
    ident = provider.identity()
    out: dict[int, list[float]] = {}
    misses: list[EligibleReference] = []
    for r in references:
        key = (r.reference_id, sha_by_ref.get(r.reference_id, ""), ident.provider,
               ident.model_id)
        cached = _feature_cache.get(key)
        if cached is not None:
            out[r.reference_id] = cached
        else:
            misses.append(r)
    if not misses:
        return out
    payload: list[bytes] = []
    ok_refs: list[EligibleReference] = []
    for r in misses:
        try:
            payload.append(_read_reference_bytes(r.image_path))
            ok_refs.append(r)
        except Exception as exc:  # noqa: BLE001 —— 单图缺失不拖垮全库；缺席即报告
            logger.debug(
                "参考图 %s 读取失败（%s），本轮缺席", r.reference_id, type(exc).__name__
            )
            continue
    if not payload:
        return out
    vectors = provider.embed_images(payload)  # 失败抛 VisualProviderError（显式）
    if len(vectors) != len(ok_refs):  # 防御：数量错位宁可失败
        raise VisualProviderError("向量数量与图片数量不一致")
    for r, vec in zip(ok_refs, vectors, strict=True):
        key = (r.reference_id, sha_by_ref.get(r.reference_id, ""), ident.provider,
               ident.model_id)
        _feature_cache[key] = vec
        out[r.reference_id] = vec
    return out
