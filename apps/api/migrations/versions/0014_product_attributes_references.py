"""PR-A2 Gate A：动态产品属性 + 产品参考图库。

新增三表（不改 0013 及更早迁移、不删库重建）：
- product_attribute_definition：按 Category 动态定义的属性（value_type 白名单 + 语义位）
- product_attribute_value：受约束 typed columns，绑定 Family/Variant/SKU 单目标
- product_reference_asset：产品参考图（绑定单目标，存 data_dir 受控相对路径）

复用既有 catalog_status 原生枚举（0013 已建，create_type=False 避免重复 CREATE TYPE）。

Revision ID: 0014_product_attr_refs
Revises: 0013_generic_product_catalog
Create Date: 2026-07-01

注：revision id 保持 ≤32 字符（alembic_version.version_num 为 VARCHAR(32)）；
文件名 0014_product_attributes_references.py 仅供人阅读。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_product_attr_refs"
down_revision: str | None = "0013_generic_product_catalog"
branch_labels: str | None = None
depends_on: str | None = None

# 复用 0013 已建的 catalog_status 原生枚举（不重复 CREATE TYPE / 不在 downgrade 删除）
catalog_status = postgresql.ENUM(
    "draft", "active", "paused", "archived", "merged",
    name="catalog_status", create_type=False,
)


def upgrade() -> None:
    # ---- 属性定义 ----
    op.create_table(
        "product_attribute_definition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("normalized_key", sa.String(length=64), nullable=False),
        sa.Column("name_zh", sa.String(length=255), nullable=False),
        sa.Column("name_en", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("value_type", sa.String(length=16), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("allowed_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validation_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("searchable", sa.Boolean(), nullable=False),
        sa.Column("identity_relevant", sa.Boolean(), nullable=False),
        sa.Column("multi_value", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", catalog_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["category_id"], ["product_category.id"],
            name=op.f("fk_product_attribute_definition_category_id_product_category"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_attribute_definition")),
    )
    op.create_index("ix_attr_def_category_id", "product_attribute_definition", ["category_id"])
    op.create_index(
        "ix_attr_def_identity_relevant", "product_attribute_definition", ["identity_relevant"]
    )
    op.create_index("ix_attr_def_searchable", "product_attribute_definition", ["searchable"])
    op.create_index("ix_attr_def_status", "product_attribute_definition", ["status"])
    op.create_index(
        "uq_attr_def_category_nkey", "product_attribute_definition",
        ["category_id", "normalized_key"], unique=True,
        postgresql_where=sa.text("category_id IS NOT NULL"),
    )
    op.create_index(
        "uq_attr_def_global_nkey", "product_attribute_definition",
        ["normalized_key"], unique=True,
        postgresql_where=sa.text("category_id IS NULL"),
    )

    # ---- 属性值（typed columns，单目标）----
    op.create_table(
        "product_attribute_value",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("definition_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=True),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("sku_id", sa.Integer(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_number", sa.Numeric(), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN family_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN variant_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN sku_id IS NULL THEN 0 ELSE 1 END) = 1",
            name=op.f("ck_product_attribute_value_exactly_one_target"),
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"], ["product_attribute_definition.id"],
            name=op.f("fk_product_attribute_value_definition_id_product_attribute_definition"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["family_id"], ["product_family.id"],
            name=op.f("fk_product_attribute_value_family_id_product_family"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sku_id"], ["product_sku.id"],
            name=op.f("fk_product_attribute_value_sku_id_product_sku"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["product_variant.id"],
            name=op.f("fk_product_attribute_value_variant_id_product_variant"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_attribute_value")),
    )
    op.create_index("ix_attr_value_family_id", "product_attribute_value", ["family_id"])
    op.create_index("ix_attr_value_number", "product_attribute_value", ["value_number"])
    op.create_index("ix_attr_value_sku_id", "product_attribute_value", ["sku_id"])
    op.create_index("ix_attr_value_variant_id", "product_attribute_value", ["variant_id"])
    op.create_index(
        op.f("ix_product_attribute_value_definition_id"),
        "product_attribute_value", ["definition_id"],
    )
    op.create_index(
        "uq_attr_value_family_def", "product_attribute_value", ["definition_id", "family_id"],
        unique=True, postgresql_where=sa.text("family_id IS NOT NULL AND archived_at IS NULL"),
    )
    op.create_index(
        "uq_attr_value_sku_def", "product_attribute_value", ["definition_id", "sku_id"],
        unique=True, postgresql_where=sa.text("sku_id IS NOT NULL AND archived_at IS NULL"),
    )
    op.create_index(
        "uq_attr_value_variant_def", "product_attribute_value", ["definition_id", "variant_id"],
        unique=True, postgresql_where=sa.text("variant_id IS NOT NULL AND archived_at IS NULL"),
    )

    # ---- 产品参考图 ----
    op.create_table(
        "product_reference_asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=True),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("sku_id", sa.Integer(), nullable=True),
        sa.Column("image_path", sa.String(length=2048), nullable=False),
        sa.Column("thumbnail_path", sa.String(length=2048), nullable=True),
        sa.Column("original_filename", sa.String(length=512), nullable=True),
        sa.Column("content_type", sa.String(length=64), nullable=True),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("perceptual_hash", sa.String(length=64), nullable=True),
        sa.Column("angle", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("quality_status", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=16), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN family_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN variant_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN sku_id IS NULL THEN 0 ELSE 1 END) = 1",
            name=op.f("ck_product_reference_asset_exactly_one_target"),
        ),
        sa.ForeignKeyConstraint(
            ["family_id"], ["product_family.id"],
            name=op.f("fk_product_reference_asset_family_id_product_family"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sku_id"], ["product_sku.id"],
            name=op.f("fk_product_reference_asset_sku_id_product_sku"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["product_variant.id"],
            name=op.f("fk_product_reference_asset_variant_id_product_variant"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_reference_asset")),
    )
    op.create_index("ix_ref_asset_family_id", "product_reference_asset", ["family_id"])
    op.create_index("ix_ref_asset_sha256", "product_reference_asset", ["sha256"])
    op.create_index("ix_ref_asset_sku_id", "product_reference_asset", ["sku_id"])
    op.create_index("ix_ref_asset_state", "product_reference_asset", ["state"])
    op.create_index("ix_ref_asset_variant_id", "product_reference_asset", ["variant_id"])
    op.create_index(
        "uq_ref_asset_family_primary", "product_reference_asset", ["family_id"], unique=True,
        postgresql_where=sa.text("family_id IS NOT NULL AND is_primary AND archived_at IS NULL"),
    )
    op.create_index(
        "uq_ref_asset_sku_primary", "product_reference_asset", ["sku_id"], unique=True,
        postgresql_where=sa.text("sku_id IS NOT NULL AND is_primary AND archived_at IS NULL"),
    )
    op.create_index(
        "uq_ref_asset_variant_primary", "product_reference_asset", ["variant_id"], unique=True,
        postgresql_where=sa.text("variant_id IS NOT NULL AND is_primary AND archived_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_ref_asset_variant_primary", table_name="product_reference_asset",
        postgresql_where=sa.text("variant_id IS NOT NULL AND is_primary AND archived_at IS NULL"),
    )
    op.drop_index(
        "uq_ref_asset_sku_primary", table_name="product_reference_asset",
        postgresql_where=sa.text("sku_id IS NOT NULL AND is_primary AND archived_at IS NULL"),
    )
    op.drop_index(
        "uq_ref_asset_family_primary", table_name="product_reference_asset",
        postgresql_where=sa.text("family_id IS NOT NULL AND is_primary AND archived_at IS NULL"),
    )
    op.drop_index("ix_ref_asset_variant_id", table_name="product_reference_asset")
    op.drop_index("ix_ref_asset_state", table_name="product_reference_asset")
    op.drop_index("ix_ref_asset_sku_id", table_name="product_reference_asset")
    op.drop_index("ix_ref_asset_sha256", table_name="product_reference_asset")
    op.drop_index("ix_ref_asset_family_id", table_name="product_reference_asset")
    op.drop_table("product_reference_asset")

    op.drop_index(
        "uq_attr_value_variant_def", table_name="product_attribute_value",
        postgresql_where=sa.text("variant_id IS NOT NULL AND archived_at IS NULL"),
    )
    op.drop_index(
        "uq_attr_value_sku_def", table_name="product_attribute_value",
        postgresql_where=sa.text("sku_id IS NOT NULL AND archived_at IS NULL"),
    )
    op.drop_index(
        "uq_attr_value_family_def", table_name="product_attribute_value",
        postgresql_where=sa.text("family_id IS NOT NULL AND archived_at IS NULL"),
    )
    op.drop_index(
        op.f("ix_product_attribute_value_definition_id"), table_name="product_attribute_value"
    )
    op.drop_index("ix_attr_value_variant_id", table_name="product_attribute_value")
    op.drop_index("ix_attr_value_sku_id", table_name="product_attribute_value")
    op.drop_index("ix_attr_value_number", table_name="product_attribute_value")
    op.drop_index("ix_attr_value_family_id", table_name="product_attribute_value")
    op.drop_table("product_attribute_value")

    op.drop_index(
        "uq_attr_def_global_nkey", table_name="product_attribute_definition",
        postgresql_where=sa.text("category_id IS NULL"),
    )
    op.drop_index(
        "uq_attr_def_category_nkey", table_name="product_attribute_definition",
        postgresql_where=sa.text("category_id IS NOT NULL"),
    )
    op.drop_index("ix_attr_def_status", table_name="product_attribute_definition")
    op.drop_index("ix_attr_def_searchable", table_name="product_attribute_definition")
    op.drop_index("ix_attr_def_identity_relevant", table_name="product_attribute_definition")
    op.drop_index("ix_attr_def_category_id", table_name="product_attribute_definition")
    op.drop_table("product_attribute_definition")
