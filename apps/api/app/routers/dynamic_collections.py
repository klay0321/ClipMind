"""PR-06B 动态集合路由（注册前缀 /api）。

创建/列表挂在项目下（/projects/{project_id}/dynamic-collections）；单条操作与 re-run 用全局 id。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas.dynamic_collection import (
    DynamicCollectionCreate,
    DynamicCollectionOut,
    DynamicCollectionPage,
    DynamicCollectionUpdate,
)
from app.services import dynamic_collection_service
from app.services.search_providers import (
    get_query_embedding_provider,
    get_query_parser_for_settings,
)

router = APIRouter(tags=["dynamic-collections"])


@router.post(
    "/projects/{project_id}/dynamic-collections",
    response_model=DynamicCollectionOut, status_code=201,
)
async def create_dynamic_collection(
    project_id: int, req: DynamicCollectionCreate, db: AsyncSession = Depends(get_db)
) -> DynamicCollectionOut:
    obj = await dynamic_collection_service.create(db, project_id, req)
    return DynamicCollectionOut.model_validate(obj, from_attributes=True)


@router.get(
    "/projects/{project_id}/dynamic-collections", response_model=DynamicCollectionPage
)
async def list_dynamic_collections(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
) -> DynamicCollectionPage:
    rows, total = await dynamic_collection_service.list_for_project(
        db, project_id, page=page, page_size=page_size
    )
    return DynamicCollectionPage(
        items=[DynamicCollectionOut.model_validate(r, from_attributes=True) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.get("/dynamic-collections/{dyn_id}", response_model=DynamicCollectionOut)
async def get_dynamic_collection(
    dyn_id: int, db: AsyncSession = Depends(get_db)
) -> DynamicCollectionOut:
    obj = await dynamic_collection_service.get_or_404(db, dyn_id)
    return DynamicCollectionOut.model_validate(obj, from_attributes=True)


@router.patch("/dynamic-collections/{dyn_id}", response_model=DynamicCollectionOut)
async def update_dynamic_collection(
    dyn_id: int, req: DynamicCollectionUpdate, db: AsyncSession = Depends(get_db)
) -> DynamicCollectionOut:
    obj = await dynamic_collection_service.update(db, dyn_id, req)
    return DynamicCollectionOut.model_validate(obj, from_attributes=True)


@router.delete("/dynamic-collections/{dyn_id}", status_code=204)
async def delete_dynamic_collection(dyn_id: int, db: AsyncSession = Depends(get_db)):
    await dynamic_collection_service.delete(db, dyn_id)


@router.get("/dynamic-collections/{dyn_id}/shots", response_model=None)
async def run_dynamic_collection_shots(
    dyn_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
):
    """实时调当前搜索服务计算成员（后端分页；返回与搜索响应同形）。"""
    parser = get_query_parser_for_settings(settings)
    embedding_provider = get_query_embedding_provider(settings)
    return await dynamic_collection_service.run_shots(
        db, dyn_id, page=page, page_size=page_size,
        settings=settings, parser=parser, embedding_provider=embedding_provider,
    )
