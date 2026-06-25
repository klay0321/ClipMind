"""检索文档索引器（PR-04，search 队列纯逻辑）。

幂等地把一个镜头的**有效结果**构建为 ``shot_search_document`` 并嵌入向量：

有效结果规则（与 review_service.compute_effective 一致）：
- confirmed/modified 且未 stale → 人工结果（source=human，记 source_review_state_id）；
- unreviewed/pending → 最新成功 AI（source=ai，记 source_ai_analysis_id）；
- 人工 stale → 回退最新 AI；
- rejected/unable/无结果 → 保留记录、is_searchable=false、document_status=excluded、不嵌入。

文档层与嵌入层正交：文档构建成功即 document_status=indexed + is_searchable=true（可被词法/
pg_trgm/标签/产品检索，**即使无向量**）；嵌入不可用时仅 embedding_status=degraded、不进向量召回。

幂等（§8）：仅当 文档哈希 + 嵌入身份(provider/model/revision/dimension/version) + 模板版本
全部一致、且 embedding_status=completed、且向量非空时跳过重嵌；任一不符或 force_reembed 则重建。

返回状态：completed | degraded | excluded | skipped | failed | retry | not_found。
``retry`` 表示可重试的瞬时 provider 故障（任务层据此走 Celery 退避重试）。
"""

from __future__ import annotations

import logging
from typing import Any

from clipmind_shared.ai import get_embedding_provider
from clipmind_shared.ai.embedding import EmbeddingProvider
from clipmind_shared.ai.providers.base import (
    ProviderError,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderTimeoutError,
    ProviderUnavailable,
)
from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN, SEARCH_DOCUMENT_TEMPLATE_VERSION
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIShotAnalysis,
    Product,
    ProductAlias,
    Shot,
    ShotReviewState,
    ShotSearchDocument,
)
from clipmind_shared.models.enums import (
    ReviewStatus,
    SearchDocumentStatus,
    SearchEmbeddingStatus,
    ShotStatus,
)
from clipmind_shared.review import effective_result
from clipmind_shared.search import build_search_document
from sqlalchemy import Text, and_, cast, exists, or_, select
from sqlalchemy.orm import Session

from clipmind_worker.config import WorkerSettings

logger = logging.getLogger(__name__)

# 可重试的瞬时 provider 故障（其余视为永久：未配置→degraded；鉴权/维度/坏响应→failed）
_TRANSIENT = (ProviderTimeoutError, ProviderRateLimited, ProviderUnavailable)


def build_embedding_provider(settings: WorkerSettings) -> EmbeddingProvider:
    return get_embedding_provider(
        settings.embedding_provider,
        base_url=settings.embedding_base_url or None,
        api_key=settings.embedding_api_key or None,
        model=settings.embedding_model or None,
        dimension=settings.embedding_dimension,
        model_revision=settings.embedding_model_revision,
        timeout=settings.embedding_timeout,
        max_batch=settings.embedding_max_batch,
        api_key_header=settings.embedding_api_key_header,
        prefix_scheme=settings.embedding_prefix_scheme,
        require_pinned_revision=settings.embedding_require_pinned_revision,
    )


class _Effective:
    __slots__ = (
        "result", "source", "searchable", "review_status",
        "source_ai_analysis_id", "source_review_state_id", "source_review_lock_version",
        "result_schema_version",
    )

    def __init__(self, **kw: object) -> None:
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def resolve_effective(session: Session, shot: Shot) -> _Effective:
    """同步版有效结果解析（对齐 review_service.compute_effective 的语义）。"""
    ai = session.execute(
        select(AIShotAnalysis).where(AIShotAnalysis.shot_id == shot.id)
    ).scalar_one_or_none()
    review = session.execute(
        select(ShotReviewState).where(
            ShotReviewState.shot_id == shot.id,
            ShotReviewState.shot_generation == shot.generation,
        )
    ).scalar_one_or_none()

    ai_parsed = ai.parsed_result if ai else None
    rs = review.review_status.value if review else None
    eff = effective_result(
        ai_parsed,
        review_status=rs,
        confirmed_result=review.confirmed_result if review else None,
    )

    # stale：generation 不符或 review 已被标记 stale → 人工失效，回退最新 AI
    is_stale = False
    if review is not None and (
        review.shot_generation != shot.generation or review.stale_reason
    ):
        is_stale = True
    if eff.source == "human" and is_stale:
        eff = effective_result(ai_parsed, review_status=None, confirmed_result=None)

    if eff.source == "human" and review is not None:
        return _Effective(
            result=eff.result, source="human", searchable=True,
            review_status=rs, source_ai_analysis_id=review.source_ai_analysis_id,
            source_review_state_id=review.id,
            source_review_lock_version=review.lock_version,
            result_schema_version=review.result_schema_version,
        )
    if eff.source == "ai" and ai is not None:
        return _Effective(
            result=eff.result, source="ai", searchable=True,
            review_status=rs or ReviewStatus.UNREVIEWED.value,
            source_ai_analysis_id=ai.id, source_review_state_id=None,
            source_review_lock_version=None,
            result_schema_version=ai.schema_version,
        )
    # rejected / unable / none → 不可搜索（保留记录）；记录审核行身份/版本供 sweeper 比对
    return _Effective(
        result=None, source=eff.source, searchable=False,
        review_status=rs, source_ai_analysis_id=(ai.id if ai else None),
        source_review_state_id=(review.id if review else None),
        source_review_lock_version=(review.lock_version if review else None),
        result_schema_version=None,
    )


