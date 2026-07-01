"""PR-A2 Gate A：动态产品属性（定义 + 受约束的值）。

设计（见 .local/pr-a2a/attribute-storage-decision.md，脱敏审计决策）：
- **受约束的分列存储**（typed columns + `value_type` 白名单），**不用完全无约束自由 JSON**。
- 两表：`ProductAttributeDefinition`（系统能力/元数据，按 Category 动态定义）+
  `ProductAttributeValue`（值绑定到 Family / Variant / SKU **单目标**）。
- Category 只定义属性、不直接存具体值；Variant/SKU 继承 Family 的 Category（service 校验）。
- 值按 `definition.value_type` 落到对应 typed column，CHECK 保证「恰好填与类型匹配的那一列」由
  service 强校验 + DB 单目标 CHECK 兜底；enum/multi_enum 的取值须命中 `allowed_values`。
- 归档用 `archived_at` 软归档，历史值保留可审计；同目标同定义**至多一个活动值**（partial-unique）。
- **绝不把具体产品属性写进 Python/TS 枚举**；新增属性只是插入 `attribute_definition` 数据行、免迁移。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import CatalogStatus

_CATALOG_STATUS = pg_enum(CatalogStatus, "catalog_status")


class ProductAttributeDefinition(Base):
    """动态属性定义（系统能力，按 Category 动态创建）。

    `key` 为稳定业务码（更名只改 `name_*`，不改 key）；`value_type` 取受控白名单
    `ATTRIBUTE_VALUE_TYPES`；`allowed_values` 仅 enum/multi_enum 使用；`validation_rules`
    经 service 白名单校验（绝不执行用户表达式/代码）。
    """

    __tablename__ = "product_attribute_definition"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 作用域：某属性归属的品类；NULL = 全局通用属性
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_category.id", ondelete="SET NULL"), nullable=True
    )
    key: Mapped[str] = mapped_column(String(64))
    normalized_key: Mapped[str] = mapped_column(String(64))
    name_zh: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(String(16))
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 仅 enum/multi_enum 使用：受控取值白名单（字符串数组）
    allowed_values: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # service 白名单校验后的验证规则（如 {min,max,max_length,pattern}）——绝不执行用户代码
    validation_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    searchable: Mapped[bool] = mapped_column(Boolean, default=False)
    identity_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    multi_value: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[CatalogStatus] = mapped_column(_CATALOG_STATUS, default=CatalogStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # key 归一化唯一：同一 Category 内唯一；全局（category 为空）之间唯一
        Index(
            "uq_attr_def_category_nkey",
            "category_id",
            "normalized_key",
            unique=True,
            postgresql_where=text("category_id IS NOT NULL"),
        ),
        Index(
            "uq_attr_def_global_nkey",
            "normalized_key",
            unique=True,
            postgresql_where=text("category_id IS NULL"),
        ),
        Index("ix_attr_def_category_id", "category_id"),
        Index("ix_attr_def_status", "status"),
        Index("ix_attr_def_searchable", "searchable"),
        Index("ix_attr_def_identity_relevant", "identity_relevant"),
    )


class ProductAttributeValue(Base):
    """属性值（受约束 typed columns，绑定 Family / Variant / SKU 单目标）。

    按 `definition.value_type` 只填对应 value_* 列（service 强校验，DB CHECK 兜底单目标）：
    text/enum→value_text，number/measurement→value_number，boolean→value_boolean，
    multi_enum→value_json，date→value_date。归档不物理删除；同目标同定义至多一个活动值。
    """

    __tablename__ = "product_attribute_value"

    id: Mapped[int] = mapped_column(primary_key=True)
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("product_attribute_definition.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_family.id", ondelete="CASCADE"), nullable=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variant.id", ondelete="CASCADE"), nullable=True
    )
    sku_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_sku.id", ondelete="CASCADE"), nullable=True
    )
    # typed columns：按 value_type 只填其一
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_number: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    value_boolean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_json: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
        Index("ix_attr_value_family_id", "family_id"),
        Index("ix_attr_value_variant_id", "variant_id"),
        Index("ix_attr_value_sku_id", "sku_id"),
        # 同目标同定义至多一个活动值（归档值不受约束，形成可追溯值历史）
        Index(
            "uq_attr_value_family_def",
            "definition_id",
            "family_id",
            unique=True,
            postgresql_where=text("family_id IS NOT NULL AND archived_at IS NULL"),
        ),
        Index(
            "uq_attr_value_variant_def",
            "definition_id",
            "variant_id",
            unique=True,
            postgresql_where=text("variant_id IS NOT NULL AND archived_at IS NULL"),
        ),
        Index(
            "uq_attr_value_sku_def",
            "definition_id",
            "sku_id",
            unique=True,
            postgresql_where=text("sku_id IS NOT NULL AND archived_at IS NULL"),
        ),
        # 数值检索索引（value_text 为可变长 Text，btree 有行大小上限，暂不索引）
        Index("ix_attr_value_number", "value_number"),
    )
