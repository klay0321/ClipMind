"""PR-06B 统一导出中心 + 多镜头 ZIP 打包 路由（注册前缀 /api）。

- /export-center：聚合 clip/script/bundle 三类导出（只读），支持 retry（仅 failed）/delete
  （仅 completed/failed，连带安全删派生文件，绝不碰源）。
- /exports/bundle：创建/查询/下载多镜头 ZIP 打包（进入统一导出中心）。
"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models import BundleExport
from clipmind_shared.models.enums import EXPORT_KIND_BUNDLE, ExportStatus
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.bundle import BundleAcceptedOut, BundleCreateRequest
from app.schemas.export_center import (
    ExportActionOut,
    ExportCenterItem,
    ExportCenterPage,
)
from app.services import bundle_service, export_center_service, files
from app.services.export_center_service import MAX_PAGE_SIZE_GUARD

router = APIRouter(tags=["export-center"])


# ===== 多镜头 ZIP 打包（须在 /exports/{id} 之前注册以避免路由冲突）=====


@router.post("/exports/bundle", response_model=BundleAcceptedOut, status_code=202)
async def create_bundle(
    req: BundleCreateRequest, db: AsyncSession = Depends(get_db)
) -> BundleAcceptedOut:
    bundle = await bundle_service.request_bundle(db, req)
    return BundleAcceptedOut(
        export_id=bundle.id, status=bundle.status,
        celery_task_id=bundle.celery_task_id, shot_count=len(bundle.shot_ids or []),
    )


@router.get("/exports/bundle/{bundle_id}", response_model=ExportCenterItem)
async def get_bundle(bundle_id: int, db: AsyncSession = Depends(get_db)) -> ExportCenterItem:
    return await export_center_service.get_export(db, EXPORT_KIND_BUNDLE, bundle_id)


@router.get("/exports/bundle/{bundle_id}/download")
async def download_bundle(
    bundle_id: int, db: AsyncSession = Depends(get_db)
) -> FileResponse:
    bundle = await db.get(BundleExport, bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="打包导出不存在")
    if bundle.status != ExportStatus.COMPLETED or not bundle.output_path:
        raise HTTPException(status_code=409, detail="打包尚未完成")
    response = files.serve_derived(
        bundle.output_path, media_type="application/zip",
        download_name=bundle.filename or "bundle.zip", immutable=False,
    )
    await export_center_service.record_download(db, EXPORT_KIND_BUNDLE, bundle_id)
    return response


# ============================ 统一导出中心 ============================


@router.get("/export-center", response_model=ExportCenterPage)
async def list_export_center(
    db: AsyncSession = Depends(get_db),
    kind: str | None = Query(default=None),
    status: ExportStatus | None = Query(default=None),
    project_id: int | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=MAX_PAGE_SIZE_GUARD),
) -> ExportCenterPage:
    items, total = await export_center_service.list_exports(
        db, kind=kind, status=status, project_id=project_id,
        created_from=created_from, created_to=created_to,
        page=page, page_size=page_size,
    )
    return ExportCenterPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/export-center/{kind}/{export_id}", response_model=ExportCenterItem)
async def get_export_center_item(
    kind: str, export_id: int, db: AsyncSession = Depends(get_db)
) -> ExportCenterItem:
    return await export_center_service.get_export(db, kind, export_id)


@router.post("/export-center/{kind}/{export_id}/retry", response_model=ExportActionOut)
async def retry_export(
    kind: str, export_id: int, db: AsyncSession = Depends(get_db)
) -> ExportActionOut:
    return await export_center_service.retry_export(db, kind, export_id)


@router.delete("/export-center/{kind}/{export_id}", status_code=204)
async def delete_export(kind: str, export_id: int, db: AsyncSession = Depends(get_db)):
    await export_center_service.delete_export(db, kind, export_id)
