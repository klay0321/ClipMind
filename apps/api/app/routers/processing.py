"""AAP 路由：批量分析 + 全局处理概览。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.processing import BatchAnalyzeIn, BatchAnalyzeOut, ProcessingOverviewOut
from app.services import processing_service

router = APIRouter(tags=["processing"])


@router.post("/assets/batch-analyze", response_model=BatchAnalyzeOut, status_code=202)
async def batch_analyze(
    payload: BatchAnalyzeIn, db: AsyncSession = Depends(get_db)
) -> BatchAnalyzeOut:
    if not payload.asset_ids and payload.source_directory_id is None:
        raise HTTPException(
            status_code=422,
            detail="必须显式给出 asset_ids 或 source_directory_id（不做全库隐式操作）",
        )
    if not payload.stages:
        raise HTTPException(status_code=422, detail="stages 不能为空")
    return await processing_service.batch_analyze(db, payload)


@router.get("/processing/overview", response_model=ProcessingOverviewOut)
async def processing_overview(db: AsyncSession = Depends(get_db)) -> ProcessingOverviewOut:
    return await processing_service.overview(db)
