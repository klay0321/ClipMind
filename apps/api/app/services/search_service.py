"""Gate B：Hybrid Search 编排与召回（API 服务层）。

职责：解析查询 → 装配结构化过滤 → 多通道**数据库内**召回（向量/词法/标签/产品，候选池有界）
→ 复用 shared 融合评分 → 稳定排序 + 分页 → 批量取页数据与命中事实 → 规则派生解释 → 组装响应。

硬约束（与 PR 要求一致）：
- 召回、过滤、排序、分页**全部在数据库完成**；不把全量镜头读进 Python 再过滤；候选池有上限。
- 所有用户输入作为**绑定参数**，结构化字段经白名单映射到列；绝不拼接 SQL、绝不执行模型返回的
  字段/表/排序表达式。
- 向量召回严格门控：``is_searchable AND embedding_status='completed' AND embedding IS NOT NULL
  AND embedding_version = <当前 provider>``；degraded 文档不进向量，但仍参与词法/标签/产品/结构化。
- Parser/Embedding 失败**真实降级**且对外可见，不伪造向量、不假装语义成功。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from clipmind_shared.ai.embedding import EmbeddingProvider
from clipmind_shared.ai.providers.base import ProviderError
from clipmind_shared.models import (
    Asset,
    AssetProduct,
    Product,
    ProductAlias,
    Shot,
    ShotReviewState,
    ShotSearchDocument,
    ShotTag,
    Tag,
)
from clipmind_shared.models.enums import (
    ReviewStatus,
    SearchDocumentStatus,
    SearchEmbeddingStatus,
    ShotStatus,
    TagType,
)
from clipmind_shared.review.normalize import normalize_name
from clipmind_shared.search.explain import MatchFacts, build_explanations
from clipmind_shared.search.parser import SearchQueryParser
from clipmind_shared.search.query import (
    ASPECT_RATIO_TOLERANCE,
    ASPECT_RATIO_VALUES,
    AspectRatio,
    ParsedSearchQuery,
    ParserStatus,
    SearchMode,
)
from clipmind_shared.search.scoring import Candidate, order_candidates, paginate, score_candidates
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Float, String, and_, case, cast, exists, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.schemas.search import (
    AssetBrief,
    DescriptionMatchItem,
    DescriptionMatchRequest,
    DescriptionMatchResponse,
    ProductBrief,
    SearchResultItem,
    ShotSearchRequest,
    ShotSearchResponse,
    UsageInfoOut,
    UsageReasonOut,
    UsageSearchStatsOut,
)
from app.services import usage_feature_service
from app.services.usage_feature_service import UsageFeatures
from app.services.usage_ranking import (
    USAGE_MODES,
    USAGE_SCOPES,
    compute_adjustment,
    hard_filter_predicate,
    has_hard_filter,
    resolve_weights,
)

_HUMAN = (ReviewStatus.CONFIRMED.value, ReviewStatus.MODIFIED.value)
_EXCLUDED = (ReviewStatus.REJECTED.value, ReviewStatus.UNABLE.value)

_TAG_CHANNEL_FIELDS = (
    ("scenes", TagType.SCENE),
    ("actions", TagType.ACTION),
    ("shot_types", TagType.SHOT_TYPE),
    ("marketing_uses", TagType.MARKETING),
)


@dataclass
class _Merged:
    """parsed + request 合并后的结构化过滤/召回信号（显式请求优先）。"""

    scenes: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    shot_types: list[str] = field(default_factory=list)
    marketing_uses: list[str] = field(default_factory=list)
    quality_levels: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    brands: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    skus: list[str] = field(default_factory=list)
    required_risks: list[str] = field(default_factory=list)
    excluded_risks: list[str] = field(default_factory=list)
    negative_terms: list[str] = field(default_factory=list)  # 否定关键词 → 词法硬排除
    review_statuses: list[ReviewStatus] = field(default_factory=list)
    aspect_ratios: list[AspectRatio] = field(default_factory=list)
    duration_min: float | None = None
    duration_max: float | None = None
    confirmed_only: bool = False
    include_excluded: bool = False
    stale: bool | None = None
    source_directory_id: int | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    hard_product_ids: list[int] = field(default_factory=list)
    # PM：产品素材关系 hard filter（Family 维度；Shot 有效产品含继承语义）
    hard_family_id: int | None = None
    hard_variant_id: int | None = None
    has_product_assignment: bool | None = None
    # 显式 request 传入的结构化字段 → 硬过滤（解析得到的同名字段仅作软召回/解释）
    hard_scenes: list[str] = field(default_factory=list)
    hard_actions: list[str] = field(default_factory=list)
    hard_shot_types: list[str] = field(default_factory=list)
    hard_marketing: list[str] = field(default_factory=list)
    # 软场景/动作是否作为硬过滤（描述匹配 allow_similar_*=False 时启用）
    require_scene: bool = False
    require_action: bool = False


def _dedupe(*groups: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for g in groups:
        for v in g:
            k = (v or "").strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append(v.strip())
    return out


def _validate_conflicts(m: _Merged) -> None:
    """互斥条件冲突 → 422（不静默二选一）。"""
    req = {normalize_name(v) for v in m.required_risks if v}
    exc = {normalize_name(v) for v in m.excluded_risks if v}
    clash = sorted(req & exc)
    if clash:
        raise HTTPException(
            status_code=422,
            detail=f"required_risks 与 exclude_risks 冲突：{', '.join(clash)}",
        )


def _merge(parsed: ParsedSearchQuery, request: ShotSearchRequest) -> _Merged:
    return _Merged(
        scenes=_dedupe(parsed.scenes, request.scenes),
        actions=_dedupe(parsed.actions, request.actions),
        shot_types=_dedupe(parsed.shot_types, request.shot_types),
        marketing_uses=_dedupe(parsed.marketing_uses, request.marketing_uses),
        quality_levels=_dedupe(parsed.quality_requirements, request.quality_levels),
        products=_dedupe(parsed.products),
        brands=_dedupe(parsed.brands, request.brands),
        models=_dedupe(parsed.models, request.models),
        skus=_dedupe(parsed.skus, request.skus),
        required_risks=_dedupe(parsed.required_risks, request.include_risks),
        excluded_risks=_dedupe(parsed.excluded_risks, request.exclude_risks),
        negative_terms=_dedupe(parsed.negative_terms),
        review_statuses=list(dict.fromkeys([*parsed.review_statuses, *request.review_statuses])),
        aspect_ratios=list(dict.fromkeys([*parsed.aspect_ratios, *request.aspect_ratios])),
        duration_min=(
            request.duration_min if request.duration_min is not None else parsed.min_duration
        ),
        duration_max=(
            request.duration_max if request.duration_max is not None else parsed.max_duration
        ),
        confirmed_only=bool(request.confirmed_only or parsed.confirmed_only),
        include_excluded=bool(request.include_excluded or parsed.include_excluded),
        stale=request.stale,
        source_directory_id=request.source_directory_id,
        created_from=request.created_from,
        created_to=request.created_to,
        hard_product_ids=list(request.product_ids),
        hard_family_id=request.product_family_id,
        hard_variant_id=request.product_variant_id,
        has_product_assignment=(
            False if request.unassigned_only else request.has_product_assignment
        ),
        hard_scenes=list(request.scenes),
        hard_actions=list(request.actions),
        hard_shot_types=list(request.shot_types),
        hard_marketing=list(request.marketing_uses),
    )


# ---------------------- SQL 片段 ----------------------


def _effective_source():
    """当前 shot 的有效标签来源：human（已审核未 stale）否则 ai（镜像 shot_filter）。"""
    return case(
        (
            and_(
                ShotReviewState.review_status.in_(_HUMAN),
                ShotReviewState.stale_at.is_(None),
            ),
            "human",
        ),
        else_="ai",
    )


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _tag_exists(ttype: TagType, normalized_values: list[str], eff_source):
    return exists(
        select(ShotTag.id)
        .join(Tag, Tag.id == ShotTag.tag_id)
        .where(
            ShotTag.shot_id == Shot.id,
            ShotTag.active.is_(True),
            cast(ShotTag.source, String) == eff_source,
            Tag.tag_type == ttype,
            Tag.normalized_name.in_(normalized_values),
        )
    )


def _aspect_condition(ratios: list[AspectRatio]):
    ratio_expr = cast(Asset.width, Float) / func.nullif(cast(Asset.height, Float), 0)
    conds = []
    for ar in ratios:
        target = ASPECT_RATIO_VALUES[ar]
        tol = ASPECT_RATIO_TOLERANCE * target
        conds.append(
            and_(
                Asset.width.isnot(None),
                Asset.height.isnot(None),
                Asset.height > 0,
                func.abs(ratio_expr - target) <= tol,
            )
        )
    return or_(*conds) if conds else None


def _product_assoc(product_ids: list[int]):
    return or_(
        ShotReviewState.confirmed_product_id.in_(product_ids),
        Asset.primary_product_id.in_(product_ids),
        exists(
            select(AssetProduct.id).where(
                AssetProduct.asset_id == Shot.asset_id,
                AssetProduct.active.is_(True),
                AssetProduct.product_id.in_(product_ids),
            )
        ),
    )


def _joined(*cols):
    return (
        select(*cols)
        .select_from(Shot)
        .join(
            ShotSearchDocument,
            and_(
                ShotSearchDocument.shot_id == Shot.id,
                ShotSearchDocument.shot_generation == Shot.generation,
            ),
        )
        .join(Asset, Asset.id == Shot.asset_id)
        .outerjoin(
            ShotReviewState,
            and_(
                ShotReviewState.shot_id == Shot.id,
                ShotReviewState.shot_generation == Shot.generation,
            ),
        )
        .where(Shot.status == ShotStatus.READY, Shot.retired_at.is_(None))
    )


def _apply_filters(stmt, m: _Merged):
    eff = _effective_source()
    if m.include_excluded:
        stmt = stmt.where(
            ShotSearchDocument.document_status.in_(
                [SearchDocumentStatus.INDEXED, SearchDocumentStatus.EXCLUDED]
            )
        )
    else:
        stmt = stmt.where(ShotSearchDocument.is_searchable.is_(True))

    if m.review_statuses:
        stmt = stmt.where(ShotReviewState.review_status.in_(m.review_statuses))
    if m.confirmed_only:
        stmt = stmt.where(
            ShotReviewState.review_status.in_(_HUMAN),
            ShotReviewState.stale_at.is_(None),
        )
    if m.stale is True:
        stmt = stmt.where(ShotReviewState.stale_at.isnot(None))
    elif m.stale is False:
        stmt = stmt.where(
            or_(ShotReviewState.id.is_(None), ShotReviewState.stale_at.is_(None))
        )
    if m.duration_min is not None:
        stmt = stmt.where(Shot.duration >= m.duration_min)
    if m.duration_max is not None:
        stmt = stmt.where(Shot.duration <= m.duration_max)
    asp = _aspect_condition(m.aspect_ratios)
    if asp is not None:
        stmt = stmt.where(asp)
    if m.source_directory_id is not None:
        stmt = stmt.where(Asset.source_directory_id == m.source_directory_id)
    if m.created_from is not None:
        stmt = stmt.where(Shot.created_at >= m.created_from)
    if m.created_to is not None:
        stmt = stmt.where(Shot.created_at <= m.created_to)
    if m.excluded_risks:
        vals = [normalize_name(v) for v in m.excluded_risks if v]
        if vals:
            stmt = stmt.where(~_tag_exists(TagType.RISK, vals, eff))
    if m.required_risks:
        vals = [normalize_name(v) for v in m.required_risks if v]
        if vals:
            stmt = stmt.where(_tag_exists(TagType.RISK, vals, eff))
    # 否定关键词：硬排除归一文档命中该词的镜头（作用于所有召回通道的基查询）
    for neg in m.negative_terms:
        nt = normalize_name(neg)
        if nt:
            stmt = stmt.where(
                or_(
                    ShotSearchDocument.normalized_document.is_(None),
                    ~ShotSearchDocument.normalized_document.ilike(
                        f"%{_like_escape(nt)}%", escape="\\"
                    ),
                )
            )
    if m.hard_product_ids:
        stmt = stmt.where(_product_assoc(m.hard_product_ids))
    # PM：Family/Variant hard filter 与 已分配/未分配 过滤（继承语义：
    # shot 自身 link 优先，否则用 asset link；hard filter 不参与分数）
    if m.hard_family_id is not None or m.hard_variant_id is not None:
        from clipmind_shared.models import ProductMediaLink as _PML

        def _link_match(col_shot: bool):
            q = select(_PML.id)
            q = q.where(_PML.shot_id == Shot.id) if col_shot else q.where(
                _PML.asset_id == Shot.asset_id
            )
            if m.hard_family_id is not None:
                q = q.where(_PML.family_id == m.hard_family_id)
            if m.hard_variant_id is not None:
                q = q.where(_PML.variant_id == m.hard_variant_id)
            return q.exists()

        own_any = (
            select(_PML.id).where(_PML.shot_id == Shot.id).exists()
        )
        stmt = stmt.where(_link_match(True) | (~own_any & _link_match(False)))
    if m.has_product_assignment is not None:
        from clipmind_shared.models import ProductMediaLink as _PML2

        own_any2 = select(_PML2.id).where(_PML2.shot_id == Shot.id).exists()
        asset_any = select(_PML2.id).where(
            _PML2.asset_id == Shot.asset_id
        ).exists()
        assigned = own_any2 | asset_any
        stmt = stmt.where(assigned if m.has_product_assignment else ~assigned)
    # 显式 request 结构化字段 → 硬过滤（标签 EXISTS，按有效来源）；
    # 描述匹配 allow_similar_*=False 时把解析得到的场景/动作也升格为硬过滤。
    scene_hard = list(m.hard_scenes) + (m.scenes if m.require_scene else [])
    action_hard = list(m.hard_actions) + (m.actions if m.require_action else [])
    for vals_raw, ttype in (
        (scene_hard, TagType.SCENE),
        (action_hard, TagType.ACTION),
        (m.hard_shot_types, TagType.SHOT_TYPE),
        (m.hard_marketing, TagType.MARKETING),
    ):
        vals = [normalize_name(v) for v in vals_raw if v]
        if vals:
            stmt = stmt.where(_tag_exists(ttype, vals, eff))
    return stmt


# ---------------------- 产品解析 ----------------------


@dataclass
class _ResolvedProducts:
    recall_ids: list[int]
    exact_ids: list[int]
    by_id: dict[int, Product]
    match_kind: dict[int, str]


async def _resolve_products(db: AsyncSession, m: _Merged) -> _ResolvedProducts:
    """把文本产品引用解析为 product_id 集合（参考表查询，非结果过滤）。

    精确：SKU / 型号完全匹配 → exact_ids（高权重）。模糊：品牌/名称/别名归一匹配。
    """
    terms = _dedupe(m.products, m.brands, m.models, m.skus)
    if not terms and not m.skus and not m.models:
        return _ResolvedProducts([], [], {}, {})
    norm_terms = [normalize_name(t) for t in terms if t]
    norm_sku = {normalize_name(s) for s in m.skus if s} | {
        normalize_name(s) for s in m.products if s
    }
    norm_model = {normalize_name(s) for s in m.models if s}

    recall: dict[int, str] = {}
    exact: set[int] = set()
    by_id: dict[int, Product] = {}

    # 名称/品牌/SKU/型号匹配
    if norm_terms:
        stmt = select(Product).where(
            or_(
                Product.normalized_name.in_(norm_terms),
                func.lower(Product.sku).in_(list(norm_sku)) if norm_sku else False,
                func.lower(Product.model).in_(list(norm_model)) if norm_model else False,
                func.lower(Product.brand).in_(norm_terms),
            )
        )
        for p in (await db.execute(stmt)).scalars().all():
            by_id[p.id] = p
            kind = "name"
            if p.sku and normalize_name(p.sku) in norm_sku:
                kind = "sku"
                exact.add(p.id)
            elif p.model and normalize_name(p.model) in norm_model:
                kind = "model"
                exact.add(p.id)
            elif p.brand and normalize_name(p.brand) in norm_terms:
                kind = "brand"
            recall[p.id] = recall.get(p.id, kind)

    # 别名匹配
    if norm_terms:
        astmt = (
            select(ProductAlias.product_id, Product)
            .join(Product, Product.id == ProductAlias.product_id)
            .where(ProductAlias.normalized_alias.in_(norm_terms))
        )
        for pid, p in (await db.execute(astmt)).all():
            by_id[pid] = p
            recall.setdefault(pid, "alias")

    return _ResolvedProducts(list(recall.keys()), list(exact), by_id, recall)


# ---------------------- 召回通道 ----------------------


async def _channel_lexical(db, m, parsed, pool) -> list[tuple[int, float]]:
    nq = parsed.normalized_query
    terms = [normalize_name(t) for t in parsed.all_terms]
    terms += [normalize_name(t) for t in m.quality_levels]
    terms = [t for t in dict.fromkeys(terms) if t]
    if not nq and not terms:
        return []
    nd = ShotSearchDocument.normalized_document
    sim = func.similarity(nd, nq) if nq else literal(0.0)
    recall = []
    if nq:
        recall.append(nd.op("%")(nq))
    for t in terms:
        recall.append(nd.ilike(f"%{_like_escape(t)}%", escape="\\"))
    if not recall:
        return []
    stmt = _joined(Shot.id, sim.label("score"))
    stmt = _apply_filters(stmt, m).where(
        ShotSearchDocument.normalized_document.isnot(None), or_(*recall)
    )
    stmt = stmt.order_by(sim.desc(), Shot.id).limit(pool)
    rows = (await db.execute(stmt)).all()
    return [(int(r[0]), float(r[1] or 0.0)) for r in rows]


async def _channel_tag(db, m, pool) -> list[tuple[int, float]]:
    eff = _effective_source()
    conds = []
    for attr, ttype in _TAG_CHANNEL_FIELDS:
        vals = [normalize_name(v) for v in getattr(m, attr) if v]
        if vals:
            conds.append(_tag_exists(ttype, vals, eff))
    if not conds:
        return []
    hit_sum = None
    for c in conds:
        term = case((c, 1), else_=0)
        hit_sum = term if hit_sum is None else hit_sum + term
    score = cast(hit_sum, Float) / float(len(conds))
    stmt = _joined(Shot.id, score.label("score"))
    stmt = _apply_filters(stmt, m).where(or_(*conds))
    stmt = stmt.order_by(score.desc(), Shot.id).limit(pool)
    rows = (await db.execute(stmt)).all()
    return [(int(r[0]), float(r[1] or 0.0)) for r in rows]


# 产品匹配优先级阶梯（match_kind → 基础分）：SKU > 型号 > 产品名 > 别名 > 品牌
PRODUCT_KIND_SCORE: dict[str, float] = {
    "sku": 1.0,
    "model": 0.95,
    "name": 0.85,
    "alias": 0.75,
    "brand": 0.65,
}
# 人工确认的 shot-level 产品 优先于 仅素材级关联（同 kind 下加成）
CONFIRMED_ASSOC_BONUS = 0.05


async def _channel_product(
    db, m, products: _ResolvedProducts, pool
) -> list[tuple[int, float, bool]]:
    """产品召回：按 match_kind 多档打分 + shot-level confirmed 关联加成。

    返回 (shot_id, product_score, is_exact)；is_exact 表示命中 SKU/型号精确产品。
    """
    if not products.recall_ids:
        return []
    # 按匹配类型分组 → 每档一个 case；取该 shot 关联到的最高档
    by_kind: dict[str, list[int]] = {}
    for pid, kind in products.match_kind.items():
        by_kind.setdefault(kind, []).append(pid)
    tier_cases = [
        case((_product_assoc(ids), PRODUCT_KIND_SCORE.get(kind, 0.6)), else_=0.0)
        for kind, ids in by_kind.items()
    ]
    kind_score = func.greatest(*tier_cases) if len(tier_cases) > 1 else tier_cases[0]
    confirmed_boost = case(
        (ShotReviewState.confirmed_product_id.in_(products.recall_ids), CONFIRMED_ASSOC_BONUS),
        else_=0.0,
    )
    score = func.least(literal(1.0), kind_score + confirmed_boost)
    is_exact = (
        case((_product_assoc(products.exact_ids), True), else_=False)
        if products.exact_ids
        else literal(False)
    )
    stmt = _joined(Shot.id, score.label("score"), is_exact.label("is_exact"))
    stmt = _apply_filters(stmt, m).where(_product_assoc(products.recall_ids))
    stmt = stmt.order_by(score.desc(), Shot.id).limit(pool)
    rows = (await db.execute(stmt)).all()
    return [(int(r[0]), float(r[1] or 0.0), bool(r[2])) for r in rows]


async def _channel_vector(db, m, qvec, version, pool) -> list[tuple[int, float]]:
    dist = ShotSearchDocument.embedding.cosine_distance(qvec)
    stmt = _joined(Shot.id, dist.label("distance"))
    stmt = _apply_filters(stmt, m).where(
        ShotSearchDocument.embedding_status == SearchEmbeddingStatus.COMPLETED,
        ShotSearchDocument.embedding.isnot(None),
        ShotSearchDocument.embedding_version == version,
        # 历史空检索文档防御：空串向量对任意查询给近似恒定相似度，污染排序。
        # 仅排除真正“无任何文本”的文档（含标签/产品的退化文档其 normalized_document 非空，
        # 仍参与向量召回）。词法/标签/产品通道天然不会命中空文档，故只在此通道加固。
        func.length(func.coalesce(func.trim(ShotSearchDocument.normalized_document), "")) > 0,
    )
    stmt = stmt.order_by(dist.asc(), Shot.id).limit(pool)
    rows = (await db.execute(stmt)).all()
    return [(int(r[0]), max(0.0, 1.0 - float(r[1]))) for r in rows]


async def _count_base(db, m) -> int:
    stmt = _apply_filters(_joined(Shot.id), m)
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    return int((await db.execute(count_stmt)).scalar() or 0)


async def _recency_pool(db, m, pool) -> list[int]:
    stmt = _apply_filters(_joined(Shot.id), m).order_by(Shot.created_at.desc(), Shot.id.desc())
    rows = (await db.execute(stmt.limit(pool))).all()
    return [int(r[0]) for r in rows]


# ---------------------- 富集（候选池公共属性） ----------------------


@dataclass
class _Enrich:
    created_at: datetime | None
    review_status: str | None
    is_human_effective: bool
    is_stale: bool
    embedding_degraded: bool
    has_risk: bool
    has_quality_issue: bool
    duration: float


async def _enrich(db, shot_ids: list[int], current_version: str) -> dict[int, _Enrich]:
    if not shot_ids:
        return {}
    eff = _effective_source()
    # 任一风险/质量标签（有效来源）存在性
    risk_exists = exists(
        select(ShotTag.id)
        .join(Tag, Tag.id == ShotTag.tag_id)
        .where(
            ShotTag.shot_id == Shot.id,
            ShotTag.active.is_(True),
            cast(ShotTag.source, String) == eff,
            Tag.tag_type == TagType.RISK,
        )
    )
    quality_exists = exists(
        select(ShotTag.id)
        .join(Tag, Tag.id == ShotTag.tag_id)
        .where(
            ShotTag.shot_id == Shot.id,
            ShotTag.active.is_(True),
            cast(ShotTag.source, String) == eff,
            Tag.tag_type == TagType.QUALITY,
        )
    )
    stmt = _joined(
        Shot.id,
        Shot.created_at,
        Shot.duration,
        ShotReviewState.review_status,
        ShotReviewState.stale_at,
        ShotSearchDocument.embedding_status,
        ShotSearchDocument.embedding_version,
        case((risk_exists, True), else_=False).label("has_risk"),
        case((quality_exists, True), else_=False).label("has_quality"),
    ).where(Shot.id.in_(shot_ids))
    out: dict[int, _Enrich] = {}
    for r in (await db.execute(stmt)).all():
        rs = r.review_status
        is_human = rs in (ReviewStatus.CONFIRMED, ReviewStatus.MODIFIED) and r.stale_at is None
        emb_ok = (
            r.embedding_status == SearchEmbeddingStatus.COMPLETED
            and r.embedding_version == current_version
        )
        out[int(r.id)] = _Enrich(
            created_at=r.created_at,
            review_status=(rs.value if isinstance(rs, ReviewStatus) else rs),
            is_human_effective=bool(is_human),
            is_stale=bool(r.stale_at is not None),
            embedding_degraded=not emb_ok,
            has_risk=bool(r.has_risk),
            has_quality_issue=bool(r.has_quality),
            duration=float(r.duration or 0.0),
        )
    return out


# ---------------------- 页内事实（matched tags / product / 展示行） ----------------------


@dataclass
class _PageRow:
    shot: Shot
    asset: Asset
    review_status: str | None
    is_stale: bool


async def _fetch_page_rows(db, shot_ids: list[int]) -> dict[int, _PageRow]:
    if not shot_ids:
        return {}
    stmt = (
        select(Shot, Asset, ShotReviewState.review_status, ShotReviewState.stale_at)
        .join(Asset, Asset.id == Shot.asset_id)
        .outerjoin(
            ShotReviewState,
            and_(
                ShotReviewState.shot_id == Shot.id,
                ShotReviewState.shot_generation == Shot.generation,
            ),
        )
        .where(Shot.id.in_(shot_ids))
    )
    out: dict[int, _PageRow] = {}
    for shot, asset, rs, stale_at in (await db.execute(stmt)).all():
        out[shot.id] = _PageRow(
            shot=shot,
            asset=asset,
            review_status=(rs.value if isinstance(rs, ReviewStatus) else rs),
            is_stale=stale_at is not None,
        )
    return out


async def _fetch_page_tags(
    db, shot_ids: list[int], enrich: dict[int, _Enrich]
) -> dict[int, dict[str, list[str]]]:
    """返回 {shot_id: {tag_type: [tag_name,...]}}，按各 shot 的有效来源过滤。"""
    if not shot_ids:
        return {}
    stmt = (
        select(ShotTag.shot_id, ShotTag.source, Tag.tag_type, Tag.tag_name, Tag.normalized_name)
        .join(Tag, Tag.id == ShotTag.tag_id)
        .where(ShotTag.shot_id.in_(shot_ids), ShotTag.active.is_(True))
    )
    raw: dict[int, dict[str, list[tuple[str, str, str]]]] = {}
    for sid, source, ttype, tname, tnorm in (await db.execute(stmt)).all():
        src = source.value if hasattr(source, "value") else source
        raw.setdefault(int(sid), {}).setdefault(src, []).append(
            (ttype.value if hasattr(ttype, "value") else ttype, tname, tnorm)
        )
    out: dict[int, dict[str, list[str]]] = {}
    for sid in shot_ids:
        en = enrich.get(sid)
        eff_src = "human" if (en and en.is_human_effective) else "ai"
        by_type: dict[str, list[str]] = {}
        for ttype, tname, _tnorm in raw.get(sid, {}).get(eff_src, []):
            by_type.setdefault(ttype, []).append(tname)
        # 同时保留归一名用于匹配判断
        norms: dict[str, set[str]] = {}
        for ttype, _tname, tnorm in raw.get(sid, {}).get(eff_src, []):
            norms.setdefault(ttype, set()).add(tnorm)
        by_type["_norm"] = norms  # type: ignore[assignment]
        out[sid] = by_type
    return out


async def _fetch_page_products(
    db, shot_ids: list[int], products: _ResolvedProducts
) -> dict[int, ProductBrief]:
    """为页内每个 shot 找一个匹配产品（confirmed_product 优先），用于展示。"""
    if not shot_ids or not products.recall_ids:
        return {}
    # confirmed_product_id（shot 级人工确认）
    stmt = (
        select(Shot.id, ShotReviewState.confirmed_product_id)
        .outerjoin(
            ShotReviewState,
            and_(
                ShotReviewState.shot_id == Shot.id,
                ShotReviewState.shot_generation == Shot.generation,
            ),
        )
        .where(Shot.id.in_(shot_ids))
    )
    out: dict[int, ProductBrief] = {}
    confirmed: dict[int, int | None] = {
        int(sid): (int(pid) if pid is not None else None)
        for sid, pid in (await db.execute(stmt)).all()
    }
    # 素材级 product（fallback）
    astmt = (
        select(Shot.id, AssetProduct.product_id)
        .join(AssetProduct, AssetProduct.asset_id == Shot.asset_id)
        .where(
            Shot.id.in_(shot_ids),
            AssetProduct.active.is_(True),
            AssetProduct.product_id.in_(products.recall_ids),
        )
    )
    asset_prod: dict[int, int] = {}
    for sid, pid in (await db.execute(astmt)).all():
        asset_prod.setdefault(int(sid), int(pid))
    for sid in shot_ids:
        pid = confirmed.get(sid)
        if pid not in products.by_id:
            pid = asset_prod.get(sid)
        if pid in products.by_id:
            p = products.by_id[pid]
            out[sid] = ProductBrief(
                id=p.id,
                name=p.name,
                brand=p.brand,
                model=p.model,
                sku=p.sku,
                match_kind=products.match_kind.get(p.id),
            )
    return out


# ---------------------- URL 组装 ----------------------


def _urls(shot: Shot) -> dict[str, str | None]:
    base = f"/api/shots/{shot.id}"
    preview = f"{base}/preview" if shot.proxy_path else None
    return {
        "preview_url": preview,
        "thumbnail_url": f"{base}/thumbnail" if shot.thumbnail_path else None,
        "keyframe_url": f"{base}/keyframe" if shot.keyframe_path else None,
        "download_url": preview,  # 代理视频即 Gate B 可下载产物（剪辑导出属 PR-05）
    }


def _round_opt(v: float | None) -> float | None:
    return round(v, 4) if v is not None else None


def _orientation(asset: Asset) -> str | None:
    if asset.orientation:
        return asset.orientation
    if asset.width and asset.height:
        if asset.width > asset.height:
            return "landscape"
        if asset.width < asset.height:
            return "portrait"
        return "square"
    return None


# ---------------------- 主流程 ----------------------


@dataclass
class _Plan:
    parsed: ParsedSearchQuery
    candidates: list[Candidate]
    total: int                # 进入融合排序、可分页的候选数（truncated=false 时即精确匹配数）
    filtered_total: int       # 满足硬过滤条件的精确总数（与召回无关的"可检索宇宙"）
    truncated: bool           # 候选池是否被截断（某通道命中达上限 → total 为下界）
    mode_used: str
    embedding_status: str
    degraded: bool
    reasons: list[str]
    plan_summary: dict
    products: _ResolvedProducts
    enrich: dict[int, _Enrich]


async def _plan_search(
    db: AsyncSession,
    *,
    parsed: ParsedSearchQuery,
    m: _Merged,
    mode: SearchMode,
    embedding_provider: EmbeddingProvider,
    settings: Settings,
    pool: int,
) -> _Plan:
    reasons: list[str] = []
    if parsed.parser_status == ParserStatus.DEGRADED:
        reasons.append("parser_degraded")

    products = await _resolve_products(db, m)

    # 决定向量是否启用
    want_vector = mode in (SearchMode.HYBRID, SearchMode.SEMANTIC)
    qvec = None
    version = ""
    embedding_status = "unavailable"
    if want_vector:
        health = embedding_provider.health()
        if not health.ok:
            embedding_status = "degraded"
            reasons.append(f"embedding_provider_unhealthy:{health.detail or 'unhealthy'}")
        else:
            try:
                qvec = await run_in_threadpool(
                    embedding_provider.embed_query, parsed.semantic_text
                )
                version = embedding_provider.identity().embedding_version
                embedding_status = "ok"
            except ProviderError as exc:
                embedding_status = "degraded"
                reasons.append(f"query_embedding_failed:{getattr(exc, 'error_code', 'error')}")
                qvec = None
            except Exception:  # noqa: BLE001
                embedding_status = "degraded"
                reasons.append("query_embedding_failed:unexpected")
                qvec = None

    # 选择参与 RRF 的通道
    if mode == SearchMode.LEXICAL:
        active = ["lexical"]
    elif mode == SearchMode.STRUCTURED:
        active = ["product", "tag"]
    elif mode == SearchMode.SEMANTIC:
        active = ["semantic"] if qvec is not None else ["lexical"]
    else:  # hybrid
        active = ["product", "lexical", "tag"]
        if qvec is not None:
            active.append("semantic")

    # 执行各通道（仅 active）
    plan_summary: dict = {"candidate_pool_limit": pool}
    lex = tag = prod = vec = []
    if "lexical" in active:
        lex = await _channel_lexical(db, m, parsed, pool)
    if "tag" in active:
        tag = await _channel_tag(db, m, pool)
    if "product" in active:
        prod = await _channel_product(db, m, products, pool)
    if "semantic" in active and qvec is not None:
        vec = await _channel_vector(db, m, qvec, version, pool)
    plan_summary.update(
        {"lexical": len(lex), "tag": len(tag), "product": len(prod), "vector": len(vec)}
    )
    # 候选池截断判定：任一参与通道返回数达上限 → 可能有更多匹配未进池 → total 为下界
    truncated = any(
        len(rows) >= pool for rows in (lex, tag, prod, vec) if rows
    )

    cands: dict[int, Candidate] = {}

    def _get(sid: int) -> Candidate:
        c = cands.get(sid)
        if c is None:
            c = Candidate(shot_id=sid)
            cands[sid] = c
        return c

    for sid, s in lex:
        _get(sid).lexical_score = s
    for sid, s in tag:
        _get(sid).tag_score = s
    for sid, s, exact in prod:
        c = _get(sid)
        c.product_score = s
        c.exact_product = exact
    for sid, s in vec:
        _get(sid).semantic_score = s

    # 无任何信号通道（纯浏览）→ 走 recency 兜底
    no_signal = not (lex or tag or prod or vec)
    if no_signal and not parsed.has_structured_signal and not parsed.semantic_text.strip():
        rec_ids = await _recency_pool(db, m, pool)
        for sid in rec_ids:
            _get(sid)
        active = []
    elif no_signal:
        # 有条件但召回为空 → 候选为空（真实结果，不伪造）
        pass

    # 富集 + 评分
    enrich = await _enrich(db, list(cands.keys()), version)
    for sid, c in cands.items():
        en = enrich.get(sid)
        if en:
            c.created_at = en.created_at
            c.is_human_effective = en.is_human_effective
            c.review_status = en.review_status
            c.embedding_degraded = en.embedding_degraded
            c.has_unexcluded_risk = en.has_risk
            c.quality_score = 1.0 if not en.has_quality_issue else 0.5

    candidate_list = list(cands.values())
    if active:
        scored = score_candidates(candidate_list, active_channels=active)
    else:
        scored = order_candidates(candidate_list)
    plan_summary["pool"] = len(scored)

    # mode_used 真实反映
    mode_used = mode.value
    if mode == SearchMode.SEMANTIC and qvec is None:
        mode_used = "lexical"
    if no_signal and not active:
        mode_used = "structured"

    degraded = bool(reasons)
    total = len(scored)
    # 硬过滤精确总数（"可检索宇宙"，独立于软召回）：候选超过池时尤其有意义
    filtered_total = await _count_base(db, m)
    plan_summary["filtered_total"] = filtered_total
    plan_summary["truncated"] = truncated
    return _Plan(
        parsed=parsed,
        candidates=scored,
        total=total,
        filtered_total=filtered_total,
        truncated=truncated,
        mode_used=mode_used,
        embedding_status=embedding_status,
        degraded=degraded,
        reasons=reasons,
        plan_summary=plan_summary,
        products=products,
        enrich=enrich,
    )


def _reorder(scored: list[Candidate], sort: str, enrich: dict[int, _Enrich]) -> list[Candidate]:
    """二次排序。relevance 默认（保留融合全序）；其余以指定维度为主、final_score 为次，
    始终以 shot_id 收尾形成全序（稳定、可分页）。latest 兼容 newest。"""
    if sort in ("latest", "newest"):
        return sorted(
            scored,
            key=lambda c: (
                -(c.created_at.timestamp() if c.created_at else 0.0),
                -c.final_score,
                c.shot_id,
            ),
        )
    if sort == "duration":
        return sorted(
            scored,
            key=lambda c: (
                enrich.get(c.shot_id).duration if enrich.get(c.shot_id) else 0.0,
                -c.final_score,
                c.shot_id,
            ),
        )
    if sort == "quality":
        return sorted(
            scored,
            key=lambda c: (-c.quality_score, -c.final_score, c.shot_id),
        )
    return scored  # relevance：已由 score_candidates 全序排好


def _matched_facts(
    *,
    candidate: Candidate,
    parsed: ParsedSearchQuery,
    m: _Merged,
    tags: dict[str, object],
    product: ProductBrief | None,
    products: _ResolvedProducts,
    enrich: _Enrich | None,
) -> MatchFacts:
    norms: dict[str, set[str]] = tags.get("_norm", {}) if tags else {}  # type: ignore[assignment]

    def matched(req: list[str], ttype: TagType) -> tuple[list[str], list[str]]:
        present = norms.get(ttype.value, set())
        hit, miss = [], []
        for v in req:
            (hit if normalize_name(v) in present else miss).append(v)
        return hit, miss

    ms, us = matched(m.scenes, TagType.SCENE)
    ma, ua = matched(m.actions, TagType.ACTION)
    mst, ust = matched(m.shot_types, TagType.SHOT_TYPE)
    mmk, umk = matched(m.marketing_uses, TagType.MARKETING)

    # 关键词命中（正向词出现在归一文档不可得；用产品/标签命中 + 语义/词法分代理）
    matched_keywords: list[str] = []

    exact_label = None
    matched_products: list[str] = []
    product_mismatch = None
    if product is not None:
        if candidate.exact_product and product.sku and product.match_kind == "sku":
            exact_label = f"SKU {product.sku}"
        elif candidate.exact_product and product.model and product.match_kind == "model":
            exact_label = f"型号 {product.model}"
        else:
            matched_products = [product.name]
    elif products.recall_ids:
        wanted = _dedupe(m.products, m.brands, m.models, m.skus)[:3]
        product_mismatch = "、".join(wanted) or "指定产品"

    risk_present: list[str] = []
    if tags and "risk" in tags:
        risk_present = list(tags.get("risk", []))  # type: ignore[arg-type]

    excluded_clear = list(m.excluded_risks) if m.excluded_risks else []

    quality_requested = bool(m.quality_levels)
    quality_satisfied = bool(enrich and not enrich.has_quality_issue)

    return MatchFacts(
        matched_products=matched_products,
        exact_product_label=exact_label,
        matched_scenes=ms,
        matched_actions=ma,
        matched_shot_types=mst,
        matched_marketing=mmk,
        matched_keywords=matched_keywords,
        semantic_matched=candidate.semantic_score is not None,
        quality_requested=quality_requested,
        quality_satisfied=quality_satisfied,
        is_human_confirmed=bool(enrich and enrich.is_human_effective),
        excluded_risks_clear=excluded_clear,
        unmatched_scenes=us,
        unmatched_actions=ua,
        unmatched_shot_types=ust,
        unmatched_marketing=umk,
        product_mismatch=product_mismatch,
        quality_unmet=bool(quality_requested and enrich and enrich.has_quality_issue),
        embedding_degraded=bool(enrich and enrich.embedding_degraded),
        present_risks=risk_present,
    )


async def _build_items(
    db: AsyncSession,
    *,
    page_cands: list[Candidate],
    parsed: ParsedSearchQuery,
    m: _Merged,
    products: _ResolvedProducts,
    enrich: dict[int, _Enrich],
) -> list[SearchResultItem]:
    shot_ids = [c.shot_id for c in page_cands]
    rows = await _fetch_page_rows(db, shot_ids)
    tags = await _fetch_page_tags(db, shot_ids, enrich)
    prod_map = await _fetch_page_products(db, shot_ids, products)

    items: list[SearchResultItem] = []
    for c in page_cands:
        row = rows.get(c.shot_id)
        if row is None:
            continue
        shot, asset = row.shot, row.asset
        product = prod_map.get(c.shot_id)
        facts = _matched_facts(
            candidate=c,
            parsed=parsed,
            m=m,
            tags=tags.get(c.shot_id, {}),
            product=product,
            products=products,
            enrich=enrich.get(c.shot_id),
        )
        matched_reasons, unmatched, risks = build_explanations(facts)
        urls = _urls(shot)
        items.append(
            SearchResultItem(
                shot_id=shot.id,
                asset_id=shot.asset_id,
                sequence_no=shot.sequence_no,
                start_time=shot.start_time,
                end_time=shot.end_time,
                duration=shot.duration,
                status=shot.status.value if hasattr(shot.status, "value") else shot.status,
                asset=AssetBrief(
                    id=asset.id,
                    filename=asset.filename,
                    duration=asset.duration,
                    width=asset.width,
                    height=asset.height,
                    orientation=_orientation(asset),
                    source_directory_id=asset.source_directory_id,
                ),
                preview_url=urls["preview_url"],
                thumbnail_url=urls["thumbnail_url"],
                keyframe_url=urls["keyframe_url"],
                download_url=urls["download_url"],
                product=product,
                score=round(c.final_score, 4),
                match_percent=round(c.final_score * 100, 1),
                semantic_score=_round_opt(c.semantic_score),
                lexical_score=_round_opt(c.lexical_score),
                tag_score=_round_opt(c.tag_score),
                product_score=_round_opt(c.product_score),
                quality_score=round(c.quality_score, 4),
                review_bonus=round(c.review_bonus, 4),
                risk_penalty=round(c.risk_penalty, 4),
                matched_reasons=matched_reasons,
                unmatched_requirements=unmatched,
                risk_warnings=risks,
                review_status=row.review_status,
                review_is_stale=row.is_stale,
                embedding_degraded=c.embedding_degraded,
            )
        )
    return items


def _validate_usage_params(request: ShotSearchRequest) -> None:
    if request.usage_mode not in USAGE_MODES:
        raise HTTPException(status_code=422, detail=f"不支持的 usage_mode: {request.usage_mode}")
    if request.usage_scope not in USAGE_SCOPES:
        raise HTTPException(status_code=422, detail=f"不支持的 usage_scope: {request.usage_scope}")
    if (
        request.usage_mode == "exclude_high_frequency"
        and request.max_confirmed_usage_count is None
    ):
        raise HTTPException(
            status_code=422,
            detail="exclude_high_frequency 需要显式提供 max_confirmed_usage_count",
        )
    # 权重提前校验（NaN/Inf/越界 → 422），default 模式也校验以尽早暴露错误
    resolve_weights(request.usage_preset, request.usage_weights)


def _usage_ranking_active(request: ShotSearchRequest) -> bool:
    """default 模式完全跳过 usage 重排与过滤（排序与旧实现逐位一致）。"""
    return request.usage_mode != "default" or has_hard_filter(
        request.usage_mode,
        request.max_confirmed_usage_count,
        request.min_days_since_last_use,
        request.exclude_recently_used_days,
    )


@dataclass
class _UsageApplied:
    ordered: list[Candidate]
    adjustments: dict[int, tuple[float, float, list]]  # sid -> (base, adj, reasons)
    stats: UsageSearchStatsOut
    features: dict[int, UsageFeatures]


async def _apply_usage_ranking(
    db: AsyncSession,
    *,
    ordered: list[Candidate],
    request: ShotSearchRequest,
    now: datetime,
) -> _UsageApplied:
    """usage 过滤 + 重排（相关性为主：final=base+capped adjustment；tie-break 确定）。"""
    proj_started = time.perf_counter()
    features = await usage_feature_service.batch_features(
        db, [c.shot_id for c in ordered]
    )
    weights = resolve_weights(request.usage_preset, request.usage_weights)
    keep = hard_filter_predicate(
        mode=request.usage_mode,
        max_confirmed_usage_count=request.max_confirmed_usage_count,
        min_days_since_last_use=request.min_days_since_last_use,
        exclude_recently_used_days=request.exclude_recently_used_days,
        now=now,
    )
    kept: list[Candidate] = []
    filtered = 0
    adjustments: dict[int, tuple[float, float, list]] = {}
    for c in ordered:
        f = features.get(c.shot_id) or UsageFeatures(shot_id=c.shot_id)
        if not keep(f):
            filtered += 1
            continue
        adj, reasons = compute_adjustment(
            f,
            weights=weights,
            mode=request.usage_mode,
            scope=request.usage_scope,
            include_legacy_unknown=request.include_legacy_unknown,
            now=now,
        )
        adjustments[c.shot_id] = (c.final_score, adj, reasons)
        kept.append(c)
    if request.usage_mode != "default":
        # 重排：final=base+adj；tie-break (final desc, base desc, shot_id asc) 全序确定
        kept.sort(
            key=lambda c: (
                -(adjustments[c.shot_id][0] + adjustments[c.shot_id][1]),
                -adjustments[c.shot_id][0],
                c.shot_id,
            )
        )
    stats = UsageSearchStatsOut(
        requested_top_k=request.page * request.page_size,
        candidate_pool_size=len(ordered),
        filtered_count=filtered,
        returned_count=len(kept),
        usage_projection_ms=int((time.perf_counter() - proj_started) * 1000),
    )
    return _UsageApplied(ordered=kept, adjustments=adjustments, stats=stats, features=features)


def _attach_usage(
    items: list[SearchResultItem],
    features: dict[int, UsageFeatures],
    adjustments: dict[int, tuple[float, float, list]],
    now: datetime,
    request: ShotSearchRequest,
) -> None:
    """把使用特征/调整/解释附到结果项（不覆盖原始相似度字段与 score）。"""
    for item in items:
        f = features.get(item.shot_id)
        base, adj, reasons = adjustments.get(item.shot_id, (item.score, 0.0, []))
        item.base_score = round(base, 6)
        item.usage_adjustment = round(adj, 6)
        item.final_score = round(base + adj, 6)
        if not request.include_usage_explanation:
            continue
        if f is not None:
            item.usage = UsageInfoOut(
                shot_confirmed_usage_count=f.shot_confirmed_usage_count,
                shot_distinct_final_video_count=f.shot_distinct_final_video_count,
                asset_confirmed_usage_count=f.asset_confirmed_usage_count,
                asset_distinct_final_video_count=f.asset_distinct_final_video_count,
                asset_used_shot_count=f.asset_used_shot_count,
                asset_total_current_shot_count=f.asset_total_current_shot_count,
                last_confirmed_used_at=f.shot_last_confirmed_used_at,
                days_since_last_confirmed_use=f.days_since_last_confirmed_use(now),
                accepted_legacy_evidence_count=f.accepted_legacy_evidence_count,
                pending_formal_count=f.pending_formal_count,
                usage_state=f.usage_state,
            )
        item.usage_reasons = [
            UsageReasonOut(code=r.code, adjustment=r.adjustment, message=r.message)
            for r in reasons
        ]


async def run_shot_search(
    db: AsyncSession,
    request: ShotSearchRequest,
    *,
    parser: SearchQueryParser,
    embedding_provider: EmbeddingProvider,
    settings: Settings,
) -> ShotSearchResponse:
    started = time.perf_counter()
    _validate_usage_params(request)
    parsed = await run_in_threadpool(parser.parse, request.query or "")
    m = _merge(parsed, request)
    _validate_conflicts(m)
    pool = max(settings.search_candidate_pool, request.page * request.page_size)
    now = datetime.now(UTC)

    usage_active = _usage_ranking_active(request)
    hard_filtering = has_hard_filter(
        request.usage_mode,
        request.max_confirmed_usage_count,
        request.min_days_since_last_use,
        request.exclude_recently_used_days,
    )
    pool_max = max(settings.search_candidate_pool_max, pool)
    need = request.page * request.page_size
    expansion_rounds = 0
    limit_reached = False

    while True:
        plan = await _plan_search(
            db,
            parsed=parsed,
            m=m,
            mode=request.search_mode,
            embedding_provider=embedding_provider,
            settings=settings,
            pool=pool,
        )
        ordered = _reorder(plan.candidates, request.sort, plan.enrich)
        usage_applied: _UsageApplied | None = None
        if usage_active:
            usage_applied = await _apply_usage_ranking(
                db, ordered=ordered, request=request, now=now
            )
            ordered = usage_applied.ordered
            # 防饥饿：hard filter 吃掉候选且池被截断（可能还有匹配未进池）→ 扩张重跑
            if (
                hard_filtering
                and len(ordered) < need
                and plan.truncated
                and pool < pool_max
                and expansion_rounds < 3
            ):
                pool = min(pool * 2, pool_max)
                expansion_rounds += 1
                continue
            limit_reached = (
                hard_filtering
                and len(ordered) < need
                and plan.truncated
                and (pool >= pool_max or expansion_rounds >= 3)
            )
        break

    total = len(ordered) if usage_active else plan.total
    page_cands = paginate(ordered, request.page, request.page_size)
    items = await _build_items(
        db, page_cands=page_cands, parsed=parsed, m=m, products=plan.products, enrich=plan.enrich
    )

    usage_stats: UsageSearchStatsOut | None = None
    if usage_active:
        _attach_usage(items, usage_applied.features, usage_applied.adjustments, now, request)
        usage_stats = usage_applied.stats
        usage_stats.returned_count = len(ordered)
        usage_stats.expansion_rounds = expansion_rounds
        usage_stats.candidate_limit_reached = limit_reached
    elif request.include_usage_explanation:
        # default + 展示：只对页内投影（省查询）；adjustment 恒 0
        page_features = await usage_feature_service.batch_features(
            db, [c.shot_id for c in page_cands]
        )
        _attach_usage(items, page_features, {}, now, request)
        usage_stats = UsageSearchStatsOut(
            requested_top_k=need,
            candidate_pool_size=len(plan.candidates),
            filtered_count=0,
            returned_count=len(ordered),
        )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return ShotSearchResponse(
        items=items,
        total=total,
        filtered_total=plan.filtered_total,
        truncated=plan.truncated,
        page=request.page,
        page_size=request.page_size,
        search_mode_used=plan.mode_used,
        parser_status=parsed.parser_status.value,
        parser_provider=parsed.parser_provider,
        embedding_status=plan.embedding_status,
        degraded=plan.degraded,
        degradation_reasons=plan.reasons,
        elapsed_ms=elapsed_ms,
        query_plan_summary=plan.plan_summary,
        usage_stats=usage_stats,
        parsed_query=parsed,
    )


# ---------------------- 画面描述匹配 ----------------------


def _target_requirements(m: _Merged) -> list[str]:
    out: list[str] = []
    for label, vals in (
        ("产品", _dedupe(m.products, m.brands, m.models, m.skus)),
        ("场景", m.scenes),
        ("动作", m.actions),
        ("镜头类型", m.shot_types),
        ("营销用途", m.marketing_uses),
        ("画质", m.quality_levels),
        ("排除风险", m.excluded_risks),
    ):
        if vals:
            out.append(f"{label}：{'、'.join(vals[:5])}")
    if m.duration_min is not None or m.duration_max is not None:
        lo = "" if m.duration_min is None else f"{m.duration_min:g}s"
        hi = "" if m.duration_max is None else f"{m.duration_max:g}s"
        out.append(f"时长：{lo}~{hi}")
    if m.aspect_ratios:
        out.append(f"画幅：{'、'.join(a.value for a in m.aspect_ratios)}")
    if m.confirmed_only:
        out.append("仅人工确认")
    return out


def _recommendation_level(score: float, requires_review: bool) -> str:
    if score >= 0.75 and not requires_review:
        return "high"
    if score >= 0.5:
        return "medium"
    if score > 0.0:
        return "low"
    return "not_recommended"


async def run_description_match(
    db: AsyncSession,
    request: DescriptionMatchRequest,
    *,
    parser: SearchQueryParser,
    embedding_provider: EmbeddingProvider,
    settings: Settings,
) -> DescriptionMatchResponse:
    started = time.perf_counter()
    parsed = await run_in_threadpool(parser.parse, request.target_description)

    # 复用搜索过滤；allow_similar_* 控制场景/动作是否硬过滤
    base_req = ShotSearchRequest(
        query=request.target_description,
        product_ids=[request.product_id] if request.product_id else [],
        exclude_risks=request.exclude_risks,
        confirmed_only=request.confirmed_only,
        duration_min=request.duration_min,
        duration_max=request.duration_max,
        aspect_ratios=request.aspect_ratios,
        search_mode=SearchMode.HYBRID,
        page=1,
        page_size=request.limit,
    )
    m = _merge(parsed, base_req)
    # 显式结构化软信号并入软通道（解析结果 + 段落 structured_requirements 合并去重）。
    # 注意：并入 m.scenes/actions（软召回），而非 m.hard_scenes（始终硬）——是否升格为硬过滤
    # 由下方 require_scene/require_action（allow_similar_*=False）统一决定。
    m.scenes = _dedupe(m.scenes, request.scenes)
    m.actions = _dedupe(m.actions, request.actions)
    m.shot_types = _dedupe(m.shot_types, request.shot_types)
    m.marketing_uses = _dedupe(m.marketing_uses, request.marketing_uses)
    m.quality_levels = _dedupe(m.quality_levels, request.quality_levels)
    m.negative_terms = _dedupe(m.negative_terms, request.negative_terms)
    m.brands = _dedupe(m.brands, request.brands)
    m.models = _dedupe(m.models, request.models)
    m.skus = _dedupe(m.skus, request.skus)
    # 脚本匹配：忽略从文本解析出的时长，不据此硬过滤（时长是软偏好，单独算建议）。
    # 显式 request.duration_min/max（若传）不受影响，仍生效。
    if request.suppress_parsed_duration:
        m.duration_min = request.duration_min
        m.duration_max = request.duration_max
    _validate_conflicts(m)
    m.require_scene = not request.allow_similar_scene
    m.require_action = not request.allow_similar_action

    pool = max(settings.search_candidate_pool, request.limit)
    plan = await _plan_search(
        db,
        parsed=parsed,
        m=m,
        mode=SearchMode.HYBRID,
        embedding_provider=embedding_provider,
        settings=settings,
        pool=pool,
    )

    # minimum_score 过滤 + limit
    eligible = [c for c in plan.candidates if c.final_score >= request.minimum_score]
    page_cands = eligible[: request.limit]
    base_items = await _build_items(
        db, page_cands=page_cands, parsed=parsed, m=m, products=plan.products, enrich=plan.enrich
    )

    target_reqs = _target_requirements(m)
    items: list[DescriptionMatchItem] = []
    for it in base_items:
        requires_review = it.review_status not in ("confirmed", "modified")
        rec = _recommendation_level(it.score, requires_review)
        items.append(
            DescriptionMatchItem(
                **it.model_dump(),
                target_requirements=target_reqs,
                matched_requirements=it.matched_reasons,
                requires_human_confirmation=requires_review,
                recommendation_level=rec,
            )
        )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return DescriptionMatchResponse(
        items=items,
        total=plan.total,
        filtered_total=plan.filtered_total,
        truncated=plan.truncated,
        minimum_score=request.minimum_score,
        target_requirements=target_reqs,
        search_mode_used=plan.mode_used,
        parser_status=parsed.parser_status.value,
        embedding_status=plan.embedding_status,
        degraded=plan.degraded,
        degradation_reasons=plan.reasons,
        elapsed_ms=elapsed_ms,
    )
