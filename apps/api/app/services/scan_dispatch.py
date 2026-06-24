"""扫描调度：以数据库为事实来源地创建 ScanRun 并入队 Celery 任务。

流程（API 同步事务）：
1. 若已有活动 ScanRun（queued/running）→ 幂等返回该 run。
2. 否则创建 ScanRun(queued) + 置目录 scan_status=queued，flush（部分唯一索引兜底并发）。
3. 提交后入队 Celery，写回 celery_task_id。
   入队失败则把 run/目录标记 failed。
"""

from __future__ import annotations

from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import ScanRun, SourceDirectory
from clipmind_shared.models.enums import (
    ACTIVE_SCAN_RUN_STATUSES,
    ScanRunStatus,
    ScanStatus,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks_client import enqueue_rescan_asset, enqueue_scan


async def get_active_scan_run(db: AsyncSession, sd_id: int) -> ScanRun | None:
    stmt = (
        select(ScanRun)
        .where(
            ScanRun.source_directory_id == sd_id,
            ScanRun.status.in_(list(ACTIVE_SCAN_RUN_STATUSES)),
        )
        .order_by(ScanRun.id.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def get_latest_scan_run(db: AsyncSession, sd_id: int) -> ScanRun | None:
    stmt = (
        select(ScanRun)
        .where(ScanRun.source_directory_id == sd_id)
        .order_by(ScanRun.id.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def request_scan(db: AsyncSession, sd: SourceDirectory) -> ScanRun:
    existing = await get_active_scan_run(db, sd.id)
    if existing is not None:
        return existing

    run = ScanRun(
        source_directory_id=sd.id,
        status=ScanRunStatus.QUEUED,
        queued_at=utcnow(),
    )
    db.add(run)
    sd.scan_status = ScanStatus.QUEUED
    try:
        await db.flush()
    except IntegrityError:
        # 并发：另一个请求已创建活动 run
        await db.rollback()
        existing = await get_active_scan_run(db, sd.id)
        if existing is not None:
            return existing
        raise

    # DB 先落地（事实来源），再入队
    await db.commit()
    await db.refresh(run)

    try:
        task_id = enqueue_scan(run.id)
    except Exception as exc:  # noqa: BLE001 - 入队失败需要标记并向上抛
        run.status = ScanRunStatus.FAILED
        run.error_message = f"入队失败: {exc}"[:ERROR_MESSAGE_MAX_LEN]
        sd.scan_status = ScanStatus.FAILED
        await db.commit()
        raise

    run.celery_task_id = task_id
    await db.commit()
    await db.refresh(run)
    return run


async def request_rescan_asset(asset_id: int) -> str:
    """入队单素材重扫，返回 celery_task_id。"""
    return enqueue_rescan_asset(asset_id)
