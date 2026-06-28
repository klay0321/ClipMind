"""PR-06B 保存搜索路由（注册前缀 /api）。"""

from __future__ import annotations

from clipmind_shared.models.enums import SearchKind
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas.saved_search import (
    SavedSearchCreate,
    SavedSearchOut,
    SavedSearchPage,
    SavedSearchUpdate,
)
from app.services import saved_search_service
from app.services.search_providers import (
    get_query_embedding_provider,
    get_query_parser_for_settings,
)

router = APIRouter(prefix="/saved-searches", tags=["saved-searches"])


@router.post("", response_model=SavedSearchOut, status_code=201)
async def create_saved_search(
    req: SavedSearchCreate, db: AsyncSession = Depends(get_db)
) -> SavedSearchOut:
    obj = await saved_search_service.create(db, req)
    return SavedSearchOut.model_validate(obj, from_attributes=True)


@router.get("", response_model=SavedSearchPage)
async def list_saved_searches(
    db: AsyncSession = Depends(get_db),
    project_id: int | None = Query(default=None),
    search_kind: SearchKind | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
) -> SavedSearchPage:
    rows, total = await saved_search_service.list_saved(
        db, page=page, page_size=page_size, project_id=project_id, search_kind=search_kind
    )
    return SavedSearchPage(
        items=[SavedSearchOut.model_validate(r, from_attributes=True) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.get("/{saved_id}", response_model=SavedSearchOut)
async def get_saved_search(saved_id: int, db: AsyncSession = Depends(get_db)) -> SavedSearchOut:
    obj = await saved_search_service.get_or_404(db, saved_id)
    return SavedSearchOut.model_validate(obj, from_attributes=True)


@router.patch("/{saved_id}", response_model=SavedSearchOut)
async def update_saved_search(
    saved_id: int, req: SavedSearchUpdate, db: AsyncSession = Depends(get_db)
) -> SavedSearchOut:
    obj = await saved_search_service.update(db, saved_id, req)
    return SavedSearchOut.model_validate(obj, from_attributes=True)


@router.delete("/{saved_id}", status_code=204)
async def delete_saved_search(saved_id: int, db: AsyncSession = Depends(get_db)):
    await saved_search_service.delete(db, saved_id)


@router.post("/{saved_id}/run", response_model=None)
async def run_saved_search(
    saved_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
):
    """按当前真实搜索服务重新运行（返回与 /search/shots 或 /match/description 同形）。"""
    parser = get_query_parser_for_settings(settings)
    embedding_provider = get_query_embedding_provider(settings)
    return await saved_search_service.run(
        db, saved_id, page=page, page_size=page_size,
        settings=settings, parser=parser, embedding_provider=embedding_provider,
    )
