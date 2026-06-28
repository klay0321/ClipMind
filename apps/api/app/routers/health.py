"""健康检查：live（仅进程）与 ready（依赖就绪）。"""

from __future__ import annotations

import redis.asyncio as aioredis
from clipmind_shared.ffprobe import ffprobe_version
from fastapi import APIRouter, Response
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.schemas.system import HealthLiveOut, HealthReadyOut
from app.services.migration_check import check_migration

router = APIRouter(tags=["health"])


async def _check_db() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - 健康检查只关心可达性
        return False


async def _check_redis(url: str) -> bool:
    client = aioredis.from_url(url)
    try:
        await client.ping()
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        await client.aclose()


@router.get("/health/live", response_model=HealthLiveOut)
async def health_live() -> HealthLiveOut:
    """仅检测应用进程存活，永远返回 200（用于容器 healthcheck）。"""
    return HealthLiveOut()


@router.get("/health/ready", response_model=HealthReadyOut)
async def health_ready(response: Response) -> HealthReadyOut:
    """检测 PostgreSQL / Redis / FFprobe / 迁移版本 就绪；任一异常返回 503。

    迁移落后（DB revision != head）也判 not-ready，使部署门禁可识别"需要运行迁移升级"，
    避免 API 以旧 schema 静默服务、对新接口 500。
    """
    settings = get_settings()
    db_ok = await _check_db()
    redis_ok = await _check_redis(settings.redis_url)
    ffprobe_ok = ffprobe_version() is not None

    migration = await check_migration(engine) if db_ok else None

    detail: dict[str, str] = {}
    if not db_ok:
        detail["database"] = "无法连接 PostgreSQL"
    if not redis_ok:
        detail["redis"] = "无法连接 Redis"
    if not ffprobe_ok:
        detail["ffprobe"] = "ffprobe 不可用"
    migration_ok = migration.ok if migration is not None else False
    if migration is not None and not migration.ok:
        detail["migration"] = migration.detail

    all_ok = db_ok and redis_ok and ffprobe_ok and migration_ok
    if not all_ok:
        response.status_code = 503

    return HealthReadyOut(
        status="ok" if all_ok else "degraded",
        database=db_ok,
        redis=redis_ok,
        ffprobe=ffprobe_ok,
        migration_ok=migration_ok,
        migration_current=migration.current if migration is not None else None,
        migration_head=migration.head if migration is not None else None,
        detail=detail,
    )
