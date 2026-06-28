"""导出路由：导出状态查询 + 下载（附件，支持中文文件名）。"""

from __future__ import annotations

from clipmind_shared.models import Export
from clipmind_shared.models.enums import EXPORT_KIND_CLIP, ExportStatus
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.export import ExportOut, to_export_out
from app.services import export_center_service, files

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/{export_id}", response_model=ExportOut)
async def get_export(export_id: int, db: AsyncSession = Depends(get_db)) -> ExportOut:
    export = await db.get(Export, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="导出不存在")
    return to_export_out(export)


@router.get("/{export_id}/download")
async def download_export(export_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    export = await db.get(Export, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="导出不存在")
    if export.status != ExportStatus.COMPLETED or not export.output_path:
        raise HTTPException(status_code=409, detail="导出尚未完成")
    download_name = export.filename or "clip.mp4"
    response = files.serve_derived(
        export.output_path,
        media_type="video/mp4",
        download_name=download_name,
        immutable=True,
    )
    await export_center_service.record_download(db, EXPORT_KIND_CLIP, export_id)
    return response
