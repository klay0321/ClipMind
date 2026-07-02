"""PR-B 最终成片路由（注册前缀 /api，见 main.py）。

FinalVideo CRUD + 归档/恢复（无物理删除接口：删除 = 归档，血缘保留）+
Usage 子资源（列表 / 手工添加）+ 从项目生成候选 + 血缘全景。

页面必须如实展示：项目中已选择或锁定的镜头只会生成候选引用（proposed），
人工确认后才计入正式使用次数。
"""

from __future__ import annotations

from clipmind_shared.models.enums import FinalVideoStatus, FinalVideoUsageStatus
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.final_video import (
    FinalVideoCreateRequest,
    FinalVideoLineageOut,
    FinalVideoListResponse,
    FinalVideoOut,
    FinalVideoUpdateRequest,
    ProposeFromProjectOut,
    ProposeFromProjectRequest,
    UsageCreateRequest,
    UsageListResponse,
    UsageOut,
)
from app.services import final_video_service

router = APIRouter(prefix="/final-videos", tags=["final-videos"])


async def _one_out(db: AsyncSession, fv) -> FinalVideoOut:
    return (await final_video_service._to_final_video_outs(db, [fv]))[0]


@router.post("", response_model=FinalVideoOut, status_code=status.HTTP_201_CREATED)
async def create_final_video(
    req: FinalVideoCreateRequest, db: AsyncSession = Depends(get_db)
) -> FinalVideoOut:
    fv = await final_video_service.create_final_video(db, req)
    return await _one_out(db, fv)


@router.get("", response_model=FinalVideoListResponse)
async def list_final_videos(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: FinalVideoStatus | None = Query(None, alias="status"),
    project_id: int | None = Query(None),
    q: str | None = Query(None, max_length=200),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> FinalVideoListResponse:
    rows, total = await final_video_service.list_final_videos(
        db,
        page=page,
        page_size=page_size,
        status=status_filter,
        project_id=project_id,
        q=q,
        include_archived=include_archived,
    )
    items = await final_video_service._to_final_video_outs(db, rows)
    return FinalVideoListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{final_video_id}", response_model=FinalVideoOut)
async def get_final_video(
    final_video_id: int, db: AsyncSession = Depends(get_db)
) -> FinalVideoOut:
    fv = await final_video_service.get_final_video_or_404(db, final_video_id)
    return await _one_out(db, fv)


@router.patch("/{final_video_id}", response_model=FinalVideoOut)
async def update_final_video(
    final_video_id: int,
    req: FinalVideoUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> FinalVideoOut:
    fv = await final_video_service.update_final_video(db, final_video_id, req)
    return await _one_out(db, fv)


@router.post("/{final_video_id}/archive", response_model=FinalVideoOut)
async def archive_final_video(
    final_video_id: int, db: AsyncSession = Depends(get_db)
) -> FinalVideoOut:
    fv = await final_video_service.archive_final_video(db, final_video_id)
    return await _one_out(db, fv)


@router.post("/{final_video_id}/restore", response_model=FinalVideoOut)
async def restore_final_video(
    final_video_id: int, db: AsyncSession = Depends(get_db)
) -> FinalVideoOut:
    fv = await final_video_service.restore_final_video(db, final_video_id)
    return await _one_out(db, fv)


# ============================ Usage 子资源 ============================


@router.get("/{final_video_id}/usages", response_model=UsageListResponse)
async def list_usages(
    final_video_id: int,
    status_filter: FinalVideoUsageStatus | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> UsageListResponse:
    rows, total = await final_video_service.list_usages(
        db, final_video_id, status=status_filter
    )
    items = await final_video_service._to_usage_outs(db, rows)
    return UsageListResponse(items=items, total=total)


@router.post(
    "/{final_video_id}/usages",
    response_model=UsageOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_usage(
    final_video_id: int,
    req: UsageCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> UsageOut:
    usage = await final_video_service.create_manual_usage(db, final_video_id, req)
    return (await final_video_service._to_usage_outs(db, [usage]))[0]


@router.post(
    "/{final_video_id}/propose-from-project", response_model=ProposeFromProjectOut
)
async def propose_from_project(
    final_video_id: int,
    req: ProposeFromProjectRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ProposeFromProjectOut:
    return await final_video_service.propose_from_project(
        db,
        final_video_id,
        actor_label=req.actor_label if req is not None else None,
    )


@router.get("/{final_video_id}/lineage", response_model=FinalVideoLineageOut)
async def get_lineage(
    final_video_id: int, db: AsyncSession = Depends(get_db)
) -> FinalVideoLineageOut:
    return await final_video_service.get_final_video_lineage(db, final_video_id)
