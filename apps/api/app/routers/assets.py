"""素材路由：分页列表（搜索/筛选）+ 详情 + 单素材重扫。"""

from __future__ import annotations

from clipmind_shared.models.enums import AssetStatus
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.asset import AssetOut, RescanAcceptedOut
from app.schemas.common import Page
from app.services import asset_service, scan_dispatch

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=Page[AssetOut])
async def list_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, description="文件名模糊搜索"),
    status: AssetStatus | None = Query(None),
    source_directory_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Page[AssetOut]:
    items, total = await asset_service.list_assets(
        db,
        page=page,
        page_size=page_size,
        q=q,
        status=status,
        source_directory_id=source_directory_id,
    )
    return Page[AssetOut](
        items=[AssetOut.model_validate(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{asset_id}", response_model=AssetOut)
async def get_asset(asset_id: int, db: AsyncSession = Depends(get_db)) -> AssetOut:
    asset = await asset_service.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    return AssetOut.model_validate(asset)


@router.post(
    "/{asset_id}/rescan",
    response_model=RescanAcceptedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rescan_asset(
    asset_id: int, db: AsyncSession = Depends(get_db)
) -> RescanAcceptedOut:
    asset = await asset_service.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    try:
        task_id = await scan_dispatch.request_rescan_asset(asset.id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"无法入队重扫任务: {exc}") from exc
    return RescanAcceptedOut(asset_id=asset.id, celery_task_id=task_id)
