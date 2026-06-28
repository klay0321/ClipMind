"""Export / 片段导出相关 schema。"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models import Export
from clipmind_shared.models.enums import ExportStatus
from pydantic import BaseModel, Field


class ExportCreate(BaseModel):
    mode: str = Field("reencode", pattern="^(reencode|copy)$")
    project_id: int | None = None  # PR-06B：可选项目归属（导出中心聚合）


class ExportOut(BaseModel):
    id: int
    asset_id: int | None
    shot_id: int | None
    status: ExportStatus
    mode: str
    # 来源快照（永久可追溯，不依赖 Asset/Shot 仍存在）
    source_asset_id: int
    source_shot_id: int
    source_generation: int
    source_sequence_no: int
    source_start_time: float
    source_end_time: float
    source_filename: str
    source_relative_path: str
    filename: str | None
    error_message: str | None
    celery_task_id: str | None
    has_file: bool
    created_at: datetime
    finished_at: datetime | None


class ExportAcceptedOut(BaseModel):
    export_id: int
    shot_id: int
    status: ExportStatus
    celery_task_id: str | None = None
    detail: str = "已入队片段导出"


def to_export_out(export: Export) -> ExportOut:
    return ExportOut(
        id=export.id,
        asset_id=export.asset_id,
        shot_id=export.shot_id,
        status=export.status,
        mode=export.mode,
        source_asset_id=export.source_asset_id,
        source_shot_id=export.source_shot_id,
        source_generation=export.source_generation,
        source_sequence_no=export.source_sequence_no,
        source_start_time=export.source_start_time,
        source_end_time=export.source_end_time,
        source_filename=export.source_filename,
        source_relative_path=export.source_relative_path,
        filename=export.filename,
        error_message=export.error_message,
        celery_task_id=export.celery_task_id,
        has_file=bool(export.output_path),
        created_at=export.created_at,
        finished_at=export.finished_at,
    )
