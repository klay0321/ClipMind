"""Gate B：搜索 / 画面描述匹配 / 建议 / 索引状态与重建 路由。

注册前缀 /api（见 main.py）。当前无鉴权体系——重建等管理端点不伪造用户权限，
危险操作（全量回填 / 强制重嵌）通过显式参数控制；PR-07 前的本地管理端限制见 SEMANTIC_SEARCH.md。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas.search import (
    DescriptionMatchRequest,
    DescriptionMatchResponse,
    IndexStatusResponse,
    RebuildAcceptedResponse,
    ShotSearchRequest,
    ShotSearchResponse,
    SuggestionsResponse,
)
from app.services import search_index_service, search_service
from app.services.search_providers import (
    get_query_embedding_provider,
    get_query_parser_for_settings,
)

router = APIRouter(tags=["search"])


@router.post("/search/shots", response_model=ShotSearchResponse)
async def search_shots(
    request: ShotSearchRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ShotSearchResponse:
    """自然语言 + 结构化条件的混合检索（向量/词法/标签/产品融合）。"""
    parser = get_query_parser_for_settings(settings)
    embedding_provider = get_query_embedding_provider(settings)
    return await search_service.run_shot_search(
        db, request, parser=parser, embedding_provider=embedding_provider, settings=settings
    )


@router.post("/match/description", response_model=DescriptionMatchResponse)
async def match_description(
    request: DescriptionMatchRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DescriptionMatchResponse:
    """画面描述匹配：复用混合检索候选，叠加描述匹配维度与推荐等级。"""
    parser = get_query_parser_for_settings(settings)
    embedding_provider = get_query_embedding_provider(settings)
    return await search_service.run_description_match(
        db, request, parser=parser, embedding_provider=embedding_provider, settings=settings
    )


@router.get("/search/suggestions", response_model=SuggestionsResponse)
async def search_suggestions(
    q: str | None = Query(None, description="前缀/子串（归一匹配）；空则返回热门建议"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> SuggestionsResponse:
    """搜索建议：来自产品/别名/品牌/有效标签（不实现 SearchHistory）。"""
    return await search_index_service.get_suggestions(db, q, limit)


@router.get("/search/index/status", response_model=IndexStatusResponse)
async def index_status(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IndexStatusResponse:
    """检索索引状态：文档/嵌入计数、版本一致性、provider 健康。"""
    embedding_provider = get_query_embedding_provider(settings)
    return await search_index_service.get_index_status(db, embedding_provider)


@router.post("/search/index/rebuild/shot/{shot_id}", response_model=RebuildAcceptedResponse)
async def rebuild_shot(
    shot_id: int,
    force_reembed: bool = Query(False, description="强制重嵌（即使内容/模型未变）"),
) -> RebuildAcceptedResponse:
    """单镜头检索文档重建（入队 search 队列）。"""
    return search_index_service.rebuild_shot(shot_id, force_reembed)


@router.post("/search/index/rebuild/asset/{asset_id}", response_model=RebuildAcceptedResponse)
async def rebuild_asset(
    asset_id: int,
    force_reembed: bool = Query(False),
) -> RebuildAcceptedResponse:
    """单素材全镜头检索文档重建（入队 search 队列）。"""
    return search_index_service.rebuild_asset(asset_id, force_reembed)


@router.post("/search/index/sweep", response_model=RebuildAcceptedResponse)
async def sweep_index(
    limit: int = Query(500, ge=1, le=5000),
    force_reembed: bool = Query(False),
) -> RebuildAcceptedResponse:
    """兜底扫描：重建缺失/降级/版本漂移/审核漂移的检索文档。"""
    return search_index_service.sweep(limit, force_reembed)


@router.post("/search/index/backfill", response_model=RebuildAcceptedResponse)
async def backfill_index(
    only_failed: bool = Query(False, description="仅重建嵌入失败的文档"),
    force_reembed: bool = Query(False, description="强制重嵌（模型升级用，谨慎）"),
    limit: int = Query(1000, ge=1, le=20000),
) -> RebuildAcceptedResponse:
    """全量 / 仅失败回填（有界批次）。危险操作需显式参数；超大库用离线脚本。"""
    return search_index_service.backfill(only_failed, force_reembed, limit)
