"""PR-06B 统一导出中心 schema（只读聚合，不破坏性合表）。

统一 DTO 覆盖三类导出：clip（片段 MP4）/ script（剪辑清单多格式）/ bundle（多镜头 ZIP）。
"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models.enums import ExportStatus
from pydantic import BaseModel

from app.schemas.common import Page


class ExportCenterItem(BaseModel):
    kind: str               # clip | script | bundle
    id: int
    export_uuid: str
    project_id: int | None
    status: ExportStatus
    format: str             # mp4 | csv/xlsx/json/markdown/printable | zip
    filename: str | None
    has_file: bool
    row_count: int | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    download_url: str
    download_count: int = 0
    # 安全来源上下文（绝不含本机绝对路径/Key/Endpoint）
    source: dict


ExportCenterPage = Page[ExportCenterItem]


class ExportActionOut(BaseModel):
    kind: str
    id: int
    status: ExportStatus
    detail: str
