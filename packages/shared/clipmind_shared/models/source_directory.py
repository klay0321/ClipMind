"""SourceDirectory 模型：素材源目录配置（容器逻辑路径，只读）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.constants import SUPPORTED_VIDEO_EXTENSIONS
from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import ScanStatus


class SourceDirectory(Base):
    __tablename__ = "source_directory"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    # 容器逻辑路径（必须位于白名单根之下，如 /app/source/powergo）
    mount_path: Mapped[str] = mapped_column(String(1024))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    recursive: Mapped[bool] = mapped_column(Boolean, default=True)
    # 允许的扩展名（小写不含点）；默认全部支持的视频格式
    include_extensions: Mapped[list[str]] = mapped_column(
        JSONB, default=lambda: list(SUPPORTED_VIDEO_EXTENSIONS)
    )
    # 排除的 glob 模式
    exclude_patterns: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # 源目录恒为只读，不可取消
    read_only: Mapped[bool] = mapped_column(Boolean, default=True)
    scan_status: Mapped[ScanStatus] = mapped_column(
        pg_enum(ScanStatus, "scan_status"), default=ScanStatus.NEVER_SCANNED
    )
    last_scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
