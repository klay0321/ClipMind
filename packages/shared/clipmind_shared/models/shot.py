"""Shot 模型：从一个 Asset 派生出的单个镜头及其派生文件路径。

约束：
- (asset_id, generation, sequence_no) 唯一：同一代次内镜头序号唯一，
  允许旧/新代次在原子切换窗口内短暂共存。
- start_time >= 0、end_time > start_time、duration >= 0。
- 派生文件路径存"相对 data_dir 的相对路径"，绝不存服务器绝对路径。
- 仅 status=ready 的镜头对外可见。
- PR-02 不写 AI 字段；description/quality_score/risk_level/review_status 留待 PR-03。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import ShotStatus


class Shot(Base):
    __tablename__ = "shot"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), index=True
    )
    processing_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_processing_run.id", ondelete="SET NULL"), nullable=True
    )
    generation: Mapped[int] = mapped_column(Integer, default=0)

    sequence_no: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    duration: Mapped[float] = mapped_column(Float)

    detector_type: Mapped[str] = mapped_column(String(32))
    detector_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[ShotStatus] = mapped_column(
        pg_enum(ShotStatus, "shot_status"), default=ShotStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 派生文件相对路径（相对 data_dir）
    keyframe_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    proxy_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # 关键帧条：沿镜头时间均匀采样的多帧相对路径（有序）；空/None 表示仅主关键帧
    keyframe_paths: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "asset_id", "generation", "sequence_no", name="uq_shot_asset_gen_seq"
        ),
        CheckConstraint("start_time >= 0", name="start_nonneg"),
        CheckConstraint("end_time > start_time", name="end_gt_start"),
        CheckConstraint("duration >= 0", name="duration_nonneg"),
        Index("ix_shot_asset_status", "asset_id", "status"),
    )
