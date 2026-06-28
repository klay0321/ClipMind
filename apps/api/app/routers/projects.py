"""PR-06A 项目路由（注册前缀 /api，见 main.py）。

Project CRUD + 归档/恢复 + 素材/镜头/产品成员（批量加入/移除/重排）+ 脚本归属 + 统计。
**本阶段不提供 Project 删除接口**（真正删除留待 PR-07）。归档项目除恢复外的写操作由 service 层
统一返回 409，不依赖前端限制。
"""

from __future__ import annotations

from clipmind_shared.models.enums import ProjectStatus, ReviewStatus
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.asset import AssetOut
from app.schemas.common import Page
from app.schemas.product import ProductOut
from app.schemas.project import (
    BatchResultOut,
    MemberBatchRequest,
    MemberReorderRequest,
    ProjectArchiveRequest,
    ProjectAssetItemOut,
    ProjectAssetListResponse,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectOut,
    ProjectStatsOut,
    ProjectUpdateRequest,
)
from app.schemas.script import ScriptListResponse, ScriptProjectOut
from app.schemas.shot import ShotOut, to_shot_out
from app.services import project_service, script_service

router = APIRouter(prefix="/projects", tags=["projects"])

_ALLOWED_SHOT_SOURCES = {"all", "asset", "explicit", "collection"}


def _asset_out(asset, shot_count: int) -> AssetOut:
    out = AssetOut.model_validate(asset)
    out.shot_count = shot_count
    out.has_poster = bool(asset.poster_path)
    return out


