"""P2a 素材级检索文档索引器（search 队列纯逻辑）。

幂等地为一个 Asset 构建 ``asset_search_document``：
- 图片：来自 asset_image_analysis 的已完成解析结果（effective_source='ai'）；
- 视频：当前代次 ready 镜头**有效结果**的聚合（effective_source='aggregate'）——
  各镜头 one_line 汇入 detailed、产品/场景/动作/关键词并集；镜头层的人工审核
  语义经 resolve_effective 天然进入聚合（人工优先于 AI 不变）。
- 素材已绑定产品（product_media_link → ProductFamily）的名称/编码一并写入
  文档补充检索词：绑定产品后按产品名即可词法/语义搜到该素材。

文档层/嵌入层正交、幂等判定（哈希+嵌入身份+模板版本）、瞬时故障 retry 语义
与镜头索引器完全同款。返回：completed | degraded | excluded | skipped |
failed | retry | not_found。
"""

from __future__ import annotations

import logging

from clipmind_shared.ai.embedding import EmbeddingProvider
from clipmind_shared.ai.providers.base import ProviderError, ProviderNotConfigured
from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    AssetImageAnalysis,
    AssetSearchDocument,
    ProductFamily,
    ProductMediaLink,
    Shot,
)
from clipmind_shared.models.enums import (
    AIShotAnalysisStatus,
    AssetStatus,
    SearchDocumentStatus,
    SearchEmbeddingStatus,
    ShotStatus,
)
from clipmind_shared.search import build_search_document
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipmind_worker.search.indexer import _TRANSIENT, resolve_effective

logger = logging.getLogger(__name__)

# 素材级聚合文档模板版本（独立于镜头模板版本演进）
ASSET_DOC_TEMPLATE_VERSION = 1

# 聚合上限：防超长视频文档爆炸（e5 输入有效长度有限，头部信息已足够）
_AGG_MAX_ONE_LINES = 60
_AGG_MAX_TERMS = 40

_INDEXABLE_STATUSES = (AssetStatus.INDEXED, AssetStatus.SHOT_SPLIT, AssetStatus.AI_ANALYZING)


def _get_or_create_doc(session: Session, asset: Asset) -> AssetSearchDocument:
    doc = session.execute(
        select(AssetSearchDocument).where(AssetSearchDocument.asset_id == asset.id)
    ).scalar_one_or_none()
    if doc is None:
        doc = AssetSearchDocument(asset_id=asset.id, media_kind=asset.media_kind)
        session.add(doc)
    doc.media_kind = asset.media_kind
    return doc


def _asset_product_terms(session: Session, asset_id: int) -> list[str]:
    """素材绑定产品的检索补充词（目录 ProductFamily 名称/编码，去重保序）。"""
    rows = session.execute(
        select(ProductFamily.name_zh, ProductFamily.name_en, ProductFamily.code)
        .join(ProductMediaLink, ProductMediaLink.family_id == ProductFamily.id)
        .where(ProductMediaLink.asset_id == asset_id)
    ).all()
    terms: list[str] = []
    for name_zh, name_en, code in rows:
        for t in (name_zh, name_en, code):
            if t and t not in terms:
                terms.append(t)
    return terms


def _exclude(doc: AssetSearchDocument) -> str:
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


def _image_result(session: Session, asset: Asset, doc: AssetSearchDocument) -> dict | None:
    ai = session.execute(
        select(AssetImageAnalysis).where(AssetImageAnalysis.asset_id == asset.id)
    ).scalar_one_or_none()
    if ai is None or ai.status != AIShotAnalysisStatus.COMPLETED or not ai.parsed_result:
        return None
    doc.effective_source = "ai"
    doc.source_image_analysis_id = ai.id
    doc.result_schema_version = ai.schema_version
    return dict(ai.parsed_result)


