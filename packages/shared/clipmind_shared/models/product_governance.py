"""PR-A2 Gate B：产品入驻治理模型。

四个实体（均为系统能力，不含任何具体产品语义）：
- ProductReadinessPolicy：Category 级资料完整度策略（多历史版本，同 Category 仅一个 active）。
- ProductOnboardingReview：入驻审核记录（绑定 Family/Variant/SKU 单目标；每目标一条当前记录，
  状态流转历史由 CatalogRevision append-only 记录）。生命周期与审核是两条独立轴。
- ProductConfusionPair：易混淆产品关系（同层级、无方向，统一按 小ID/大ID 存储）。
- CatalogRevision：目录业务变更事件（append-only，revision_number 由专用序列单调递增；
  不是 Git、不是备份、不是权限审计；before/after 仅保存脱敏业务字段）。

说明：
- ONBOARDING_STATUSES / CONFUSION_SEVERITIES 等取值用 String 列 + service 白名单（免迁移扩展）。
- ConfusionPair 的 left/right 不建 FK（目标可为三张表之一）；目录实体只归档/合并、无物理删除 API，
  存在性与 canonical 解析由 service 层保证。
- submitted_by / reviewed_by 为**非可信人工显示名**（当前无用户认证），绝不代表权限审计；
  真正用户身份留待权限系统（PR-07+）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
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
from clipmind_shared.models.enums import CatalogStatus

_CATALOG_STATUS = pg_enum(CatalogStatus, "catalog_status")

# CatalogRevision.revision_number 的专用单调序列名（迁移 0015 创建）
CATALOG_REVISION_SEQ = "catalog_revision_seq"


class ProductReadinessPolicy(Base):
    """Category 级资料完整度策略（版本化；同 Category 至多一个 active）。

    数值上下限与 required_angles ⊆ REFERENCE_ANGLES 由 service 白名单校验；
    不接受任何用户可执行表达式。未配置策略时 service 使用系统默认策略
    （来自 Settings，可经环境变量调整，不硬编码产品名）。
    """

    __tablename__ = "product_readiness_policy"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("product_category.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(255))
    min_reference_count: Mapped[int] = mapped_column(Integer, default=3)
    required_angles: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    min_identity_attribute_count: Mapped[int] = mapped_column(Integer, default=1)
    require_primary_reference: Mapped[bool] = mapped_column(Boolean, default=True)
    require_name_en: Mapped[bool] = mapped_column(Boolean, default=False)
    require_alias: Mapped[bool] = mapped_column(Boolean, default=False)
    require_sku_for_active_variant: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[CatalogStatus] = mapped_column(_CATALOG_STATUS, default=CatalogStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("category_id", "version", name="uq_readiness_policy_cat_version"),
        # 同一 Category 至多一个 active policy
        Index(
            "uq_readiness_policy_cat_active",
            "category_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_readiness_policy_status", "status"),
    )


class ProductOnboardingReview(Base):
    """产品入驻审核（每目标一条当前记录；流转历史入 CatalogRevision）。

    status ∈ ONBOARDING_STATUSES；提交时由后端重算 readiness 并保存
    policy 版本与完整度快照——绝不采信前端提交的分数。
    """

    __tablename__ = "product_onboarding_review"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_family.id", ondelete="CASCADE"), nullable=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variant.id", ondelete="CASCADE"), nullable=True
    )
    sku_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_sku.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default="incomplete")
    policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_readiness_policy.id", ondelete="SET NULL"), nullable=True
    )
    policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    readiness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    readiness_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 非可信人工显示名（无认证；不作为权限审计依据）
    submitted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN family_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN variant_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN sku_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="exactly_one_target",
        ),
        # 每目标一条当前审核记录
        Index(
            "uq_onboarding_family",
            "family_id",
            unique=True,
            postgresql_where=text("family_id IS NOT NULL"),
        ),
        Index(
            "uq_onboarding_variant",
            "variant_id",
            unique=True,
            postgresql_where=text("variant_id IS NOT NULL"),
        ),
        Index(
            "uq_onboarding_sku",
            "sku_id",
            unique=True,
            postgresql_where=text("sku_id IS NOT NULL"),
        ),
        Index("ix_onboarding_status", "status"),
    )


class ProductConfusionPair(Base):
    """易混淆产品关系（同层级、无方向；统一 left_id < right_id 存储避免反向重复）。

    distinguishing_features 为人工维护的结构化条目列表
    （feature/left_value/right_value/visible_in_reference/identity_relevant），
    service 校验结构；本阶段不调用 AI。
    """

    __tablename__ = "product_confusion_pair"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_level: Mapped[str] = mapped_column(String(16))  # family / variant / sku
    left_target_id: Mapped[int] = mapped_column(Integer)
    right_target_id: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    distinguishing_features: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / archived
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("left_target_id < right_target_id", name="ordered_pair"),
        UniqueConstraint(
            "target_level", "left_target_id", "right_target_id", name="uq_confusion_pair"
        ),
        Index("ix_confusion_level_left", "target_level", "left_target_id"),
        Index("ix_confusion_level_right", "target_level", "right_target_id"),
        Index("ix_confusion_status", "status"),
    )


class CatalogRevision(Base):
    """目录业务变更事件（append-only）。

    - revision_number 由专用序列 `catalog_revision_seq` 取号，单调递增。
    - before/after 仅保存**脱敏业务字段**（长度受限；不含图片二进制/绝对路径/密钥/环境变量；
      参考图仅保存角度、状态、质量等受控元数据）。
    - 同一业务事务共用 correlation_id，且与业务变更**同事务提交**（失败即一起回滚）。
    - 无 update/delete API；actor_label 为非可信显示名。
    """

    __tablename__ = "catalog_revision"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision_number: Mapped[int] = mapped_column(BigInteger, unique=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32), index=True)
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_catalog_revision_entity", "entity_type", "entity_id"),
        Index("ix_catalog_revision_created_at", "created_at"),
    )
