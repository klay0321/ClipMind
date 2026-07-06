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
    # PM：媒体类型（video|image）。图片素材走同一 Asset 管线（只读源/扫描/
    # 身份/位置），但无拆镜头、无代理派生；按扩展名判定。
    media_kind: Mapped[str] = mapped_column(
        String(8), nullable=False, default="video", server_default="video"
    )

    # 文件系统指纹（来自 os.stat / 头尾哈希）
    file_size: Mapped[int] = mapped_column(BigInteger)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quick_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ---- PR-C 稳定内容身份（docs/ASSET_IDENTITY.md）----
    # 路径 / 文件名 / mtime / 大小都不是身份；full_hash（完整 SHA256）才是精确字节身份。
    # quick_fingerprint = sha256(size + 头/中/尾块)（带版本），只用于候选筛选，
    # 不能单独自动合并有业务数据的 Asset。
    full_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    full_hash_algorithm: Mapped[str | None] = mapped_column(String(16), nullable=True)
    quick_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    quick_fingerprint_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # 受控白名单 FINGERPRINT_STATES：pending / quick_ready / full_ready / failed / stale
    fingerprint_state: Mapped[str] = mapped_column(String(16), default="pending")
    fingerprint_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprinted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 计算 full_hash 时的字节数（与当下 file_size 核对，检测计算后内容又变化）
    content_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

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

    # PR-03B：主/默认产品（仅"素材默认产品"语义，不代表所有镜头都只含该产品；
    # 镜头级产品以人工确认或 AI 候选为准，素材↔产品多对多见 asset_product）。
    primary_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("product.id", ondelete="SET NULL"), nullable=True
    )

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
        # PR-C：路径不再是 Asset 唯一身份——(root, normalized_path) 的活动唯一性
        # 由 asset_location 的部分唯一索引保证；此处保留普通复合索引供投影查询。
        Index("ix_asset_sd_norm_path", "source_directory_id", "normalized_relative_path"),
        Index("ix_asset_sd_status", "source_directory_id", "status"),
        Index("ix_asset_sd_last_seen_scan", "source_directory_id", "last_seen_scan_id"),
    )
