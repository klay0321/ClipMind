"""P2a 素材级检索（整条视频 / 图片）。

独立于镜头检索链路的轻路径（不触碰 PR-E/E.1 精调过的 shot 排序）：
- 词法通道：pg_trgm 相似度 over asset_search_document.normalized_document；
- 语义通道：查询向量 HNSW 余弦 over 同表 embedding；
- 融合复用 clipmind_shared.search.scoring.score_candidates（纯逻辑，目标无关；
  Candidate.shot_id 字段在此承载 asset_id）；
- 过滤：media_kind / source_directory_id / product_family_id（product_media_link
  素材级 EXISTS）。不做 usage-aware / 审核加权（素材级无此语义）。
"""

from __future__ import annotations

import time

from clipmind_shared.ai.embedding import EmbeddingProvider
from clipmind_shared.ai.providers.base import ProviderError
from clipmind_shared.models import Asset, AssetSearchDocument, ProductMediaLink
from clipmind_shared.models.enums import SearchEmbeddingStatus
from clipmind_shared.review.normalize import normalize_name
from clipmind_shared.search.scoring import Candidate, paginate, score_candidates
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.schemas.search import (
    AssetSearchRequest,
    AssetSearchResponse,
    AssetSearchResultItem,
)
from app.services import product_media_service


def _like_escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _base(request: AssetSearchRequest):
    stmt = (
        select(Asset, AssetSearchDocument)
        .select_from(Asset)
        .join(AssetSearchDocument, AssetSearchDocument.asset_id == Asset.id)
        .where(AssetSearchDocument.is_searchable.is_(True))
    )
    if request.media_kind:
        stmt = stmt.where(Asset.media_kind == request.media_kind)
    if request.source_directory_id is not None:
        stmt = stmt.where(Asset.source_directory_id == request.source_directory_id)
    if request.product_family_id is not None:
        stmt = stmt.where(
            select(ProductMediaLink.id)
            .where(
                ProductMediaLink.asset_id == Asset.id,
                ProductMediaLink.family_id == request.product_family_id,
            )
            .exists()
        )
    return stmt


async def run_asset_search(
    db: AsyncSession,
    request: AssetSearchRequest,
    *,
    embedding_provider: EmbeddingProvider,
    settings: Settings,
) -> AssetSearchResponse:
    started = time.perf_counter()
    pool = max(settings.search_candidate_pool, request.page * request.page_size)
    query = (request.query or "").strip()
    nq = normalize_name(query)

    # 语义向量（失败降级为纯词法，不假失败）
    qvec = None
    embedding_status = "unavailable"
    if query:
        health = embedding_provider.health()
        if health.ok:
            try:
                qvec = await run_in_threadpool(embedding_provider.embed_query, query)
                embedding_status = "ok"
            except ProviderError:
                embedding_status = "degraded"
            except Exception:  # noqa: BLE001
                embedding_status = "degraded"
        else:
            embedding_status = "degraded"

    cands: dict[int, Candidate] = {}

    def _get(aid: int) -> Candidate:
        c = cands.get(aid)
        if c is None:
            # Candidate.shot_id 字段承载 asset_id（scoring 为纯逻辑，目标无关）
            c = Candidate(shot_id=aid, quality_score=1.0)
            cands[aid] = c
        return c

    # 词法通道
    if nq:
        nd = AssetSearchDocument.normalized_document
        sim = func.similarity(nd, nq) if nq else literal(0.0)
        recall = [nd.op("%")(nq), nd.ilike(f"%{_like_escape(nq)}%", escape="\\")]
        stmt = (
            _base(request)
            .where(nd.isnot(None), or_(*recall))
            .order_by(sim.desc(), Asset.id)
            .limit(pool)
        )
        stmt = stmt.with_only_columns(Asset.id, sim.label("score"))
        rows = (await db.execute(stmt)).all()
        for aid, score in rows:
            _get(int(aid)).lexical_score = float(score or 0.0)

    # 语义通道
    if qvec is not None:
        dist = AssetSearchDocument.embedding.cosine_distance(qvec)
        stmt = (
            _base(request)
            .where(
                AssetSearchDocument.embedding.isnot(None),
                AssetSearchDocument.embedding_status == SearchEmbeddingStatus.COMPLETED,
                func.length(
                    func.coalesce(func.trim(AssetSearchDocument.normalized_document), "")
                )
                > 0,
            )
            .order_by(dist.asc(), Asset.id)
            .limit(pool)
        )
        stmt = stmt.with_only_columns(Asset.id, dist.label("distance"))
        rows = (await db.execute(stmt)).all()
        for aid, distance in rows:
            _get(int(aid)).semantic_score = max(0.0, 1.0 - float(distance))

    # 空查询：浏览模式（最新可搜素材）
    if not query:
        stmt = (
            _base(request)
            .order_by(AssetSearchDocument.indexed_at.desc().nulls_last(), Asset.id.desc())
            .limit(pool)
        )
        stmt = stmt.with_only_columns(Asset.id)
        for (aid,) in (await db.execute(stmt)).all():
            _get(int(aid))

    ordered = score_candidates(list(cands.values()), active_channels=["lexical", "semantic"])
    total = len(ordered)
    page_items = paginate(ordered, request.page, request.page_size)
    ids = [c.shot_id for c in page_items]

    # 页内富集：素材信息 + 文档摘录 + 产品名
    items: list[AssetSearchResultItem] = []
    if ids:
        rows = (
            await db.execute(
                select(Asset, AssetSearchDocument)
                .join(AssetSearchDocument, AssetSearchDocument.asset_id == Asset.id)
                .where(Asset.id.in_(ids))
            )
        ).all()
        by_id = {int(a.id): (a, d) for a, d in rows}
        product_names = await product_media_service.product_names_for_assets(db, ids)
        for c in page_items:
            pair = by_id.get(c.shot_id)
            if pair is None:
                continue
            asset, doc = pair
            excerpt = (doc.search_document or "").strip().replace("\n", " ")
            items.append(
                AssetSearchResultItem(
                    asset_id=asset.id,
                    filename=asset.filename,
                    media_kind=asset.media_kind,
                    duration=asset.duration,
                    source_directory_id=asset.source_directory_id,
                    has_poster=bool(asset.poster_path),
                    score=round(c.final_score, 6),
                    semantic_score=(
                        round(c.semantic_score, 6) if c.semantic_score is not None else None
                    ),
                    lexical_score=(
                        round(c.lexical_score, 6) if c.lexical_score is not None else None
                    ),
                    document_excerpt=excerpt[:200] or None,
                    effective_source=doc.effective_source,
                    product_names=product_names.get(asset.id, []),
                )
            )

    return AssetSearchResponse(
        items=items,
        total=total,
        page=request.page,
        page_size=request.page_size,
        embedding_status=embedding_status,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
