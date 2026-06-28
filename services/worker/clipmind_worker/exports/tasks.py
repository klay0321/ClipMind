"""PR-05 Gate B export-worker：脚本剪辑清单 CSV 导出任务（export 队列）。

- 以 ScriptExport 行为事实来源；QUEUED→RUNNING→COMPLETED/FAILED。
- 从 DB 重建段落视图 → 全局分配 → 剪辑清单 → CSV（UTF-8 BOM、RFC4180、公式注入防护）。
- 文件写入独立 data_dir（``script_exports/{uuid}/edit_list.csv``，磁盘名固定 ASCII），绝不回写源、
  绝不输出本机绝对路径/Key/Endpoint；下载文件名安全（不可路径穿越）。
- 失败可重试（acks_late）；不以任务自报成功为准，COMPLETED 须文件落盘。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN, TASK_EXPORT_SCRIPT_CSV
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import ScriptExport, ScriptProject
from clipmind_shared.models.enums import ExportStatus
from clipmind_shared.script import editlist as E

from clipmind_worker.celery_app import celery_app
from clipmind_worker.config import get_settings
from clipmind_worker.db import SessionLocal
from clipmind_worker.exports.factload import build_segment_views
from clipmind_worker.media import storage

logger = logging.getLogger(__name__)

_CSV_DISK_NAME = "edit_list.csv"  # 磁盘名固定 ASCII，避免编码问题
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _truncate(text: str) -> str:
    return text[:ERROR_MESSAGE_MAX_LEN]


def _safe_download_name(project_name: str, project_id: int) -> str:
    """对外下载文件名（可含中文，由 API 做 RFC5987 编码）；剔除路径分隔符/控制字符。"""
    base = _UNSAFE.sub("_", (project_name or "").strip()) or f"script_{project_id}"
    return f"剪辑清单_{base[:80]}.csv"


@celery_app.task(name=TASK_EXPORT_SCRIPT_CSV, bind=True, acks_late=True)
def export_script_csv(self, export_id: int) -> dict[str, Any]:  # noqa: ANN001
    settings = get_settings()
    with SessionLocal() as session:
        export = session.get(ScriptExport, export_id)
        if export is None:
            return {"error": "script_export_not_found", "export_id": export_id}
        if export.status != ExportStatus.QUEUED:
            return {"skipped": True, "reason": f"status={export.status.value}"}
        project = session.get(ScriptProject, export.script_project_id)
        if project is None:
            export.status = ExportStatus.FAILED
            export.error_message = "script_project_not_found"
            export.finished_at = utcnow()
            session.commit()
            return {"error": "script_project_not_found"}

        export.status = ExportStatus.RUNNING
        export.started_at = utcnow()
        session.commit()

        try:
            views = build_segment_views(session, export.script_project_id)
            rows, _summary = E.build_edit_list(
                views, max_reuse=settings.script_match_max_reuse
            )
            data = E.to_csv(rows)

            root = storage.data_root(settings.data_dir)
            storage.check_disk_space(root, settings.disk_min_free_mb)
            edir = storage.script_export_dir(root, export.export_uuid)
            storage.ensure_dir(edir)
            out_abs = os.path.join(edir, _CSV_DISK_NAME)
            with open(out_abs, "wb") as f:
                f.write(data)

            export.output_path = storage.relpath(root, out_abs)
            export.filename = _safe_download_name(project.name, project.id)
            export.row_count = len(rows)
            export.status = ExportStatus.COMPLETED
            export.finished_at = utcnow()
            session.commit()
            return {"export_id": export.id, "status": export.status.value, "rows": len(rows)}
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            failed = session.get(ScriptExport, export_id)
            if failed is not None:
                failed.status = ExportStatus.FAILED
                failed.error_message = _truncate(str(exc))
                failed.finished_at = utcnow()
                session.commit()
            raise
