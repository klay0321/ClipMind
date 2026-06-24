"""SourceDirectory 与 ScanRun 相关 schema。"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models.enums import ScanRunStatus, ScanStatus
from pydantic import BaseModel, ConfigDict, Field


class SourceDirectoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    mount_path: str = Field(min_length=1, max_length=1024)
    recursive: bool = True
    enabled: bool = True
    include_extensions: list[str] | None = None
    exclude_patterns: list[str] | None = None


class SourceDirectoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    mount_path: str | None = Field(default=None, min_length=1, max_length=1024)
    recursive: bool | None = None
    enabled: bool | None = None
    include_extensions: list[str] | None = None
    exclude_patterns: list[str] | None = None


class SourceDirectoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    mount_path: str
    enabled: bool
    recursive: bool
    include_extensions: list[str]
    exclude_patterns: list[str]
    read_only: bool
    scan_status: ScanStatus
    last_scanned_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ScanRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_directory_id: int
    status: ScanRunStatus
    celery_task_id: str | None
    queued_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    finished_at: datetime | None
    worker_name: str | None
    files_discovered: int
    files_new: int
    files_modified: int
    files_missing: int
    files_errored: int
    error_message: str | None


class ScanStatusOut(BaseModel):
    source_directory_id: int
    scan_status: ScanStatus
    last_scanned_at: datetime | None
    latest_run: ScanRunOut | None
