"""PR-06B 收藏路由（注册前缀 /api）。删除收藏只删 favorite，不删 Asset/Shot。"""

from __future__ import annotations

from clipmind_shared.models.enums import FavoriteTargetType
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.favorite import FavoriteCreate, FavoriteOut, FavoritePage
from app.services import favorite_service

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.post("", response_model=FavoriteOut, status_code=201)
async def create_favorite(req: FavoriteCreate, db: AsyncSession = Depends(get_db)) -> FavoriteOut:
    fav = await favorite_service.create(db, req)
    return FavoriteOut.model_validate(fav, from_attributes=True)


@router.get("", response_model=FavoritePage)
async def list_favorites(
    db: AsyncSession = Depends(get_db),
    target_type: FavoriteTargetType | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
) -> FavoritePage:
    items, total = await favorite_service.list_favorites(
        db, page=page, page_size=page_size, target_type=target_type
    )
    return FavoritePage(items=items, total=total, page=page, page_size=page_size)


@router.delete("/{favorite_id}", status_code=204)
async def delete_favorite(favorite_id: int, db: AsyncSession = Depends(get_db)):
    await favorite_service.delete(db, favorite_id)
