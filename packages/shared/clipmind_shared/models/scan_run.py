"""ScanRun 模型：单次扫描运行，使扫描状态以数据库为事实来源。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import ScanRunStatus


class ScanRun(Base):
    __tablename__ = "scan_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_directory_id: Mapped[int] = mapped_column(
        ForeignKey("source_directory.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[ScanRunStatus] = mapped_column(
        pg_enum(ScanRunStatus, "scan_run_status"), default=ScanRunStatus.QUEUED
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    files_discovered: Mapped[int] = mapped_column(Integer, default=0)
    files_new: Mapped[int] = mapped_column(Integer, default=0)
    files_modified: Mapped[int] = mapped_column(Integer, default=0)
    files_missing: Mapped[int] = mapped_column(Integer, default=0)
    files_errored: Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # 每个目录同一时刻至多一个活动扫描（queued/running）——数据库层防重
        Index(
            "uq_active_scan_run",
            "source_directory_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )
