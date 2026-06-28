"""PR-06A 素材集合路由（注册前缀 /api，见 main.py）。

集合归属于 Project：创建/列举在 ``/projects/{project_id}/collections``；集合自身与成员在
``/collections/{collection_id}``。归档项目下的写操作由 service 层统一返回 409。
删除集合只删集合与成员关联，绝不删除 Shot。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.collection import (
    CollectionCreateRequest,
    CollectionListResponse,
    CollectionOut,
    CollectionUpdateRequest,
)
from app.schemas.common import Page
from app.schemas.project import BatchResultOut, MemberBatchRequest, MemberReorderRequest
from app.schemas.shot import ShotOut, to_shot_out
from app.services import collection_service

router = APIRouter(tags=["collections"])


def _collection_out(coll, shot_count: int) -> CollectionOut:
    out = CollectionOut.model_validate(coll)
    out.shot_count = shot_count
    return out


# ============================ 项目内集合：创建 / 列举 ============================


@router.post(
    "/projects/{project_id}/collections",
    response_model=CollectionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_collection(
    project_id: int, req: CollectionCreateRequest, db: AsyncSession = Depends(get_db)
) -> CollectionOut:
    coll = await collection_service.create_collection(db, project_id, req)
    return _collection_out(coll, 0)


@router.get(
    "/projects/{project_id}/collections", response_model=CollectionListResponse
)
async def list_collections(
    project_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> CollectionListResponse:
    rows, total, counts = await collection_service.list_collections(
        db, project_id, page=page, page_size=page_size
    )
    return CollectionListResponse(
        items=[_collection_out(c, counts.get(c.id, 0)) for c in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


# ============================ 集合自身 ============================


@router.get("/collections/{collection_id}", response_model=CollectionOut)
async def get_collection(
    collection_id: int, db: AsyncSession = Depends(get_db)
) -> CollectionOut:
    coll = await collection_service.get_collection_or_404(db, collection_id)
    count = await collection_service._shot_count(db, collection_id)
    return _collection_out(coll, count)


@router.patch("/collections/{collection_id}", response_model=CollectionOut)
async def update_collection(
    collection_id: int, req: CollectionUpdateRequest, db: AsyncSession = Depends(get_db)
) -> CollectionOut:
    coll = await collection_service.update_collection(db, collection_id, req)
    count = await collection_service._shot_count(db, collection_id)
    return _collection_out(coll, count)


@router.delete(
    "/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_collection(
    collection_id: int, db: AsyncSession = Depends(get_db)
):
    await collection_service.delete_collection(db, collection_id)


# ============================ 集合成员（镜头）============================


@router.get("/collections/{collection_id}/shots", response_model=Page[ShotOut])
async def list_collection_shots(
    collection_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Page[ShotOut]:
    rows, total = await collection_service.list_collection_shots(
        db, collection_id, page=page, page_size=page_size
    )
    return Page[ShotOut](
        items=[to_shot_out(s) for s in rows], total=total, page=page, page_size=page_size
    )


@router.post(
    "/collections/{collection_id}/shots/batch",
    response_model=BatchResultOut,
    status_code=status.HTTP_200_OK,
)
async def add_collection_shots(
    collection_id: int, req: MemberBatchRequest, db: AsyncSession = Depends(get_db)
) -> BatchResultOut:
    result = await collection_service.add_collection_shots(db, collection_id, req.ids)
    return BatchResultOut(**result)


@router.delete(
    "/collections/{collection_id}/shots/{shot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_collection_shot(
    collection_id: int, shot_id: int, db: AsyncSession = Depends(get_db)
):
    await collection_service.remove_collection_shot(db, collection_id, shot_id)


@router.post(
    "/collections/{collection_id}/shots/reorder", response_model=CollectionOut
)
async def reorder_collection_shots(
    collection_id: int, req: MemberReorderRequest, db: AsyncSession = Depends(get_db)
) -> CollectionOut:
    coll = await collection_service.reorder_collection_shots(
        db, collection_id, req.ids, req.lock_version
    )
    count = await collection_service._shot_count(db, collection_id)
    return _collection_out(coll, count)
