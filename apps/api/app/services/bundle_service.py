"""PR-06B：多镜头 ZIP 打包导出调度（校验 + 限制 + 建行 + 入队 media 队列）。

校验：去重；1≤数量≤上限；总源时长≤上限（体积安全代理）；镜头必须存在且 READY；
不允许用户提供输出路径（输出路径由 worker 在 data_dir 内分配）。
建行 → commit → 入队 → 写回 celery_task_id；入队失败标记 FAILED 并向上抛。
"""

from __future__ import annotations

import uuid

from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import BundleExport, Project, Shot
from clipmind_shared.models.enums import ExportStatus, ShotStatus
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.bundle import (
    MAX_BUNDLE_SHOTS,
    MAX_BUNDLE_TOTAL_DURATION,
    BundleCreateRequest,
)
from app.tasks_client import enqueue_export_bundle


async def request_bundle(db: AsyncSession, req: BundleCreateRequest) -> BundleExport:
    # 去重保序
    seen: set[int] = set()
    shot_ids: list[int] = []
    for sid in req.shot_ids:
        if sid not in seen:
            seen.add(sid)
            shot_ids.append(sid)

    if not shot_ids:
        raise HTTPException(status_code=422, detail="至少选择 1 个镜头")
    if len(shot_ids) > MAX_BUNDLE_SHOTS:
        raise HTTPException(
            status_code=422, detail=f"打包镜头数超过上限（最多 {MAX_BUNDLE_SHOTS} 个）"
        )

    if req.project_id is not None:
        proj = await db.get(Project, req.project_id)
        if proj is None:
            raise HTTPException(status_code=404, detail="项目不存在")

    shots = (await db.scalars(select(Shot).where(Shot.id.in_(shot_ids)))).all()
    by_id = {s.id: s for s in shots}
    missing = [sid for sid in shot_ids if sid not in by_id]
    if missing:
        raise HTTPException(status_code=422, detail=f"镜头不存在：{missing[:10]}")
    not_ready = [sid for sid in shot_ids if by_id[sid].status != ShotStatus.READY]
    if not_ready:
        raise HTTPException(status_code=422, detail=f"镜头尚未就绪：{not_ready[:10]}")

    total_duration = sum(
        float(by_id[sid].end_time - by_id[sid].start_time) for sid in shot_ids
    )
    if total_duration > MAX_BUNDLE_TOTAL_DURATION:
        raise HTTPException(
            status_code=422,
            detail=f"打包总时长超过上限（约 {MAX_BUNDLE_TOTAL_DURATION:.0f}s）",
        )

    bundle = BundleExport(
        export_uuid=uuid.uuid4().hex,
        project_id=req.project_id,
        status=ExportStatus.QUEUED,
        shot_ids=shot_ids,
        mode=req.mode,
        queued_at=utcnow(),
    )
    db.add(bundle)
    await db.commit()
    await db.refresh(bundle)

    try:
        task_id = enqueue_export_bundle(bundle.id)
    except Exception as exc:  # noqa: BLE001
        bundle.status = ExportStatus.FAILED
        bundle.error_message = f"入队失败: {exc}"[:ERROR_MESSAGE_MAX_LEN]
        bundle.finished_at = utcnow()
        await db.commit()
        raise

    bundle.celery_task_id = task_id
    await db.commit()
    await db.refresh(bundle)
    return bundle
