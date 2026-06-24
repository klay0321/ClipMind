"""系统/健康检查 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class HealthLiveOut(BaseModel):
    status: str = "ok"


class HealthReadyOut(BaseModel):
    status: str  # ok / degraded
    database: bool
    redis: bool
    ffprobe: bool
    detail: dict[str, str] = {}


class SystemStatusOut(BaseModel):
    asset_total: int
    assets_by_status: dict[str, int]
    source_directory_count: int
    active_scan_runs: int
    last_scanned_at: datetime | None
    database: bool
    redis: bool
    ffprobe: bool
