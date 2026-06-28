"""镜头路由：列表 + 详情 + 派生文件服务（缩略图/关键帧/代理 Range）+ 片段导出。"""

from __future__ import annotations

from clipmind_shared.models import Project
from clipmind_shared.models.enums import ShotStatus
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.common import Page
from app.schemas.export import ExportAcceptedOut, ExportCreate
from app.schemas.shot import (
    ShotDetailOut,
    ShotOut,
    to_shot_detail,
    to_shot_out,
)
from app.services import files, shot_dispatch, shot_service

router = APIRouter(prefix="/shots", tags=["shots"])


@router.get("", response_model=Page[ShotOut])
async def list_shots(
    asset_id: int | None = Query(None),
    status: ShotStatus | None = Query(None, description="默认仅返回 ready 镜头"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Page[ShotOut]:
    effective_status = ShotStatus.READY if status is None else status
    items, total = await shot_service.list_shots(
        db, asset_id=asset_id, status=effective_status, page=page, page_size=page_size
    )
    names = await shot_service.filenames_for_assets(db, [s.asset_id for s in items])
    return Page[ShotOut](
        items=[to_shot_out(s, names.get(s.asset_id)) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{shot_id}", response_model=ShotDetailOut)
async def get_shot(shot_id: int, db: AsyncSession = Depends(get_db)) -> ShotDetailOut:
    shot = await shot_service.get_shot(db, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    asset = await shot_service.get_asset(db, shot.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="来源素材不存在")
    return to_shot_detail(shot, asset)


@router.get("/{shot_id}/thumbnail")
async def get_thumbnail(shot_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    shot = await shot_service.get_shot(db, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    return files.serve_derived(shot.thumbnail_path, media_type="image/webp")


@router.get("/{shot_id}/keyframe")
async def get_keyframe(shot_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    shot = await shot_service.get_shot(db, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    return files.serve_derived(shot.keyframe_path, media_type="image/webp")


@router.get("/{shot_id}/keyframe/{index}")
async def get_keyframe_at(
    shot_id: int, index: int, db: AsyncSession = Depends(get_db)
) -> FileResponse:
    """关键帧条第 index 帧（0 起）。供镜头详情多帧预览。"""
    shot = await shot_service.get_shot(db, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    paths = shot.keyframe_paths or []
    if index < 0 or index >= len(paths):
        raise HTTPException(status_code=404, detail="关键帧不存在")
    return files.serve_derived(paths[index], media_type="image/webp")


@router.get("/{shot_id}/preview")
async def get_preview(shot_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    """代理视频预览（浏览器可播放，FileResponse 原生支持 HTTP Range/206/416）。"""
    shot = await shot_service.get_shot(db, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    return files.serve_derived(shot.proxy_path, media_type="video/mp4")


@router.post(
    "/{shot_id}/export",
    response_model=ExportAcceptedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def export_shot(
    shot_id: int,
    body: ExportCreate | None = None,
    db: AsyncSession = Depends(get_db),
) -> ExportAcceptedOut:
    shot = await shot_service.get_shot(db, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    mode = (body.mode if body else "reencode")
    project_id = body.project_id if body else None
    if project_id is not None and await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        export = await shot_dispatch.request_export(
            db, shot, mode=mode, project_id=project_id
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"无法入队导出任务: {exc}") from exc
    return ExportAcceptedOut(
        export_id=export.id,
        shot_id=shot.id,
        status=export.status,
        celery_task_id=export.celery_task_id,
    )
