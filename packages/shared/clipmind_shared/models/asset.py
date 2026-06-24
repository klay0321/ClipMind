"""Asset 模型：原始视频文件的索引记录（绝不修改源文件本身）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.constants import METADATA_VERSION
from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import AssetStatus


class Asset(Base):
    __tablename__ = "asset"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_directory_id: Mapped[int] = mapped_column(
        ForeignKey("source_directory.id", ondelete="CASCADE")
    )

    # 原始相对路径（展示用）与规范化相对路径（唯一约束/查找用）
    relative_path: Mapped[str] = mapped_column(String(2048))
    normalized_relative_path: Mapped[str] = mapped_column(String(2048))
    filename: Mapped[str] = mapped_column(String(512), index=True)
    extension: Mapped[str] = mapped_column(String(16))

    # 文件系统指纹（来自 os.stat / 头尾哈希）
    file_size: Mapped[int] = mapped_column(BigInteger)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quick_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 预留：完整内容哈希（后续 PR 启用）

    # FFprobe 视频信息
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    orientation: Mapped[str | None] = mapped_column(String(16), nullable=True)  # landscape/portrait/square
    has_audio: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # 素材海报：用 FFmpeg 从源视频抽一帧的派生封面（相对 data_dir）。
    # 与镜头无关，未分析素材也有；绝不写源目录。
    poster_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    status: Mapped[AssetStatus] = mapped_column(
        pg_enum(AssetStatus, "asset_status"), default=AssetStatus.DISCOVERED
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 缺失检测：记录最后一次发现该文件的扫描运行 ID（避免大内存 seen set）
    last_seen_scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("scan_run.id", ondelete="SET NULL"), nullable=True
    )
    metadata_version: Mapped[int] = mapped_column(Integer, default=METADATA_VERSION)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "source_directory_id",
            "normalized_relative_path",
            name="uq_asset_sd_norm_path",
        ),
        Index("ix_asset_sd_status", "source_directory_id", "status"),
        Index("ix_asset_sd_last_seen_scan", "source_directory_id", "last_seen_scan_id"),
    )
