"""PR-C 稳定素材身份：Asset 物理位置与指纹任务模型。

- ``asset_location``：一个 Asset（稳定逻辑内容实体）的一个物理位置。
  文件移动/复制不改变 Asset 身份：移动 = 旧位置转 historical + 新位置成为
  primary present；复制 = 同一 Asset 增加第二个非 primary 位置。
  位置历史**不物理删除**（审计事实）。
- ``fingerprint_job``：quick/full 指纹计算任务的进度与结果跟踪
  （单资产与批量共用；实际计算在 worker 里分块只读执行）。

安全：
- 只存 source root 下的安全相对路径（入库前经 normalize + 路径穿越校验），
  绝不存 Windows 绝对路径或 NAS 管理员路径；
- 同一 root + normalized_path 同时只能有一个非 historical 位置（部分唯一索引）；
- 一个 Asset 至多一个 primary 位置（部分唯一索引）；
- source root 归档/禁用不删除 Asset 与位置历史。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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

from clipmind_shared.db.base import Base, utcnow


class AssetLocation(Base):
    __tablename__ = "asset_location"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), index=True
    )
    source_root_id: Mapped[int] = mapped_column(
        ForeignKey("source_directory.id", ondelete="CASCADE"), index=True
    )

    # 原始相对路径（展示用）与规范化相对路径（唯一性/查找用）；均为 root 下安全相对路径
    relative_path: Mapped[str] = mapped_column(String(2048))
    normalized_path: Mapped[str] = mapped_column(String(2048))

    # 受控白名单 LOCATION_STATUSES：present / missing / historical / conflict
    # - present：文件在此路径存在
    # - missing：上次在此见过、当前扫描未见（可能被移动，等待 reconcile 或重现）
    # - historical：已被确认移走/改名，仅作路径历史保留
    # - conflict：同路径内容被替换（quick 指纹变化），等待人工确认，不静默覆盖身份
    location_status: Mapped[str] = mapped_column(String(16), default="present")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mtime_ns: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    missing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 最近一次内容核对（full hash 验证或扫描确认）时刻
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        # 同一 root + 规范化路径同时只能指向一个活动（非 historical）位置
        Index(
            "uq_asset_location_active_path",
            "source_root_id",
            "normalized_path",
            unique=True,
            postgresql_where=text("location_status != 'historical'"),
        ),
        # 一个 Asset 至多一个 primary 位置
        Index(
            "uq_asset_location_primary",
            "asset_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        Index("ix_asset_location_status", "location_status"),
    )


class FingerprintJob(Base):
    """指纹计算任务（单资产/批量共用；进度与失败以数据库为事实来源）。"""

    __tablename__ = "fingerprint_job"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 受控 FINGERPRINT_KINDS：quick / full
    kind: Mapped[str] = mapped_column(String(16))
    # 请求时的 asset id 快照（有序；执行结果见 counts 与 asset 行上的状态）
    asset_ids: Mapped[list[int]] = mapped_column(JSONB)
    # 受控 FINGERPRINT_JOB_STATUSES：queued / running / completed / partial / failed
    status: Mapped[str] = mapped_column(String(16), default="queued")

    total_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    # 当前文件内的进度（0-100，full 大文件分块时更新）
    progress: Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 每资产结果摘要（脱敏：只存 asset_id 与受控结果值，不存路径/完整哈希）
    results: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_fingerprint_job_status", "status"),
    )