def _product_terms(session: Session, shot: Shot, eff: _Effective) -> list[str]:
    """人工确认产品的补充检索词（品牌/型号/SKU/别名）。仅 human 来源时取当前确认产品。"""
    if eff.source != "human" or eff.source_review_state_id is None:
        return []
    review = session.get(ShotReviewState, eff.source_review_state_id)
    if review is None or review.confirmed_product_id is None:
        return []
    product = session.get(Product, review.confirmed_product_id)
    if product is None:
        return []
    terms = [product.name, product.brand or "", product.model or "", product.sku or ""]
    aliases = session.execute(
        select(ProductAlias.alias).where(ProductAlias.product_id == product.id)
    ).scalars().all()
    terms.extend(aliases)
    return [t for t in terms if t]


def _get_or_create_doc(session: Session, shot: Shot) -> ShotSearchDocument:
    doc = session.execute(
        select(ShotSearchDocument).where(
            ShotSearchDocument.shot_id == shot.id,
            ShotSearchDocument.shot_generation == shot.generation,
        )
    ).scalar_one_or_none()
    if doc is None:
        doc = ShotSearchDocument(shot_id=shot.id, shot_generation=shot.generation)
        session.add(doc)
    return doc


def rebuild_shot_document(
    session: Session,
    shot_id: int,
    provider: EmbeddingProvider,
    *,
    force_reembed: bool = False,
) -> str:
    """重建单镜头检索文档（幂等）。调用方负责 session.commit()。"""
    shot = session.get(Shot, shot_id)
    if shot is None or shot.status != ShotStatus.READY:
        return "not_found"

    eff = resolve_effective(session, shot)
    doc = _get_or_create_doc(session, shot)
    doc.asset_id = shot.asset_id
    doc.effective_source = eff.source
    doc.review_status = eff.review_status
    doc.source_ai_analysis_id = eff.source_ai_analysis_id
    doc.source_review_state_id = eff.source_review_state_id
    doc.source_review_lock_version = eff.source_review_lock_version

    # rejected / unable / none → 文档排除（保留记录，便于重新开放与审计）
    if not eff.searchable:
        doc.document_status = SearchDocumentStatus.EXCLUDED
        doc.embedding_status = SearchEmbeddingStatus.PENDING
        doc.is_searchable = False
        doc.search_document = None
        doc.normalized_document = None
        doc.search_document_hash = None
        doc.embedding = None
        doc.error_message = None
        doc.indexed_at = utcnow()
        return "excluded"

    content = build_search_document(
        eff.result,
        product_terms=_product_terms(session, shot, eff),
        result_schema_version=eff.result_schema_version or 0,
    )
    identity = provider.identity()

    # 嵌入层幂等：用文档"更新前"的状态判断是否可跳过重嵌（必须在覆写 hash/身份字段之前计算）。
    # 仅当向量已就绪(completed) 且 内容哈希+嵌入身份+模板版本全同 才跳过。
    can_skip = (
        not force_reembed
        and doc.embedding is not None
        and doc.embedding_status == SearchEmbeddingStatus.COMPLETED
        and doc.search_document_hash == content.document_hash
        and doc.embedding_provider == identity.provider
        and doc.embedding_model == identity.model
        and doc.embedding_model_revision == identity.model_revision
        and doc.embedding_dimension == identity.dimension
        and doc.embedding_version == identity.embedding_version
        and doc.document_template_version == content.template_version
    )

    # 文档层：始终标 indexed + is_searchable（即使跳过重嵌或缺向量，文本仍最新、可词法检索）
    doc.document_status = SearchDocumentStatus.INDEXED
    doc.is_searchable = True
    doc.search_document = content.text
    doc.normalized_document = content.normalized_document
    doc.search_document_hash = content.document_hash
    doc.document_template_version = content.template_version
    doc.result_schema_version = eff.result_schema_version
    doc.indexed_at = utcnow()

    if can_skip:
        return "skipped"

    doc.embedding_status = SearchEmbeddingStatus.EMBEDDING

    # 健康检查：未配置/不可用/未固定 revision → 降级（文档已 indexed，仅缺向量），不计失败、不重试
    health = provider.health()
    if not health.ok:
        doc.embedding_status = SearchEmbeddingStatus.DEGRADED
        doc.embedding = None
        detail = health.detail or "embedding provider unavailable"
        doc.error_message = detail[:ERROR_MESSAGE_MAX_LEN]
        return "degraded"

    try:
        vector = provider.embed_documents([content.text])[0]
    except ProviderNotConfigured as exc:
        doc.embedding_status = SearchEmbeddingStatus.DEGRADED
        doc.embedding = None
        doc.error_message = str(exc)[:ERROR_MESSAGE_MAX_LEN]
        return "degraded"
    except _TRANSIENT as exc:
        doc.embedding_status = SearchEmbeddingStatus.FAILED
        doc.retry_count += 1
        doc.error_message = f"{exc.error_code}: {exc}"[:ERROR_MESSAGE_MAX_LEN]
        logger.warning("检索文档嵌入瞬时失败 shot=%s: %s", shot_id, exc.error_code)
        return "retry"
    except ProviderError as exc:
        # 永久错误（鉴权/坏响应/维度不符等）：记失败，不自动重试（需修配置/排障）
        doc.embedding_status = SearchEmbeddingStatus.FAILED
        doc.retry_count += 1
        doc.error_message = f"{getattr(exc, 'error_code', 'error')}: {exc}"[:ERROR_MESSAGE_MAX_LEN]
        logger.error("检索文档嵌入失败（永久）shot=%s: %s", shot_id, exc)
        return "failed"

    doc.embedding = vector
    doc.embedding_provider = identity.provider
    doc.embedding_model = identity.model
    doc.embedding_model_revision = identity.model_revision
    doc.embedding_dimension = identity.dimension
    doc.embedding_version = identity.embedding_version
    doc.normalization_version = identity.normalization_version
    doc.embedding_status = SearchEmbeddingStatus.COMPLETED
    doc.embedded_at = utcnow()
    doc.error_message = None
    return "completed"


