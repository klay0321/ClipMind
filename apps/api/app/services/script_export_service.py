"""PR-05 Gate B：脚本剪辑清单 CSV 导出调度（建行 + 入队 export 队列）。

与 shot_dispatch.request_export 一致的顺序：建行 → commit → 入队 → 写回 celery_task_id；
入队失败标记 FAILED 并向上抛。CSV 生成在 export-worker（不在 API 进程做重活）。
"""

from __future__ import annotations

import uuid

from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import ScriptExport
from clipmind_shared.models.enums import ExportStatus
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.script_match_service import get_project_or_404
from app.tasks_client import enqueue_export_script_csv


async def request_csv_export(db: AsyncSession, project_id: int) -> ScriptExport:
    """为脚本项目创建 CSV 导出运行并入队。"""
    await get_project_or_404(db, project_id)
    export = ScriptExport(
        export_uuid=uuid.uuid4().hex,
        script_project_id=project_id,
        status=ExportStatus.QUEUED,
        export_format="csv",
        queued_at=utcnow(),
    )
    db.add(export)
    await db.commit()
    await db.refresh(export)

    try:
        task_id = enqueue_export_script_csv(export.id)
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


async def get_export_or_404(
    db: AsyncSession, project_id: int, export_id: int
) -> ScriptExport:
    export = await db.get(ScriptExport, export_id)
    if export is None or export.script_project_id != project_id:
        raise HTTPException(status_code=404, detail="脚本导出不存在")
    return export
