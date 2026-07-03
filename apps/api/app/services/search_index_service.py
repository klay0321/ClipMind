"""Gate B：索引状态 / 搜索建议 / 索引重建编排（API 服务层）。

- 索引状态：聚合 ``shot_search_document`` 的文档/嵌入状态与版本一致性，回显当前 provider 健康。
- 搜索建议：产品名/别名/品牌 + 有效标签（scene/action/marketing/shot_type）；不做 SearchHistory。
- 重建：按名入队 search 队列任务；危险操作（全量/强制重嵌）需显式参数。当前无鉴权体系，
  本地管理端限制见文档（PR-07 前不伪造用户权限）。
"""

from __future__ import annotations

import logging

from clipmind_shared.ai.embedding import EmbeddingProvider
from clipmind_shared.models import (
    AIShotAnalysis,
    Asset,
    Product,
    ProductAlias,
    Shot,
    ShotReviewState,
    ShotSearchDocument,
    ShotTag,
    Tag,
)
from clipmind_shared.models.enums import (
    AIShotAnalysisStatus,
    ProductStatus,
    ReviewStatus,
    SearchDocumentStatus,
    SearchEmbeddingStatus,
    ShotStatus,
    TagType,
)
from clipmind_shared.review.normalize import normalize_name
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.search import (
    IndexStatusResponse,
    RebuildAcceptedResponse,
    SearchSuggestion,
    ShotCompletenessResponse,
    SuggestionsResponse,
)
from app.tasks_client import (
    enqueue_backfill_search_docs,
    enqueue_rebuild_asset_search_docs,
    enqueue_rebuild_shot_search_doc,
    enqueue_sweep_search_docs,
)

logger = logging.getLogger(__name__)


async def get_index_status(
    db: AsyncSession, embedding_provider: EmbeddingProvider
) -> IndexStatusResponse:
    ssd = ShotSearchDocument
    identity = embedding_provider.identity()
    current_version = identity.embedding_version
    health = embedding_provider.health()

    total_shots = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Shot)
                .where(Shot.status == ShotStatus.READY, Shot.retired_at.is_(None))
            )
        ).scalar()
        or 0
    )

    doc_counts = {
        k: int(v)
        for k, v in (
            await db.execute(
                select(ssd.document_status, func.count()).group_by(ssd.document_status)
            )
        ).all()
    }
    emb_counts = {
        k: int(v)
        for k, v in (
            await db.execute(
                select(ssd.embedding_status, func.count()).group_by(ssd.embedding_status)
            )
        ).all()
    }

    matched = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ssd)
                .where(
                    ssd.embedding_status == SearchEmbeddingStatus.COMPLETED,
                    ssd.embedding_version == current_version,
                )
            )
        ).scalar()
        or 0
    )
    completed = emb_counts.get(SearchEmbeddingStatus.COMPLETED, 0)
    mismatched = max(0, completed - matched)

    stale_documents = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ShotReviewState)
                .where(ShotReviewState.stale_at.isnot(None))
            )
        ).scalar()
        or 0
    )
    last_indexed_at = (
        await db.execute(select(func.max(ssd.indexed_at)))
    ).scalar()

    return IndexStatusResponse(
        total_shots=total_shots,
        indexed_documents=doc_counts.get(SearchDocumentStatus.INDEXED, 0),
        excluded_documents=doc_counts.get(SearchDocumentStatus.EXCLUDED, 0),
        completed_embeddings=completed,
        degraded_embeddings=emb_counts.get(SearchEmbeddingStatus.DEGRADED, 0),
        failed_embeddings=emb_counts.get(SearchEmbeddingStatus.FAILED, 0),
        pending_embeddings=emb_counts.get(SearchEmbeddingStatus.PENDING, 0)
        + emb_counts.get(SearchEmbeddingStatus.EMBEDDING, 0),
        current_embedding_version=current_version,
        embedding_version_matched=matched,
        embedding_version_mismatched=mismatched,
        stale_documents=stale_documents,
        last_indexed_at=last_indexed_at,
        provider_healthy=bool(health.ok),
        provider_detail=health.detail or "",
    )


async def get_shot_completeness(db: AsyncSession) -> ShotCompletenessResponse:
    """全库镜头拆解完整度（只读聚合）。所有计数均来自真实表统计，绝不估算/伪造。"""
    total_assets = int(
        (await db.execute(select(func.count()).select_from(Asset))).scalar() or 0
    )
    total_shots = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Shot)
                .where(Shot.status == ShotStatus.READY, Shot.retired_at.is_(None))
            )
        ).scalar()
        or 0
    )
    ai_analyzed_shots = int(
        (
            await db.execute(
                select(func.count(func.distinct(AIShotAnalysis.shot_id))).where(
                    AIShotAnalysis.status == AIShotAnalysisStatus.COMPLETED
                )
            )
        ).scalar()
        or 0
    )
    ai_failed_shots = int(
        (
            await db.execute(
                select(func.count(func.distinct(AIShotAnalysis.shot_id))).where(
                    AIShotAnalysis.status == AIShotAnalysisStatus.FAILED
                )
            )
        ).scalar()
        or 0
    )
    review_counts = {
        k: int(v)
        for k, v in (
            await db.execute(
                select(ShotReviewState.review_status, func.count()).group_by(
                    ShotReviewState.review_status
                )
            )
        ).all()
    }
    pending_review_shots = review_counts.get(ReviewStatus.PENDING_REVIEW, 0)
    confirmed_shots = review_counts.get(ReviewStatus.CONFIRMED, 0) + review_counts.get(
        ReviewStatus.MODIFIED, 0
    )
    searchable_shots = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ShotSearchDocument)
                .where(ShotSearchDocument.is_searchable.is_(True))
            )
        ).scalar()
        or 0
    )
    risk_shots = int(
        (
            await db.execute(
                select(func.count(func.distinct(ShotTag.shot_id)))
                .select_from(ShotTag)
                .join(Tag, Tag.id == ShotTag.tag_id)
                .where(ShotTag.active.is_(True), Tag.tag_type == TagType.RISK)
            )
        ).scalar()
        or 0
    )
    return ShotCompletenessResponse(
        total_assets=total_assets,
        total_shots=total_shots,
        ai_analyzed_shots=ai_analyzed_shots,
        ai_failed_shots=ai_failed_shots,
        pending_review_shots=pending_review_shots,
        confirmed_shots=confirmed_shots,
        searchable_shots=searchable_shots,
        risk_shots=risk_shots,
    )