def _video_aggregate(session: Session, asset: Asset, doc: AssetSearchDocument) -> dict | None:
    shots = (
        session.execute(
            select(Shot)
            .where(
                Shot.asset_id == asset.id,
                Shot.status == ShotStatus.READY,
                Shot.retired_at.is_(None),
            )
            .order_by(Shot.sequence_no.asc())
        )
        .scalars()
        .all()
    )
    one_lines: list[str] = []
    products: list[str] = []
    scenes: list[str] = []
    actions: list[str] = []
    keywords: list[str] = []

    def _extend(dst: list[str], values) -> None:
        if values is None:
            return
        items = values if isinstance(values, list) else [values]
        for v in items:
            sv = str(v).strip()
            if sv and sv not in dst and len(dst) < _AGG_MAX_TERMS:
                dst.append(sv)

    for shot in shots:
        eff = resolve_effective(session, shot)
        if not eff.searchable or not eff.result:
            continue
        r = eff.result
        line = str(r.get("one_line") or "").strip()
        if line and line not in one_lines and len(one_lines) < _AGG_MAX_ONE_LINES:
            one_lines.append(line)
        _extend(products, r.get("product"))
        _extend(scenes, r.get("scene"))
        _extend(actions, r.get("action"))
        _extend(keywords, r.get("search_keywords"))

    if not one_lines and not products and not keywords:
        return None
    doc.effective_source = "aggregate"
    doc.source_image_analysis_id = None
    doc.result_schema_version = None
    # 聚合词统一并入 keywords：build_search_document 的 product 键期待
    # dict（单镜头结构）、scene/action 期待单值，list 会被丢弃/字符串化。
    merged_keywords: list[str] = []
    for src in (products, scenes, actions, keywords):
        for t in src:
            if t not in merged_keywords:
                merged_keywords.append(t)
    return {
        "one_line": one_lines[0] if one_lines else "",
        "detailed": "\n".join(one_lines),
        "search_keywords": merged_keywords,
    }


def rebuild_asset_level_document(
    session: Session,
    asset_id: int,
    provider: EmbeddingProvider,
    *,
    force_reembed: bool = False,
) -> str:
    """重建素材级检索文档（幂等）。调用方负责 session.commit()。"""
    asset = session.get(Asset, asset_id)
    if asset is None:
        return "not_found"
    doc = _get_or_create_doc(session, asset)
    if asset.status not in _INDEXABLE_STATUSES:
        return _exclude(doc)

    if asset.media_kind == "image":
        result = _image_result(session, asset, doc)
    else:
        result = _video_aggregate(session, asset, doc)
    if result is None:
        return _exclude(doc)

    content = build_search_document(
        result,
        product_terms=_asset_product_terms(session, asset.id),
        result_schema_version=doc.result_schema_version or 0,
    )
    if not content.text.strip():
        return _exclude(doc)

    identity = provider.identity()
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
        and doc.document_template_version == ASSET_DOC_TEMPLATE_VERSION
    )

    doc.document_status = SearchDocumentStatus.INDEXED
    doc.is_searchable = True
    doc.search_document = content.text
    doc.normalized_document = content.normalized_document
    doc.search_document_hash = content.document_hash
    doc.document_template_version = ASSET_DOC_TEMPLATE_VERSION
    doc.indexed_at = utcnow()

    if can_skip:
        return "skipped"

    doc.embedding_status = SearchEmbeddingStatus.EMBEDDING
    health = provider.health()
    if not health.ok:
        doc.embedding_status = SearchEmbeddingStatus.DEGRADED
        doc.embedding = None
        doc.error_message = (health.detail or "embedding provider unavailable")[
            :ERROR_MESSAGE_MAX_LEN
        ]
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
        logger.warning("素材级文档嵌入瞬时失败 asset=%s: %s", asset_id, exc.error_code)
        return "retry"
    except ProviderError as exc:
        doc.embedding_status = SearchEmbeddingStatus.FAILED
        doc.retry_count += 1
        doc.error_message = f"{getattr(exc, 'error_code', 'error')}: {exc}"[
            :ERROR_MESSAGE_MAX_LEN
        ]
        logger.error("素材级文档嵌入失败（永久）asset=%s: %s", asset_id, exc)
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
