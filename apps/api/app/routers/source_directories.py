"""素材源目录路由：CRUD + 扫描 + 状态。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.source_directory import (
    ScanRunOut,
    ScanStatusOut,
    SourceDirectoryCreate,
    SourceDirectoryOut,
    SourceDirectoryUpdate,
)
from app.services import scan_dispatch, source_directory_service

router = APIRouter(prefix="/source-directories", tags=["source-directories"])


async def _get_or_404(db: AsyncSession, sd_id: int):
    sd = await source_directory_service.get_source_directory(db, sd_id)
    if sd is None:
        raise HTTPException(status_code=404, detail="素材目录不存在")
    return sd


@router.get("", response_model=list[SourceDirectoryOut])
async def list_source_directories(db: AsyncSession = Depends(get_db)):
    return await source_directory_service.list_source_directories(db)


@router.post("", response_model=SourceDirectoryOut, status_code=status.HTTP_201_CREATED)
async def create_source_directory(
    payload: SourceDirectoryCreate, db: AsyncSession = Depends(get_db)
):
    # PathNotAllowed 由全局异常处理器映射为 422
    return await source_directory_service.create_source_directory(db, payload)


@router.get("/{sd_id}", response_model=SourceDirectoryOut)
async def get_source_directory(sd_id: int, db: AsyncSession = Depends(get_db)):
    return await _get_or_404(db, sd_id)


@router.put("/{sd_id}", response_model=SourceDirectoryOut)
async def update_source_directory(
    sd_id: int, payload: SourceDirectoryUpdate, db: AsyncSession = Depends(get_db)
):
    sd = await _get_or_404(db, sd_id)
    return await source_directory_service.update_source_directory(db, sd, payload)


@router.post("/{sd_id}/scan", response_model=ScanRunOut, status_code=status.HTTP_202_ACCEPTED)
async def scan_source_directory(sd_id: int, db: AsyncSession = Depends(get_db)):
    sd = await _get_or_404(db, sd_id)
    try:
        run = await scan_dispatch.request_scan(db, sd)
    except Exception as exc:  # noqa: BLE001 - 入队失败转 503
        raise HTTPException(status_code=503, detail=f"无法入队扫描任务: {exc}") from exc
    return run


@router.get("/{sd_id}/status", response_model=ScanStatusOut)
async def get_scan_status(sd_id: int, db: AsyncSession = Depends(get_db)):
    sd = await _get_or_404(db, sd_id)
    latest = await scan_dispatch.get_latest_scan_run(db, sd.id)
    return ScanStatusOut(
        source_directory_id=sd.id,
        scan_status=sd.scan_status,
        last_scanned_at=sd.last_scanned_at,
        latest_run=ScanRunOut.model_validate(latest) if latest else None,
    )
