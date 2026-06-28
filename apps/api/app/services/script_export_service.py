"""PR-05 Gate B / PR-06B：脚本剪辑清单导出调度（建行 + 入队 export 队列）。

与 shot_dispatch.request_export 一致的顺序：建行 → commit → 入队 → 写回 celery_task_id；
入队失败标记 FAILED 并向上抛。多格式生成在 export-worker（不在 API 进程做重活）。

PR-06B：``export_format`` 支持 csv/xlsx/json/markdown/printable；``project_id`` 关联到导出中心，
默认取脚本项目所属 Project（script_project.project_id），不存在则为 NULL。
"""

from __future__ import annotations

import uuid

from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import ScriptExport
from clipmind_shared.models.enums import SCRIPT_EXPORT_FORMATS, ExportStatus
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.script_match_service import get_project_or_404
from app.tasks_client import enqueue_export_script


async def request_script_export(
    db: AsyncSession, project_id: int, *, export_format: str = "csv"
) -> ScriptExport:
    """为脚本项目创建指定格式导出运行并入队（格式非法 422）。"""
    if export_format not in SCRIPT_EXPORT_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的导出格式（允许：{', '.join(SCRIPT_EXPORT_FORMATS)}）",
        )
    script = await get_project_or_404(db, project_id)
    export = ScriptExport(
        export_uuid=uuid.uuid4().hex,
        script_project_id=project_id,
        project_id=getattr(script, "project_id", None),
        status=ExportStatus.QUEUED,
        export_format=export_format,
        queued_at=utcnow(),
    )
    db.add(export)
    await db.commit()
    await db.refresh(export)

    try:
        task_id = enqueue_export_script(export.id)
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
