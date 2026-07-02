"""PR-B 最终成片与 Shot 使用血缘数据模型（以 PostgreSQL 为事实来源）。

四表：
- ``final_video``：最终成片业务实体。**引用已有 Asset 作为成片媒体文件，不重复保存视频**；
  Project / Script 绑定可空。归档不物理删除，也绝不删除 Asset 文件。
- ``final_video_usage``：某成片确实/可能使用了某个 Source Shot 的引用关系。
  ``UNIQUE(final_video_id, source_shot_id)``：同一成片与同一 Shot 只有一条关系，
  多次出现由 occurrence 表表达，故 **confirmed 行数天然 = 按成片去重的正式使用次数**。
- ``final_video_usage_occurrence``：一条 Usage 内的具体出现时间段（源/成片双侧时间码，
  毫秒整数）。任意多条 occurrence 不会让正式使用次数增加。
- ``final_video_usage_event``：轻量 append-only 审计（与业务变更同事务；无更新/删除接口；
  不误用 CatalogRevision）。

关键约束/安全：
- ``final_video.asset_id`` / ``usage.source_shot_id`` / ``usage.source_asset_id`` 均
  **RESTRICT**：存在成片记录/血缘时禁止静默删除被引用的 Asset/Shot（镜头重新分析的
  代次替换会物理删除旧 Shot，service 层在分析入口另有守卫，DB 层此处兜底）。
- ``final_video.project_id`` / ``script_project_id`` **SET NULL**：项目/脚本删除绝不
  删除成片与已确认血缘。
- 同一 Asset 至多一个未归档 FinalVideo（部分唯一索引）。
- 使用次数是派生值：本模块**没有**任何 usage_count 缓存列，计数一律实时聚合。
- evidence_method / event.action 为受控 String（白名单见 enums），不建 PG 枚举，免迁移扩展。
- evidence_summary / evidence_refs 只存脱敏受控信息：绝不存 API Key、绝对路径或图片二进制。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import FinalVideoStatus, FinalVideoUsageStatus

# 名称/说明长度上限（DB 兜底；schema 层亦校验并 strip）
FINAL_VIDEO_TITLE_MAX = 255
FINAL_VIDEO_DESC_MAX = 2000
VERSION_LABEL_MAX = 64
ACTOR_LABEL_MAX = 120


class FinalVideo(Base):
    __tablename__ = "final_video"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 成片媒体文件 = 已有 Asset（经上传或 NAS 只读扫描索引）；RESTRICT：有成片记录时
    # 不允许删除该 Asset 行（成片记录永不悬空）。
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset.id", ondelete="RESTRICT"), index=True
    )
    # 可选绑定业务项目 / 脚本项目：删除时 SET NULL，成片与血缘保留。
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    script_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("script_project.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(FINAL_VIDEO_TITLE_MAX))
    description: Mapped[str | None] = mapped_column(
        String(FINAL_VIDEO_DESC_MAX), nullable=True
    )
    version_label: Mapped[str | None] = mapped_column(
        String(VERSION_LABEL_MAX), nullable=True
    )

    status: Mapped[FinalVideoStatus] = mapped_column(
        pg_enum(FinalVideoStatus, "final_video_status"),
        default=FinalVideoStatus.DRAFT,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        # 同一 Asset 默认只能对应一个活动（未归档）FinalVideo
        Index(
            "uq_final_video_active_asset",
            "asset_id",
            unique=True,
            postgresql_where=text("status != 'archived'"),
        ),
        Index("ix_final_video_status", "status"),
    )


class FinalVideoUsage(Base):
    """成片 ↔ Source Shot 引用关系（一对关系一行；多次出现见 occurrence）。"""

    __tablename__ = "final_video_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    final_video_id: Mapped[int] = mapped_column(
        ForeignKey("final_video.id", ondelete="CASCADE"), index=True
    )
    # RESTRICT：有血缘引用的 Shot 不允许被静默删除（重新分析入口另有 service 守卫）。
    source_shot_id: Mapped[int] = mapped_column(
        ForeignKey("shot.id", ondelete="RESTRICT"), index=True
    )
    # 冗余锚点：创建时从 shot.asset_id 派生，供素材级聚合与后续 PR-C 追溯。
    source_asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset.id", ondelete="RESTRICT"), index=True
    )
    # 创建时的 Shot 代次快照（仅审计/追溯用，不参与业务判断）
    source_shot_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[FinalVideoUsageStatus] = mapped_column(
        pg_enum(FinalVideoUsageStatus, "final_video_usage_status"),
        default=FinalVideoUsageStatus.PROPOSED,
    )
    # 受控业务值（USAGE_EVIDENCE_METHODS 白名单；String 免迁移扩展）
    evidence_method: Mapped[str] = mapped_column(String(32))
    # 置信度可空；人工确认不伪造 confidence=1
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 脱敏、受控摘要（人读）；不存 API Key、绝对路径或图片二进制
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 生成来源结构化引用（机器可读，仅存 ID 与受控枚举），如
    # {"segments": [{"script_project_id": 1, "segment_id": 2, "kind": "locked"}]}
    evidence_refs: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 非可信显示名（无鉴权，不作权限审计依据；同 reviewer_label 范式）
    actor_label: Mapped[str | None] = mapped_column(String(ACTOR_LABEL_MAX), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "final_video_id", "source_shot_id", name="uq_final_video_usage_video_shot"
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="usage_confidence_0_1",
        ),
        Index("ix_final_video_usage_status", "status"),
        # 计数聚合热路径：按 Shot 找 confirmed usage
        Index("ix_fv_usage_shot_status", "source_shot_id", "status"),
        Index("ix_fv_usage_asset_status", "source_asset_id", "status"),
    )


class FinalVideoUsageOccurrence(Base):
    """一条 Usage 内的具体出现时间段（毫秒整数；不影响正式使用次数）。"""

    __tablename__ = "final_video_usage_occurrence"

    id: Mapped[int] = mapped_column(primary_key=True)
    usage_id: Mapped[int] = mapped_column(
        ForeignKey("final_video_usage.id", ondelete="CASCADE"), index=True
    )
    occurrence_index: Mapped[int] = mapped_column(Integer)

    # 源侧时间段：源媒体（Source Asset）时间轴上的毫秒；须落在 Source Shot 区间内
    source_start_ms: Mapped[int] = mapped_column(Integer)
    source_end_ms: Mapped[int] = mapped_column(Integer)
    # 成片侧时间段：Final Video 时间轴上的毫秒；须落在成片时长内
    final_start_ms: Mapped[int] = mapped_column(Integer)
    final_end_ms: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "usage_id", "occurrence_index", name="uq_fv_occurrence_usage_index"
        ),
        CheckConstraint("occurrence_index >= 0", name="occurrence_index_nonneg"),
        CheckConstraint("source_start_ms >= 0", name="occ_source_start_nonneg"),
        CheckConstraint("final_start_ms >= 0", name="occ_final_start_nonneg"),
        CheckConstraint("source_end_ms > source_start_ms", name="occ_source_end_gt_start"),
        CheckConstraint("final_end_ms > final_start_ms", name="occ_final_end_gt_start"),
    )


class FinalVideoUsageEvent(Base):
    """使用血缘审计事件（append-only；与业务变更同事务写入；无更新/删除接口）。

    action 取值见 enums.USAGE_EVENT_ACTIONS（受控 String）。
    actor_label 是非可信显示名（无鉴权）。不保存媒体路径或秘密。
    """

    __tablename__ = "final_video_usage_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    usage_id: Mapped[int] = mapped_column(
        ForeignKey("final_video_usage.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(32))
    before_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    after_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_label: Mapped[str | None] = mapped_column(String(ACTOR_LABEL_MAX), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_fv_usage_event_created_at", "created_at"),
    )
