"""PR-A2 Gate B：产品入驻治理。

新增四表 + 一序列（不改 0014 及更早迁移、不删库重建）：
- product_readiness_policy：Category 级完整度策略（版本化，单 active partial-unique）
- product_onboarding_review：入驻审核（单目标 CHECK，每目标一条当前记录）
- product_confusion_pair：同层级无向混淆关系（left<right 有序 + 唯一）
- catalog_revision：append-only 变更事件（revision_number 取自 catalog_revision_seq）

复用既有 catalog_status 原生枚举（0013 已建，create_type=False）。
downgrade 删四表与序列，不删 catalog_status、不物理删除参考图片文件。

Revision ID: 0015_product_onboarding_gov
Revises: 0014_product_attr_refs
Create Date: 2026-07-01

注：revision id ≤32 字符（alembic_version.version_num 为 VARCHAR(32)）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_product_onboarding_gov"
down_revision: str | None = "0014_product_attr_refs"
branch_labels: str | None = None
depends_on: str | None = None

catalog_status = postgresql.ENUM(
    "draft", "active", "paused", "archived", "merged",
    name="catalog_status", create_type=False,
)


def upgrade() -> None:
    # ---- 变更事件序列（revision_number 单调递增）----
    op.execute("CREATE SEQUENCE IF NOT EXISTS catalog_revision_seq")

    # ---- catalog_revision（append-only）----
    op.create_table(
        "catalog_revision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("change_summary", sa.String(length=500), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("actor_label", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_revision")),
        sa.UniqueConstraint(
            "revision_number", name=op.f("uq_catalog_revision_revision_number")
        ),
    )
    op.create_index(op.f("ix_catalog_revision_action"), "catalog_revision", ["action"])
    op.create_index(
        op.f("ix_catalog_revision_correlation_id"), "catalog_revision", ["correlation_id"]
    )
    op.create_index("ix_catalog_revision_created_at", "catalog_revision", ["created_at"])
    op.create_index(
        "ix_catalog_revision_entity", "catalog_revision", ["entity_type", "entity_id"]
    )

    # ---- product_confusion_pair ----
    op.create_table(
        "product_confusion_pair",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("target_level", sa.String(length=16), nullable=False),
        sa.Column("left_target_id", sa.Integer(), nullable=False),
        sa.Column("right_target_id", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "distinguishing_features", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "left_target_id < right_target_id",
            name=op.f("ck_product_confusion_pair_ordered_pair"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_confusion_pair")),
        sa.UniqueConstraint(
            "target_level", "left_target_id", "right_target_id", name="uq_confusion_pair"
        ),
    )
    op.create_index(
        "ix_confusion_level_left", "product_confusion_pair", ["target_level", "left_target_id"]
    )
    op.create_index(
        "ix_confusion_level_right",
        "product_confusion_pair",
        ["target_level", "right_target_id"],
    )
    op.create_index("ix_confusion_status", "product_confusion_pair", ["status"])

    # ---- product_readiness_policy ----
    op.create_table(
        "product_readiness_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("min_reference_count", sa.Integer(), nullable=False),
        sa.Column("required_angles", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("min_identity_attribute_count", sa.Integer(), nullable=False),
        sa.Column("require_primary_reference", sa.Boolean(), nullable=False),
        sa.Column("require_name_en", sa.Boolean(), nullable=False),
        sa.Column("require_alias", sa.Boolean(), nullable=False),
        sa.Column("require_sku_for_active_variant", sa.Boolean(), nullable=False),
        sa.Column("status", catalog_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["category_id"], ["product_category.id"],
            name=op.f("fk_product_readiness_policy_category_id_product_category"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_readiness_policy")),
        sa.UniqueConstraint("category_id", "version", name="uq_readiness_policy_cat_version"),
    )
    op.create_index(
        op.f("ix_product_readiness_policy_category_id"),
        "product_readiness_policy",
        ["category_id"],
    )
    op.create_index("ix_readiness_policy_status", "product_readiness_policy", ["status"])
    op.create_index(
        "uq_readiness_policy_cat_active",
        "product_readiness_policy",
        ["category_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # ---- product_onboarding_review ----
    op.create_table(
        "product_onboarding_review",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=True),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("sku_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=True),
        sa.Column("readiness_score", sa.Integer(), nullable=True),
        sa.Column("readiness_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.String(length=64), nullable=True),
        sa.Column("reviewed_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN family_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN variant_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN sku_id IS NULL THEN 0 ELSE 1 END) = 1",
            name=op.f("ck_product_onboarding_review_exactly_one_target"),
        ),
        sa.ForeignKeyConstraint(
            ["family_id"], ["product_family.id"],
            name=op.f("fk_product_onboarding_review_family_id_product_family"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["product_readiness_policy.id"],
            name=op.f("fk_product_onboarding_review_policy_id_product_readiness_policy"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sku_id"], ["product_sku.id"],
            name=op.f("fk_product_onboarding_review_sku_id_product_sku"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["product_variant.id"],
            name=op.f("fk_product_onboarding_review_variant_id_product_variant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_onboarding_review")),
    )
    op.create_index("ix_onboarding_status", "product_onboarding_review", ["status"])
    op.create_index(
        "uq_onboarding_family",
        "product_onboarding_review",
        ["family_id"],
        unique=True,
        postgresql_where=sa.text("family_id IS NOT NULL"),
    )
    op.create_index(
        "uq_onboarding_sku",
        "product_onboarding_review",
        ["sku_id"],
        unique=True,
        postgresql_where=sa.text("sku_id IS NOT NULL"),
    )
    op.create_index(
        "uq_onboarding_variant",
        "product_onboarding_review",
        ["variant_id"],
        unique=True,
        postgresql_where=sa.text("variant_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_onboarding_variant",
        table_name="product_onboarding_review",
        postgresql_where=sa.text("variant_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_onboarding_sku",
        table_name="product_onboarding_review",
        postgresql_where=sa.text("sku_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_onboarding_family",
        table_name="product_onboarding_review",
        postgresql_where=sa.text("family_id IS NOT NULL"),
    )
    op.drop_index("ix_onboarding_status", table_name="product_onboarding_review")
    op.drop_table("product_onboarding_review")

    op.drop_index(
        "uq_readiness_policy_cat_active",
        table_name="product_readiness_policy",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_index("ix_readiness_policy_status", table_name="product_readiness_policy")
    op.drop_index(
        op.f("ix_product_readiness_policy_category_id"), table_name="product_readiness_policy"
    )
    op.drop_table("product_readiness_policy")

    op.drop_index("ix_confusion_status", table_name="product_confusion_pair")
    op.drop_index("ix_confusion_level_right", table_name="product_confusion_pair")
    op.drop_index("ix_confusion_level_left", table_name="product_confusion_pair")
    op.drop_table("product_confusion_pair")

    op.drop_index("ix_catalog_revision_entity", table_name="catalog_revision")
    op.drop_index("ix_catalog_revision_created_at", table_name="catalog_revision")
    op.drop_index(op.f("ix_catalog_revision_correlation_id"), table_name="catalog_revision")
    op.drop_index(op.f("ix_catalog_revision_action"), table_name="catalog_revision")
    op.drop_table("catalog_revision")

    op.execute("DROP SEQUENCE IF EXISTS catalog_revision_seq")
