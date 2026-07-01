"""generic product catalog core: category/family/variant/sku + catalog alias

Revision ID: 0013_generic_product_catalog
Revises: 0012_library_export_features
Create Date: 2026-06-30

PR-A1 通用产品目录核心（方案 B）。新增 5 表 + catalog_status 枚举 +
product_family.legacy_product_id 兼容桥（软引用既有 product，空初始）。

非破坏：不改既有 product / product_alias / product_image / asset_product 及其引用；
不改历史迁移 0001-0012；不写入 seed 产品名；不猜产品层级。
一次性建通用基础 Schema；此后新增产品 / 别名只是插入数据、免迁移。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_generic_product_catalog"
down_revision: str | None = "0012_library_export_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 目录节点生命周期枚举（显式建/删，避免多表内联重复 CREATE TYPE 冲突）
catalog_status = postgresql.ENUM(
    "draft", "active", "paused", "archived", "merged", name="catalog_status"
)


def _status_col() -> sa.Column:
    return sa.Column(
        "status",
        postgresql.ENUM(name="catalog_status", create_type=False),
        nullable=False,
    )


def upgrade() -> None:
    bind = op.get_bind()
    catalog_status.create(bind, checkfirst=True)

    op.create_table(
        "product_category",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name_zh", sa.String(length=255), nullable=False),
        sa.Column("name_en", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        _status_col(),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_category")),
        sa.UniqueConstraint("code", name="uq_product_category_code"),
    )
    op.create_index(
        "ix_product_category_status", "product_category", ["status"], unique=False
    )

    op.create_table(
        "product_family",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name_zh", sa.String(length=255), nullable=False),
        sa.Column("name_en", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        _status_col(),
        sa.Column("merged_into_id", sa.Integer(), nullable=True),
        sa.Column("legacy_product_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id <> id",
            name=op.f("ck_product_family_no_self_merge"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["product_category.id"],
            name=op.f("fk_product_family_category_id_product_category"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["legacy_product_id"], ["product.id"],
            name=op.f("fk_product_family_legacy_product_id_product"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_id"], ["product_family.id"],
            name=op.f("fk_product_family_merged_into_id_product_family"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_family")),
        sa.UniqueConstraint("code", name="uq_product_family_code"),
    )
    op.create_index(
        "ix_product_family_category_id", "product_family", ["category_id"], unique=False
    )
    op.create_index(
        "ix_product_family_merged_into_id", "product_family", ["merged_into_id"],
        unique=False,
    )
    op.create_index(
        "ix_product_family_status", "product_family", ["status"], unique=False
    )
    op.create_index(
        "uq_product_family_legacy_product", "product_family", ["legacy_product_id"],
        unique=True, postgresql_where=sa.text("legacy_product_id IS NOT NULL"),
    )

    op.create_table(
        "product_variant",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name_zh", sa.String(length=255), nullable=False),
        sa.Column("name_en", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        _status_col(),
        sa.Column("merged_into_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id <> id",
            name=op.f("ck_product_variant_no_self_merge"),
        ),
        sa.ForeignKeyConstraint(
            ["family_id"], ["product_family.id"],
            name=op.f("fk_product_variant_family_id_product_family"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_id"], ["product_variant.id"],
            name=op.f("fk_product_variant_merged_into_id_product_variant"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_variant")),
        sa.UniqueConstraint("code", name="uq_product_variant_code"),
    )
    op.create_index(
        op.f("ix_product_variant_family_id"), "product_variant", ["family_id"],
        unique=False,
    )
    op.create_index(
        "ix_product_variant_merged_into_id", "product_variant", ["merged_into_id"],
        unique=False,
    )
    op.create_index(
        "ix_product_variant_status", "product_variant", ["status"], unique=False
    )

    op.create_table(
        "product_sku",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("sku_code", sa.String(length=128), nullable=True),
        sa.Column("name_zh", sa.String(length=255), nullable=False),
        sa.Column("name_en", sa.String(length=255), nullable=True),
        _status_col(),
        sa.Column("merged_into_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id <> id",
            name=op.f("ck_product_sku_no_self_merge"),
        ),
        sa.ForeignKeyConstraint(
            ["family_id"], ["product_family.id"],
            name=op.f("fk_product_sku_family_id_product_family"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_id"], ["product_sku.id"],
            name=op.f("fk_product_sku_merged_into_id_product_sku"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["product_variant.id"],
            name=op.f("fk_product_sku_variant_id_product_variant"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_sku")),
        sa.UniqueConstraint("code", name="uq_product_sku_code"),
    )
    op.create_index(
        op.f("ix_product_sku_family_id"), "product_sku", ["family_id"], unique=False
    )
    op.create_index(
        "ix_product_sku_merged_into_id", "product_sku", ["merged_into_id"], unique=False
    )
    op.create_index("ix_product_sku_status", "product_sku", ["status"], unique=False)
    op.create_index(
        "ix_product_sku_variant_id", "product_sku", ["variant_id"], unique=False
    )
    op.create_index(
        "uq_product_sku_sku_code", "product_sku", ["sku_code"], unique=True,
        postgresql_where=sa.text("sku_code IS NOT NULL"),
    )

    op.create_table(
        "product_catalog_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("family_id", sa.Integer(), nullable=True),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("sku_id", sa.Integer(), nullable=True),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("alias_type", sa.String(length=32), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN category_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN family_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN variant_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN sku_id IS NULL THEN 0 ELSE 1 END) = 1",
            name=op.f("ck_product_catalog_alias_exactly_one_target"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["product_category.id"],
            name=op.f("fk_product_catalog_alias_category_id_product_category"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["family_id"], ["product_family.id"],
            name=op.f("fk_product_catalog_alias_family_id_product_family"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sku_id"], ["product_sku.id"],
            name=op.f("fk_product_catalog_alias_sku_id_product_sku"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["product_variant.id"],
            name=op.f("fk_product_catalog_alias_variant_id_product_variant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_catalog_alias")),
    )
    op.create_index(
        op.f("ix_product_catalog_alias_normalized_alias"), "product_catalog_alias",
        ["normalized_alias"], unique=False,
    )
    op.create_index(
        "uq_catalog_alias_category_norm", "product_catalog_alias",
        ["category_id", "normalized_alias"], unique=True,
        postgresql_where=sa.text("category_id IS NOT NULL"),
    )
    op.create_index(
        "uq_catalog_alias_family_norm", "product_catalog_alias",
        ["family_id", "normalized_alias"], unique=True,
        postgresql_where=sa.text("family_id IS NOT NULL"),
    )
    op.create_index(
        "uq_catalog_alias_sku_norm", "product_catalog_alias",
        ["sku_id", "normalized_alias"], unique=True,
        postgresql_where=sa.text("sku_id IS NOT NULL"),
    )
    op.create_index(
        "uq_catalog_alias_variant_norm", "product_catalog_alias",
        ["variant_id", "normalized_alias"], unique=True,
        postgresql_where=sa.text("variant_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_catalog_alias_variant_norm", table_name="product_catalog_alias",
        postgresql_where=sa.text("variant_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_catalog_alias_sku_norm", table_name="product_catalog_alias",
        postgresql_where=sa.text("sku_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_catalog_alias_family_norm", table_name="product_catalog_alias",
        postgresql_where=sa.text("family_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_catalog_alias_category_norm", table_name="product_catalog_alias",
        postgresql_where=sa.text("category_id IS NOT NULL"),
    )
    op.drop_index(
        op.f("ix_product_catalog_alias_normalized_alias"),
        table_name="product_catalog_alias",
    )
    op.drop_table("product_catalog_alias")

    op.drop_index(
        "uq_product_sku_sku_code", table_name="product_sku",
        postgresql_where=sa.text("sku_code IS NOT NULL"),
    )
    op.drop_index("ix_product_sku_variant_id", table_name="product_sku")
    op.drop_index("ix_product_sku_status", table_name="product_sku")
    op.drop_index("ix_product_sku_merged_into_id", table_name="product_sku")
    op.drop_index(op.f("ix_product_sku_family_id"), table_name="product_sku")
    op.drop_table("product_sku")

    op.drop_index("ix_product_variant_status", table_name="product_variant")
    op.drop_index("ix_product_variant_merged_into_id", table_name="product_variant")
    op.drop_index(op.f("ix_product_variant_family_id"), table_name="product_variant")
    op.drop_table("product_variant")

    op.drop_index(
        "uq_product_family_legacy_product", table_name="product_family",
        postgresql_where=sa.text("legacy_product_id IS NOT NULL"),
    )
    op.drop_index("ix_product_family_status", table_name="product_family")
    op.drop_index("ix_product_family_merged_into_id", table_name="product_family")
    op.drop_index("ix_product_family_category_id", table_name="product_family")
    op.drop_table("product_family")

    op.drop_index("ix_product_category_status", table_name="product_category")
    op.drop_table("product_category")

    catalog_status.drop(op.get_bind(), checkfirst=True)
