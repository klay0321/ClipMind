"""PR-06B：下载记录（导出可追溯，PRD §7.13「下载记录」）。

记录一次成功开始返回文件的导出下载（kind + export_id + 时间）。无鉴权体系，
**不记录虚假 user_id**；"谁下载"留 PR-07。多态引用（kind+id），不建外键，保持轻量。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, utcnow


class DownloadLog(Base):
    __tablename__ = "download_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    export_kind: Mapped[str] = mapped_column(String(16))  # clip | script | bundle
    export_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_download_log_kind_export", "export_kind", "export_id"),
    )