def ready_shot_ids_for_asset(session: Session, asset_id: int) -> list[int]:
    rows = session.execute(
        select(Shot.id)
        .where(Shot.asset_id == asset_id, Shot.status == ShotStatus.READY)
        .order_by(Shot.generation.desc(), Shot.sequence_no.asc())
    ).scalars().all()
    return list(rows)


def shots_needing_index(
    session: Session,
    *,
    current_embedding_version: str | None = None,
    current_template_version: int = SEARCH_DOCUMENT_TEMPLATE_VERSION,
    limit: int = 200,
) -> list[int]:
    """sweeper/回填：识别 READY 镜头中**需（重）建检索文档**的 shot_id（漏发 Celery 后兜底修复）。

    覆盖以下漂移（均经 SQL 检测，幂等器再决定是否真重嵌）：
    - 缺当前代次文档；
    - 嵌入卡住/失败/降级（pending/embedding/failed/degraded —— degraded 在 Provider 恢复后可重嵌）；
    - 文档模板版本漂移（document_template_version != 当前）；
    - 嵌入版本漂移（completed 但 embedding_version != 当前 Provider —— 模型/维度/revision 变更）；
    - 审核漂移（当前代次审核行的 id 或 review_status 与文档记录不一致 —— confirm/modify/reject/
      unable/reopen 改变了有效来源/状态）。

    注：AI 同一行(shot_id 唯一)内容变化（id 不变、parsed_result 变 → 文档哈希变）由 AI 完成钩子
    入队 + 周期性全量 backfill 覆盖（纯 SQL 无法在不重算文档的情况下检测内容哈希）。
    旧 generation 的文档随旧 Shot 级联删除（见 media._finalize），不会残留为 searchable。
    """
    SSD = ShotSearchDocument
    doc_join = and_(SSD.shot_id == Shot.id, SSD.shot_generation == Shot.generation)

    # 审核漂移：当前代次审核行的 id / review_status / lock_version 任一与文档记录不一致。
    # lock_version 在确认/修改/驳回/无法/重开后均自增（apply_review），故能捕获同一行内的
    # confirmed_result / confirmed_product / review_status / stale 变化（即使审核钩子丢失）。
    review_drift = exists(
        select(ShotReviewState.id).where(
            ShotReviewState.shot_id == Shot.id,
            ShotReviewState.shot_generation == Shot.generation,
            or_(
                ShotReviewState.id.is_distinct_from(SSD.source_review_state_id),
                cast(ShotReviewState.review_status, Text).is_distinct_from(SSD.review_status),
                ShotReviewState.lock_version.is_distinct_from(SSD.source_review_lock_version),
            ),
        )
    )

    conds: list[Any] = [
        SSD.id.is_(None),  # 缺当前代次文档
        SSD.embedding_status.in_(
            [
                SearchEmbeddingStatus.PENDING,
                SearchEmbeddingStatus.EMBEDDING,
                SearchEmbeddingStatus.FAILED,
                SearchEmbeddingStatus.DEGRADED,
            ]
        ),
        SSD.document_template_version.is_distinct_from(current_template_version),
        review_drift,
    ]
    if current_embedding_version is not None:
        conds.append(
            and_(
                SSD.embedding_status == SearchEmbeddingStatus.COMPLETED,
                SSD.embedding_version.is_distinct_from(current_embedding_version),
            )
        )

    stmt = (
        select(Shot.id)
        .outerjoin(SSD, doc_join)
        .where(Shot.status == ShotStatus.READY, or_(*conds))
        .order_by(Shot.id.asc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


__all__ = [
    "build_embedding_provider",
    "resolve_effective",
    "rebuild_shot_document",
    "ready_shot_ids_for_asset",
    "shots_needing_index",
]
