"""PR-A1 通用产品目录核心模型（Category → Family → Variant → SKU + 通用别名）。

方案 B：与既有扁平 `product` 表**并存**、不改动后者。要点：
- 四级层级全部动态创建；新增产品/别名只是插入数据行，**无需迁移、无产品名枚举/CHECK**。
- **Family 是核心产品实体**；Category 建议必填（service 校验，允许 draft 暂缺）；Variant / SKU 可选。
- 稳定身份：`id` 为 PK，`code` 为稳定业务码（更名不变）；更名只改 `name_*`。
- 生命周期：draft/active/paused/archived/merged；archived/merged **不物理删除**。
- 合并：`merged_into_id` 自引用指向 canonical 目标（SET NULL）；CHECK 防自合并；防环在 service 层。
- 兼容桥：`product_family.legacy_product_id` 软引用既有 `product`（SET NULL，空初始，运营/后续 PR 填，绝不猜层级）。
- 别名：单表多目标，CHECK 恰好一个目标非空 + 每目标 `normalized_alias` partial-unique。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import CatalogStatus

_CATALOG_STATUS = pg_enum(CatalogStatus, "catalog_status")


class ProductCategory(Base):
    """产品类别（顶层品类，动态创建）。"""

    __tablename__ = "product_category"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name_zh: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CatalogStatus] = mapped_column(_CATALOG_STATUS, default=CatalogStatus.DRAFT)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("code", name="uq_product_category_code"),
        Index("ix_product_category_status", "status"),
    )


class ProductFamily(Base):
    """产品族 / 产品系列（核心产品实体，动态创建）。"""

    __tablename__ = "product_family"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_category.id", ondelete="SET NULL"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(64))
    name_zh: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CatalogStatus] = mapped_column(_CATALOG_STATUS, default=CatalogStatus.DRAFT)
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_family.id", ondelete="SET NULL"), nullable=True
    )
    # 兼容桥：软引用既有扁平 product（不猜层级，空初始）
    legacy_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("product.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("code", name="uq_product_family_code"),
        CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id <> id", name="no_self_merge"
        ),
        Index("ix_product_family_category_id", "category_id"),
        Index("ix_product_family_status", "status"),
        Index("ix_product_family_merged_into_id", "merged_into_id"),
        # 一个 legacy product 至多桥接一个 family
        Index(
            "uq_product_family_legacy_product",
            "legacy_product_id",
            unique=True,
            postgresql_where=text("legacy_product_id IS NOT NULL"),
        ),
    )


class ProductVariant(Base):
    """产品变体（族下可区分版本，可选，动态创建）。"""

    __tablename__ = "product_variant"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(
        ForeignKey("product_family.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(64))
    name_zh: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CatalogStatus] = mapped_column(_CATALOG_STATUS, default=CatalogStatus.DRAFT)
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variant.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("code", name="uq_product_variant_code"),
        CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id <> id", name="no_self_merge"
        ),
        Index("ix_product_variant_status", "status"),
        Index("ix_product_variant_merged_into_id", "merged_into_id"),
    )


class ProductSKU(Base):
    """产品 SKU / 货号（可选，可直接属于 Family 或 Variant，动态创建）。"""

    __tablename__ = "product_sku"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(
        ForeignKey("product_family.id", ondelete="CASCADE"), index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variant.id", ondelete="SET NULL"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(64))
    sku_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name_zh: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[CatalogStatus] = mapped_column(_CATALOG_STATUS, default=CatalogStatus.DRAFT)
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_sku.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("code", name="uq_product_sku_code"),
        CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id <> id", name="no_self_merge"
        ),
        Index("ix_product_sku_variant_id", "variant_id"),
        Index("ix_product_sku_status", "status"),
        Index("ix_product_sku_merged_into_id", "merged_into_id"),
        # sku_code 非空时全局唯一
        Index(
            "uq_product_sku_sku_code",
            "sku_code",
            unique=True,
            postgresql_where=text("sku_code IS NOT NULL"),
        ),
    )


class ProductCatalogAlias(Base):
    """通用产品目录别名（单表多目标，CHECK 恰好一个目标非空）。

    支持中文/英文/简称/文件夹别名/历史名称/SKU 别名（`alias_type`）。
    文件夹别名仅作候选线索，绝不作产品判定真值。
    """

    __tablename__ = "product_catalog_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_category.id", ondelete="CASCADE"), nullable=True
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
    alias: Mapped[str] = mapped_column(String(255))
    normalized_alias: Mapped[str] = mapped_column(String(255), index=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    alias_type: Mapped[str] = mapped_column(String(32))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN category_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN family_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN variant_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN sku_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="exactly_one_target",
        ),
        # 每个目标下 normalized_alias 唯一（partial unique per target）
        Index(
            "uq_catalog_alias_category_norm",
            "category_id",
            "normalized_alias",
            unique=True,
            postgresql_where=text("category_id IS NOT NULL"),
        ),
        Index(
            "uq_catalog_alias_family_norm",
            "family_id",
            "normalized_alias",
            unique=True,
            postgresql_where=text("family_id IS NOT NULL"),
        ),
        Index(
            "uq_catalog_alias_variant_norm",
            "variant_id",
            "normalized_alias",
            unique=True,
            postgresql_where=text("variant_id IS NOT NULL"),
        ),
        Index(
            "uq_catalog_alias_sku_norm",
            "sku_id",
            "normalized_alias",
            unique=True,
            postgresql_where=text("sku_id IS NOT NULL"),
        ),
    )
