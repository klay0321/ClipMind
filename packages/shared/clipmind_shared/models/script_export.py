"""PR-05 Gate B：脚本剪辑清单导出（CSV）。

与片段视频导出（``Export``，从源视频按时间码裁剪可下载片段）**不同**：``ScriptExport`` 是
脚本项目维度的**结构化剪辑计划导出**（一行一段，含选用镜头/时间码/匹配理由/缺口），不裁剪视频。

- 复用 ``ExportStatus`` 枚举与 ``export`` 队列；导出文件写入独立 data_dir（``script_exports/{uuid}/``），
  绝不回写源目录、绝不包含本机绝对路径/Key/Endpoint。
- 删除脚本项目级联删除其导出记录（CASCADE）；导出文件由清理逻辑按 data_dir 处理。
- PR-05 Gate B 起 CSV；PR-06B 扩 XLSX/JSON/Markdown/printable HTML（``export_format``）。
- PR-06B：可选 ``project_id``（导出中心按项目聚合，项目删除 SET NULL，记录保留）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import ExportStatus


class ScriptExport(Base):
    __tablename__ = "script_export"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 文件目录使用 UUID（不直接用自增 id 作为文件系统路径输入）
    export_uuid: Mapped[str] = mapped_column(String(36), unique=True)

    script_project_id: Mapped[int] = mapped_column(
        ForeignKey("script_project.id", ondelete="CASCADE"), index=True
    )
    # PR-06B：可选项目归属（导出中心按项目聚合）。项目删除时 SET NULL，导出记录保留。
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[ExportStatus] = mapped_column(
        pg_enum(ExportStatus, "export_status"), default=ExportStatus.QUEUED
    )
    # PR-06B：csv / xlsx / json / markdown / printable（列宽 16 容纳 'printable'）
    export_format: Mapped[str] = mapped_column(String(16), default="csv")

    # 导出文件相对路径（相对 data_dir）与对外下载文件名（安全、不可路径穿越）
    output_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        Index("ix_script_export_status", "status"),
    )
