"""PR-03B 标签投影层 + 人工审核层 + 审计层模型。

四层结构（与 PR-03A 的 ``ai_shot_analysis`` 原始层配合）：
- ``tag`` / ``shot_tag``：检索投影层（结构化筛选 + PR-04 搜索）。AI 与人工标签各存一行
  （``source`` 区分），互不覆盖历史；``active`` 标记当前有效。
- ``shot_review_state``：人工当前状态层。每个 (shot_id, shot_generation) 至多一条；绑定
  来源 AI 分析与输入指纹；``lock_version`` 乐观锁防并发覆盖；``stale_*`` 标记因重拆镜头/
  指纹变化而失效。AI 重新分析**绝不**修改本表。
- ``review_event``：审计层，append-only；每次确认/修改/驳回/无法判断都新增一行，不更新旧事件。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
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
from clipmind_shared.models.enums import (
    ProductStatus,
    ReviewAction,
    ReviewStatus,
    TagSource,
    TagType,
)


class Tag(Base):
    """标签字典（去重的标签维度 + 名称）。"""

    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_type: Mapped[TagType] = mapped_column(pg_enum(TagType, "tag_type"))
    # 展示名（保留用户可见原名）+ 标准化名（唯一约束/匹配用）
    tag_name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    # 复用 active/archived 生命周期（归档后新审核不再推荐，历史仍可显示）
    status: Mapped[ProductStatus] = mapped_column(
        pg_enum(ProductStatus, "product_status"), default=ProductStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("tag_type", "normalized_name", name="uq_tag_type_norm"),
    )


class ShotTag(Base):
    """镜头↔标签投影。AI 与人工各存一行（source 区分），互不覆盖历史。"""

    __tablename__ = "shot_tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    shot_id: Mapped[int] = mapped_column(
        ForeignKey("shot.id", ondelete="CASCADE"), index=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"), index=True)
    source: Mapped[TagSource] = mapped_column(pg_enum(TagSource, "tag_source"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_ai_analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_shot_analysis.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 当前是否生效（人工修改审核时在同一事务刷新投影）
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        # 历史共存：保留多条 inactive；同一 (shot, tag, source) 至多一条 active
        Index(
            "uq_shot_tag_active",
            "shot_id",
            "tag_id",
            "source",
            unique=True,
            postgresql_where=text("active"),
        ),
        Index("ix_shot_tag_tag_active", "tag_id", "active"),
        # 投影优先筛选：按 shot/tag + source + active 命中有效标签
        Index("ix_shot_tag_shot_src_active", "shot_id", "source", "active"),
        Index("ix_shot_tag_tag_src_active", "tag_id", "source", "active"),
        Index("ix_shot_tag_src_ai", "source_ai_analysis_id"),
    )


class ShotReviewState(Base):
    """镜头人工审核当前状态（每 shot_generation 一条；乐观锁；可标 stale）。"""

    __tablename__ = "shot_review_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    shot_id: Mapped[int] = mapped_column(
        ForeignKey("shot.id", ondelete="CASCADE"), index=True
    )
    shot_generation: Mapped[int] = mapped_column(Integer)
    # 绑定来源 AI 分析与输入指纹，用于 stale 判定与安全复用
    source_ai_analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_shot_analysis.id", ondelete="SET NULL"), nullable=True
    )
    source_input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    review_status: Mapped[ReviewStatus] = mapped_column(
        pg_enum(ReviewStatus, "review_status"), default=ReviewStatus.UNREVIEWED
    )
    # 人工确认/修改后的结构化结果（与 AI 结果同一 Pydantic Schema 校验）
    confirmed_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confirmed_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("product.id", ondelete="SET NULL"), nullable=True
    )
    reviewer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # PR-07 接用户体系
    reviewer_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stale_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=0)  # 乐观锁

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("shot_id", "shot_generation", name="uq_shot_review_shot_gen"),
        Index("ix_srs_review_status", "review_status"),
        Index("ix_srs_stale_at", "stale_at"),
        Index("ix_srs_confirmed_product", "confirmed_product_id"),
    )


class ReviewEvent(Base):
    """审核审计事件（append-only；每次审核动作新增一行）。"""

    __tablename__ = "review_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    object_type: Mapped[str] = mapped_column(String(32))  # "shot"
    object_id: Mapped[int] = mapped_column(Integer, index=True)
    shot_id_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shot_generation_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_ai_analysis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewer_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[ReviewAction] = mapped_column(pg_enum(ReviewAction, "review_action"))
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
