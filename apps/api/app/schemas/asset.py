"""Asset 相关 schema。"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models.enums import AssetStatus
from pydantic import BaseModel, ConfigDict


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_directory_id: int
    relative_path: str
    normalized_relative_path: str
    filename: str
    extension: str
    file_size: int
    modified_at: datetime | None
    quick_hash: str | None
    duration: float | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    orientation: str | None
    has_audio: bool | None
    status: AssetStatus
    error_message: str | None
    last_seen_scan_id: int | None
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class RescanAcceptedOut(BaseModel):
    asset_id: int
    celery_task_id: str
    detail: str = "已入队重扫"
