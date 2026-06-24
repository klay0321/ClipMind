"""素材路由：分页列表（搜索/筛选）+ 详情 + 单素材重扫 + 镜头分析。"""

from __future__ import annotations

from clipmind_shared.models.enums import AssetStatus
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.asset import AssetOut, RescanAcceptedOut
from app.schemas.common import Page
from app.schemas.shot import (
    AnalyzeAcceptedOut,
    ShotAnalysisOut,
    ShotOut,
    to_analysis_out,
    to_shot_out,
)
from app.services import asset_service, scan_dispatch, shot_dispatch, shot_service

router = APIRouter(prefix="/assets", tags=["assets"])


def _enrich(out: AssetOut, *, shot_count: int, analysis_status: str | None) -> AssetOut:
    out.shot_count = shot_count
    out.analysis_status = analysis_status
    return out


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
    ids = [a.id for a in items]
    counts = await shot_service.ready_counts_for_assets(db, ids)
    statuses = await shot_service.latest_run_status_for_assets(db, ids)
    return Page[AssetOut](
        items=[
            _enrich(
                AssetOut.model_validate(a),
                shot_count=counts.get(a.id, 0),
                analysis_status=statuses.get(a.id),
            )
            for a in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{asset_id}", response_model=AssetOut)
async def get_asset(asset_id: int, db: AsyncSession = Depends(get_db)) -> AssetOut:
    asset = await asset_service.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    counts = await shot_service.ready_counts_for_assets(db, [asset.id])
    statuses = await shot_service.latest_run_status_for_assets(db, [asset.id])
    return _enrich(
        AssetOut.model_validate(asset),
        shot_count=counts.get(asset.id, 0),
        analysis_status=statuses.get(asset.id),
    )


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


# ---------------- PR-02 镜头分析 ----------------


async def _start_analysis(asset_id: int, db: AsyncSession) -> AnalyzeAcceptedOut:
    asset = await asset_service.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    if asset.status == AssetStatus.SOURCE_MISSING:
        raise HTTPException(status_code=409, detail="源文件缺失，无法分析")
    try:
        run = await shot_dispatch.request_analysis(db, asset)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"无法入队镜头分析: {exc}") from exc
    return AnalyzeAcceptedOut(
        asset_id=asset.id,
        run_id=run.id,
        status=run.status,
        celery_task_id=run.celery_task_id,
    )


@router.post(
    "/{asset_id}/analyze-shots",
    response_model=AnalyzeAcceptedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_shots(
    asset_id: int, db: AsyncSession = Depends(get_db)
) -> AnalyzeAcceptedOut:
    return await _start_analysis(asset_id, db)


@router.post(
    "/{asset_id}/shot-analysis/retry",
    response_model=AnalyzeAcceptedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_shot_analysis(
    asset_id: int, db: AsyncSession = Depends(get_db)
) -> AnalyzeAcceptedOut:
    return await _start_analysis(asset_id, db)


@router.get("/{asset_id}/shot-analysis", response_model=ShotAnalysisOut)
async def get_shot_analysis(
    asset_id: int, response: Response, db: AsyncSession = Depends(get_db)
) -> ShotAnalysisOut:
    asset = await asset_service.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    response.headers["Cache-Control"] = "no-store"  # 任务状态接口不缓存
    run = await shot_dispatch.get_latest_media_run(db, asset_id)
    shot_count = await shot_service.count_ready_shots(db, asset_id)
    return to_analysis_out(asset_id, run, shot_count)


@router.get("/{asset_id}/shots", response_model=Page[ShotOut])
async def list_asset_shots(
    asset_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Page[ShotOut]:
    asset = await asset_service.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    items, total = await shot_service.list_shots(
        db, asset_id=asset_id, page=page, page_size=page_size
    )
    return Page[ShotOut](
        items=[to_shot_out(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )
