"""PR-06B：多镜头打包导出（Bundle ZIP）。

按 PRD §7.15.2「批量下载」：多选镜头 → 各自从源视频裁剪 clip → 打包为 ZIP，内含
``clips/`` + ``manifest.json``（来源/时间码/产品/JSON 元数据）+ 剪辑清单 + ``README.txt``。

- 复用 ``ExportStatus`` 枚举；导出文件写入独立 data_dir（``bundle_exports/{export_uuid}/``），
  绝不回写源目录、绝不包含本机绝对路径 / Key / Endpoint。
- ``shot_ids`` 为请求时的镜头 id 快照（JSONB），任务按此裁剪；缺失/不可用镜头在任务内处理。
- 与 ``Export`` / ``ScriptExport`` 一起进入统一导出中心（kind=bundle，只读聚合，不合表）。
- 可选 ``project_id``（导出中心按项目聚合，项目删除 SET NULL，记录保留）。
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import ExportStatus


class BundleExport(Base):
    __tablename__ = "bundle_export"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 文件目录使用 UUID（不直接用自增 id 作为文件系统路径输入）
    export_uuid: Mapped[str] = mapped_column(String(36), unique=True)

    # 可选项目归属（导出中心按项目聚合）。项目删除时 SET NULL，导出记录保留。
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[ExportStatus] = mapped_column(
        pg_enum(ExportStatus, "export_status"), default=ExportStatus.QUEUED
    )
    # 请求时的镜头 id 快照（顺序即打包顺序）
    shot_ids: Mapped[list] = mapped_column(JSONB)
    mode: Mapped[str] = mapped_column(String(16), default="reencode")  # reencode / copy

    # 导出 ZIP 相对路径（相对 data_dir）与对外下载文件名（安全、不可路径穿越）
    output_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 实际成功打包的片段数
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
        Index("ix_bundle_export_status", "status"),
    )
