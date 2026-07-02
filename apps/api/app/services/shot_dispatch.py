"""镜头分析 / 片段导出调度：以数据库为事实来源创建运行行并入队 Celery。

与 scan_dispatch 一致的顺序：先建行 + flush（部分唯一索引兜底并发）→ commit → 入队 →
写回 celery_task_id；入队失败标记 FAILED 并向上抛。
"""

from __future__ import annotations

import uuid

from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Asset, Export, MediaProcessingRun, Shot
from clipmind_shared.models.enums import (
    ACTIVE_MEDIA_RUN_STATUSES,
    ExportStatus,
    MediaRunStatus,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks_client import enqueue_analyze_shots, enqueue_export_clip


async def get_active_media_run(db: AsyncSession, asset_id: int) -> MediaProcessingRun | None:
    stmt = (
        select(MediaProcessingRun)
        .where(
            MediaProcessingRun.asset_id == asset_id,
            MediaProcessingRun.status.in_(list(ACTIVE_MEDIA_RUN_STATUSES)),
        )
        .order_by(MediaProcessingRun.id.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def get_latest_media_run(db: AsyncSession, asset_id: int) -> MediaProcessingRun | None:
    stmt = (
        select(MediaProcessingRun)
        .where(MediaProcessingRun.asset_id == asset_id)
        .order_by(MediaProcessingRun.id.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def request_analysis(db: AsyncSession, asset: Asset) -> MediaProcessingRun:
    """发起/重试镜头分析：已有活动运行则幂等返回，否则建运行并入队。

    PR-B 血缘守卫：素材镜头存在成片使用血缘引用时拒绝重新分析——
    代次替换会物理删除旧镜头，破坏 final_video_usage 的 RESTRICT 外键与血缘完整性
    （worker 侧即便绕过也会因外键失败而保留旧代次，绝不静默断血缘）。
    """
    from fastapi import HTTPException

    from app.services.final_video_service import count_usage_refs_for_asset

    usage_refs = await count_usage_refs_for_asset(db, asset.id)
    if usage_refs > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"该素材的镜头已被成片使用血缘引用（{usage_refs} 条），"
                "重新拆镜头会删除旧镜头并破坏血缘，已阻止"
            ),
        )

    existing = await get_active_media_run(db, asset.id)
    if existing is not None:
        return existing

    run = MediaProcessingRun(
        run_uuid=uuid.uuid4().hex,
        asset_id=asset.id,
        status=MediaRunStatus.QUEUED,
        queued_at=utcnow(),
    )
    db.add(run)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await get_active_media_run(db, asset.id)
        if existing is not None:
            return existing
        raise

    await db.commit()
    await db.refresh(run)

    try:
        task_id = enqueue_analyze_shots(run.id)
    except Exception as exc:  # noqa: BLE001
        run.status = MediaRunStatus.FAILED
        run.error_message = f"入队失败: {exc}"[:ERROR_MESSAGE_MAX_LEN]
        run.finished_at = utcnow()
        await db.commit()
        raise

    run.celery_task_id = task_id
    await db.commit()
    await db.refresh(run)
    return run


async def request_export(
    db: AsyncSession, shot: Shot, *, mode: str = "reencode", project_id: int | None = None
) -> Export:
    """为镜头创建导出运行并入队，写入来源快照（永久可追溯，不依赖旧 Shot）。

    PR-06B：可选 project_id 关联到导出中心（项目删除 SET NULL，记录保留）。
    """
    asset = await db.get(Asset, shot.asset_id)
    if asset is None:
        raise ValueError("asset_not_found")
    export = Export(
        export_uuid=uuid.uuid4().hex,
        asset_id=shot.asset_id,
        shot_id=shot.id,
        project_id=project_id,
        status=ExportStatus.QUEUED,
        mode=mode,
        # 来源快照
        source_asset_id=shot.asset_id,
        source_shot_id=shot.id,
        source_generation=shot.generation,
        source_sequence_no=shot.sequence_no,
        source_start_time=shot.start_time,
        source_end_time=shot.end_time,
        source_filename=asset.filename,
        source_relative_path=asset.relative_path,
        queued_at=utcnow(),
    )
    db.add(export)
    await db.commit()
    await db.refresh(export)

    try:
        task_id = enqueue_export_clip(export.id)
    except Exception as exc:  # noqa: BLE001
        export.status = ExportStatus.FAILED
        export.error_message = f"入队失败: {exc}"[:ERROR_MESSAGE_MAX_LEN]
        export.finished_at = utcnow()
        await db.commit()
        raise

    export.celery_task_id = task_id
    await db.commit()
    await db.refresh(export)
    return export
