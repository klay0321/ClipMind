"""Export 模型：按镜头时间区间从源视频导出的可下载片段。

- 导出文件写入独立 data_dir（exports/{export_uuid}/），绝不回写源目录。
- **来源快照**：创建时写入来源镜头/素材的不可变快照（source_*），即使旧镜头后续被
  重分析删除，导出记录仍能完整追溯到原 Asset、原代次、原时间码与原文件名/路径，
  下载也不依赖旧 Shot 仍然存在。
- shot_id 为可空关系（SET NULL），仅作"当前是否还指向某镜头"的便利引用；
  来源追溯一律以 source_* 快照为准（source_* 不为空）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import ExportStatus


class Export(Base):
    __tablename__ = "export"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 文件目录使用 UUID（不直接用自增 id 作为文件系统路径输入）
    export_uuid: Mapped[str] = mapped_column(String(36), unique=True)

    # 便利引用：Asset 仍存在时直接建立数据库关联；被删除后置 NULL（追溯不依赖它）
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 便利引用：旧镜头被重分析删除后置 NULL；追溯不依赖它
    shot_id: Mapped[int | None] = mapped_column(
        ForeignKey("shot.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # PR-06B：可选项目归属（导出中心按项目聚合）。项目删除时 SET NULL，导出记录保留。
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[ExportStatus] = mapped_column(
        pg_enum(ExportStatus, "export_status"), default=ExportStatus.QUEUED
    )
    mode: Mapped[str] = mapped_column(String(16), default="reencode")  # reencode / copy

    # ---- 来源快照（不为空，创建时写入，永久可追溯，Asset/Shot 删除后仍保留）----
    source_asset_id: Mapped[int] = mapped_column(Integer)
    source_shot_id: Mapped[int] = mapped_column(Integer)
    source_generation: Mapped[int] = mapped_column(Integer)
    source_sequence_no: Mapped[int] = mapped_column(Integer)
    source_start_time: Mapped[float] = mapped_column(Float)
    source_end_time: Mapped[float] = mapped_column(Float)
    source_filename: Mapped[str] = mapped_column(String(512))
    source_relative_path: Mapped[str] = mapped_column(String(2048))

    # 导出文件相对路径（相对 data_dir）与对外下载文件名
    output_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        Index("ix_export_status", "status"),
    )