# ============================ Project CRUD ============================


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    req: ProjectCreateRequest, db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    proj = await project_service.create_project(db, req)
    return ProjectOut.model_validate(proj)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: ProjectStatus | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> ProjectListResponse:
    rows, total = await project_service.list_projects(
        db, page=page, page_size=page_size, status=status_filter
    )
    return ProjectListResponse(
        items=[ProjectOut.model_validate(p) for p in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    proj = await project_service.get_project_or_404(db, project_id)
    return ProjectOut.model_validate(proj)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int, req: ProjectUpdateRequest, db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    proj = await project_service.update_project(db, project_id, req)
    return ProjectOut.model_validate(proj)


@router.post("/{project_id}/archive", response_model=ProjectOut)
async def archive_project(
    project_id: int, req: ProjectArchiveRequest, db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    proj = await project_service.archive_project(db, project_id, req.lock_version)
    return ProjectOut.model_validate(proj)


@router.post("/{project_id}/unarchive", response_model=ProjectOut)
async def unarchive_project(
    project_id: int, req: ProjectArchiveRequest, db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    proj = await project_service.unarchive_project(db, project_id, req.lock_version)
    return ProjectOut.model_validate(proj)


@router.get("/{project_id}/stats", response_model=ProjectStatsOut)
async def get_project_stats(
    project_id: int, db: AsyncSession = Depends(get_db)
) -> ProjectStatsOut:
    data = await project_service.get_project_stats(db, project_id)
    return ProjectStatsOut(**data)


# ============================ Project Assets ============================


@router.get("/{project_id}/assets", response_model=ProjectAssetListResponse)
async def list_project_assets(
    project_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ProjectAssetListResponse:
    items, total, shot_counts = await project_service.list_project_assets(
        db, project_id, page=page, page_size=page_size
    )
    return ProjectAssetListResponse(
        items=[
            ProjectAssetItemOut(
                order_index=order_index,
                asset=_asset_out(asset, shot_counts.get(asset.id, 0)),
            )
            for order_index, asset in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{project_id}/assets/batch",
    response_model=BatchResultOut,
    status_code=status.HTTP_200_OK,
)
async def add_project_assets(
    project_id: int, req: MemberBatchRequest, db: AsyncSession = Depends(get_db)
) -> BatchResultOut:
    result = await project_service.add_project_assets(db, project_id, req.ids)
    return BatchResultOut(**result)


@router.delete(
    "/{project_id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_project_asset(
    project_id: int, asset_id: int, db: AsyncSession = Depends(get_db)
):
    await project_service.remove_project_asset(db, project_id, asset_id)


@router.post("/{project_id}/assets/reorder", response_model=ProjectOut)
async def reorder_project_assets(
    project_id: int, req: MemberReorderRequest, db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    proj = await project_service.reorder_project_assets(
        db, project_id, req.ids, req.lock_version
    )
    return ProjectOut.model_validate(proj)


# ============================ Project Shots ============================


@router.get("/{project_id}/shots", response_model=Page[ShotOut])
async def list_project_shots(
    project_id: int,
    source: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    sort: str = Query("sequence"),
    product_id: int | None = Query(None),
    review_status: ReviewStatus | None = Query(None),
    risk: str | None = Query(None),
    include_excluded: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> Page[ShotOut]:
    src = source if source in _ALLOWED_SHOT_SOURCES else "all"
    rows, total = await project_service.list_project_shots(
        db,
        project_id,
        source=src,
        page=page,
        page_size=page_size,
        sort=sort,
        product_id=product_id,
        review_status=review_status,
        risk=risk,
        include_excluded=include_excluded,
    )
    return Page[ShotOut](
        items=[to_shot_out(s) for s in rows], total=total, page=page, page_size=page_size
    )


@router.post(
    "/{project_id}/shots/batch",
    response_model=BatchResultOut,
    status_code=status.HTTP_200_OK,
)
async def add_project_shots(
    project_id: int, req: MemberBatchRequest, db: AsyncSession = Depends(get_db)
) -> BatchResultOut:
    result = await project_service.add_project_shots(db, project_id, req.ids)
    return BatchResultOut(**result)


@router.delete("/{project_id}/shots/{shot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_shot(
    project_id: int, shot_id: int, db: AsyncSession = Depends(get_db)
):
    await project_service.remove_project_shot(db, project_id, shot_id)


@router.post("/{project_id}/shots/reorder", response_model=ProjectOut)
async def reorder_project_shots(
    project_id: int, req: MemberReorderRequest, db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    proj = await project_service.reorder_project_shots(
        db, project_id, req.ids, req.lock_version
    )
    return ProjectOut.model_validate(proj)


# ============================ Project Products ============================


@router.get("/{project_id}/products", response_model=Page[ProductOut])
async def list_project_products(
    project_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Page[ProductOut]:
    rows, total = await project_service.list_project_products(
        db, project_id, page=page, page_size=page_size
    )
    return Page[ProductOut](
        items=[ProductOut.model_validate(p) for p in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{project_id}/products/batch",
    response_model=BatchResultOut,
    status_code=status.HTTP_200_OK,
)
async def add_project_products(
    project_id: int, req: MemberBatchRequest, db: AsyncSession = Depends(get_db)
) -> BatchResultOut:
    result = await project_service.add_project_products(db, project_id, req.ids)
    return BatchResultOut(**result)


@router.delete(
    "/{project_id}/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_project_product(
    project_id: int, product_id: int, db: AsyncSession = Depends(get_db)
):
    await project_service.remove_project_product(db, project_id, product_id)


# ============================ Project Scripts（归属）============================


@router.get("/{project_id}/scripts", response_model=ScriptListResponse)
async def list_project_scripts(
    project_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ScriptListResponse:
    rows, total = await project_service.list_project_scripts(
        db, project_id, page=page, page_size=page_size
    )
    items = []
    for p in rows:
        out = ScriptProjectOut.model_validate(p)
        out.segment_count = await script_service._segment_count(db, p.id)
        items.append(out)
    return ScriptListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post(
    "/{project_id}/scripts/{script_id}",
    response_model=ScriptProjectOut,
    status_code=status.HTTP_200_OK,
)
async def attach_script(
    project_id: int, script_id: int, db: AsyncSession = Depends(get_db)
) -> ScriptProjectOut:
    script = await project_service.attach_script(db, project_id, script_id)
    out = ScriptProjectOut.model_validate(script)
    out.segment_count = await script_service._segment_count(db, script.id)
    return out


@router.delete(
    "/{project_id}/scripts/{script_id}",
    response_model=ScriptProjectOut,
)
async def detach_script(
    project_id: int, script_id: int, db: AsyncSession = Depends(get_db)
) -> ScriptProjectOut:
    script = await project_service.detach_script(db, project_id, script_id)
    out = ScriptProjectOut.model_validate(script)
    out.segment_count = await script_service._segment_count(db, script.id)
    return out
