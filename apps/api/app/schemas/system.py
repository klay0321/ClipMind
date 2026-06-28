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
    # 迁移就绪：DB revision 是否已到迁移脚本 head（落后 → migration_ok=false 且整体 503）
    migration_ok: bool = True
    migration_current: str | None = None
    migration_head: str | None = None
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