async def get_suggestions(db: AsyncSession, q: str | None, limit: int) -> SuggestionsResponse:
    nq = normalize_name(q) if q else ""
    out: list[SearchSuggestion] = []
    seen: set[tuple[str, str]] = set()

    def add(value: str, type_: str) -> None:
        key = (type_, value.lower())
        if value and key not in seen and len(out) < limit:
            seen.add(key)
            out.append(SearchSuggestion(value=value, type=type_))

    # 产品名（PR-E.1：LIMIT 必须配确定 ORDER BY，否则行序随执行计划漂移）
    pstmt = select(Product.name, Product.brand).where(Product.status == ProductStatus.ACTIVE)
    if nq:
        pstmt = pstmt.where(Product.normalized_name.like(f"%{nq}%"))
    pstmt = pstmt.order_by(Product.normalized_name, Product.id)
    for name, brand in (await db.execute(pstmt.limit(limit))).all():
        add(name, "product")
        if brand:
            add(brand, "brand")

    # 产品别名
    astmt = select(ProductAlias.alias)
    if nq:
        astmt = astmt.where(ProductAlias.normalized_alias.like(f"%{nq}%"))
    astmt = astmt.order_by(ProductAlias.normalized_alias, ProductAlias.id)
    for (alias,) in (await db.execute(astmt.limit(limit))).all():
        add(alias, "product")

    # 有效标签（被 active shot_tag 引用过的）
    type_map = {
        TagType.SCENE: "scene",
        TagType.ACTION: "action",
        TagType.MARKETING: "marketing",
        TagType.SHOT_TYPE: "shot_type",
    }
    used = exists(select(ShotTag.id).where(ShotTag.tag_id == Tag.id, ShotTag.active.is_(True)))
    tstmt = select(Tag.tag_name, Tag.tag_type).where(
        Tag.tag_type.in_(list(type_map.keys())), used
    )
    if nq:
        tstmt = tstmt.where(Tag.normalized_name.like(f"%{nq}%"))
    tstmt = tstmt.order_by(Tag.normalized_name, Tag.id)
    for tname, ttype in (await db.execute(tstmt.limit(limit * 2))).all():
        add(tname, type_map.get(ttype, "tag"))

    return SuggestionsResponse(items=out[:limit])


# ---------------------- 重建编排 ----------------------


def _accept(scope: str, fn, **kw) -> RebuildAcceptedResponse:
    target_id = kw.get("target_id")
    force = kw.get("force_reembed", False)
    only_failed = kw.get("only_failed", False)
    try:
        task_id = fn()
        return RebuildAcceptedResponse(
            accepted=True,
            scope=scope,
            target_id=target_id,
            force_reembed=force,
            only_failed=only_failed,
            celery_task_id=task_id,
            detail="已入队",
        )
    except Exception as exc:  # noqa: BLE001 — broker 不可用不应 500，sweeper/backfill 兜底
        logger.warning("入队检索重建失败（scope=%s）：%s", scope, exc)
        return RebuildAcceptedResponse(
            accepted=False,
            scope=scope,
            target_id=target_id,
            force_reembed=force,
            only_failed=only_failed,
            detail="入队失败：broker 不可用（可稍后由 sweeper/backfill 兜底）",
        )


def rebuild_shot(shot_id: int, force_reembed: bool) -> RebuildAcceptedResponse:
    return _accept(
        "shot",
        lambda: enqueue_rebuild_shot_search_doc(shot_id, force_reembed),
        target_id=shot_id,
        force_reembed=force_reembed,
    )


def rebuild_asset(asset_id: int, force_reembed: bool) -> RebuildAcceptedResponse:
    return _accept(
        "asset",
        lambda: enqueue_rebuild_asset_search_docs(asset_id, force_reembed),
        target_id=asset_id,
        force_reembed=force_reembed,
    )


def sweep(limit: int, force_reembed: bool) -> RebuildAcceptedResponse:
    return _accept(
        "sweep",
        lambda: enqueue_sweep_search_docs(limit, force_reembed),
        force_reembed=force_reembed,
    )


def backfill(only_failed: bool, force_reembed: bool, limit: int) -> RebuildAcceptedResponse:
    return _accept(
        "backfill",
        lambda: enqueue_backfill_search_docs(only_failed, force_reembed, limit),
        only_failed=only_failed,
        force_reembed=force_reembed,
    )
