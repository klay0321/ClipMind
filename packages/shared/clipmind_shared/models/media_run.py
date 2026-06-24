"""MediaProcessingRun 模型：单次镜头分析运行。

镜头分析状态以数据库为事实来源（仿 ScanRun）：
- 每个素材同一时刻至多一个活动运行（queued/running），由部分唯一索引保证。
- generation 为单调递增的代次号，用于"原子代次切换"：新一代镜头与旧一代可短暂共存，
  通过一次数据库事务完成切换（详见 worker/media）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import MediaRunStatus


class MediaProcessingRun(Base):
    __tablename__ = "media_processing_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 文件目录使用 UUID（不直接用自增 id 作为文件系统路径输入）
    run_uuid: Mapped[str] = mapped_column(String(36), unique=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), index=True
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[MediaRunStatus] = mapped_column(
        pg_enum(MediaRunStatus, "media_run_status"), default=MediaRunStatus.QUEUED
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    current_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total_shots: Mapped[int] = mapped_column(Integer, default=0)
    completed_shots: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 代次号：用于旧/新镜头并存时的唯一约束与原子切换
    generation: Mapped[int] = mapped_column(Integer, default=0)
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        # 每个素材同一时刻至多一个活动镜头分析（queued/running）——数据库层防重
        Index(
            "uq_active_media_run",
            "asset_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )
