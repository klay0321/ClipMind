"""健康检查：live（仅进程）与 ready（依赖就绪）。"""

from __future__ import annotations

import redis.asyncio as aioredis
from clipmind_shared.ffprobe import ffprobe_version
from fastapi import APIRouter, Response
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.schemas.system import HealthLiveOut, HealthReadyOut

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
    """检测 PostgreSQL / Redis / FFprobe 就绪；任一异常返回 503。"""
    settings = get_settings()
    db_ok = await _check_db()
    redis_ok = await _check_redis(settings.redis_url)
    ffprobe_ok = ffprobe_version() is not None

    detail: dict[str, str] = {}
    if not db_ok:
        detail["database"] = "无法连接 PostgreSQL"
    if not redis_ok:
        detail["redis"] = "无法连接 Redis"
    if not ffprobe_ok:
        detail["ffprobe"] = "ffprobe 不可用"

    all_ok = db_ok and redis_ok and ffprobe_ok
    if not all_ok:
        response.status_code = 503

    return HealthReadyOut(
        status="ok" if all_ok else "degraded",
        database=db_ok,
        redis=redis_ok,
        ffprobe=ffprobe_ok,
        detail=detail,
    )
