"""系统状态聚合。"""

from __future__ import annotations

from clipmind_shared.ffprobe import ffprobe_version
from clipmind_shared.models import Asset, ScanRun, SourceDirectory
from clipmind_shared.models.enums import ACTIVE_SCAN_RUN_STATUSES
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.routers.health import _check_redis
from app.schemas.observability import PipelineHealthOut
from app.schemas.system import SystemStatusOut
from app.services import observability_service

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/pipeline-health", response_model=PipelineHealthOut)
async def pipeline_health(db: AsyncSession = Depends(get_db)) -> PipelineHealthOut:
    """OBS：管线健康——各环节滞后/失败计数 + Celery 队列积压，只读。"""
    settings = get_settings()
    return await observability_service.pipeline_health(db, settings.redis_url)


@router.get("/status", response_model=SystemStatusOut)
async def system_status(db: AsyncSession = Depends(get_db)) -> SystemStatusOut:
    total = (await db.execute(select(func.count()).select_from(Asset))).scalar_one()

    rows = (
        await db.execute(select(Asset.status, func.count()).group_by(Asset.status))
    ).all()
    by_status = {status.value: count for status, count in rows}

    sd_count = (
        await db.execute(select(func.count()).select_from(SourceDirectory))
    ).scalar_one()

    active = (
        await db.execute(
            select(func.count())
            .select_from(ScanRun)
            .where(ScanRun.status.in_(list(ACTIVE_SCAN_RUN_STATUSES)))
        )
    ).scalar_one()

    last_scanned = (
        await db.execute(select(func.max(SourceDirectory.last_scanned_at)))
    ).scalar_one()

    settings = get_settings()
    redis_ok = await _check_redis(settings.redis_url)
    ffprobe_ok = ffprobe_version() is not None

    return SystemStatusOut(
        asset_total=total,
        assets_by_status=by_status,
        source_directory_count=sd_count,
        active_scan_runs=active,
        last_scanned_at=last_scanned,
        database=True,  # 能执行到此说明数据库可用
        redis=redis_ok,
        ffprobe=ffprobe_ok,
    )
