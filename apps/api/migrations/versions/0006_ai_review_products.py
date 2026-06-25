"""ai review products: products/tags/shot_tag/shot_review_state/review_event

Revision ID: 0006_ai_review_products
Revises: 0005_ai_analysis
Create Date: 2026-06-24

PR-03B 标签体系 + 产品库 + 人工审核（4 层结构）。新增 8 表、5 枚举与 asset.primary_product_id。
不修改既有迁移；不建 pgvector（PR-04）。不动 ai_shot_analysis（AI 原始层保持不变）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_ai_review_products"
down_revision: str | None = "0005_ai_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


product_status = postgresql.ENUM("active", "archived", name="product_status")
review_action = postgresql.ENUM(
    "confirm", "modify", "reject", "unable", "reopen", name="review_action"
)
tag_type = postgresql.ENUM(
    "product", "scene", "action", "shot_type", "marketing", "quality", "risk",
    name="tag_type",
)
review_status = postgresql.ENUM(
    "unreviewed", "pending_review", "confirmed", "modified", "rejected", "unable",
    name="review_status",
)
tag_source = postgresql.ENUM("ai", "human", name="tag_source")

_ENUMS = (product_status, review_action, tag_type, review_status, tag_source)


def upgrade() -> None:
    bind = op.get_bind()
    for e in _ENUMS:
        e.create(bind, checkfirst=True)

    op.create_table(
        "product",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("sku", sa.String(length=255), nullable=True),
        sa.Column("selling_points", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="product_status", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product")),
    )
    op.create_index(
        op.f("ix_product_normalized_name"), "product", ["normalized_name"], unique=False
    )

    op.create_table(
        "review_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("shot_id_snapshot", sa.Integer(), nullable=True),
        sa.Column("shot_generation_snapshot", sa.Integer(), nullable=True),
        sa.Column("source_ai_analysis_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_label", sa.String(length=255), nullable=True),
        sa.Column(
            "action",
            postgresql.ENUM(name="review_action", create_type=False),
            nullable=False,
        ),
        sa.Column("before_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_event")),
    )
    op.create_index(
        op.f("ix_review_event_object_id"), "review_event", ["object_id"], unique=False
    )

    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "tag_type", postgresql.ENUM(name="tag_type", create_type=False), nullable=False
        ),
        sa.Column("tag_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column(
            "status", postgresql.ENUM(name="product_status", create_type=False), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tag")),
        sa.UniqueConstraint("tag_type", "normalized_name", name="uq_tag_type_norm"),
    )
    op.create_index(op.f("ix_tag_normalized_name"), "tag", ["normalized_name"], unique=False)

    op.create_table(
        "product_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"], ["product.id"],
            name=op.f("fk_product_alias_product_id_product"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_alias")),
        sa.UniqueConstraint("product_id", "normalized_alias", name="uq_product_alias_norm"),
    )
    op.create_index(
        op.f("ix_product_alias_normalized_alias"), "product_alias", ["normalized_alias"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_alias_product_id"), "product_alias", ["product_id"], unique=False
    )

    op.create_table(
        "product_image",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.String(length=2048), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"], ["product.id"],
            name=op.f("fk_product_image_product_id_product"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_image")),
    )
    op.create_index(
        op.f("ix_product_image_product_id"), "product_image", ["product_id"], unique=False
    )

    op.create_table(
        "asset_product",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column(
            "source", postgresql.ENUM(name="tag_source", create_type=False), nullable=False
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("match_type", sa.String(length=32), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("confirmed_by", sa.String(length=255), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"],
            name=op.f("fk_asset_product_asset_id_asset"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["product.id"],
            name=op.f("fk_asset_product_product_id_product"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_product")),
        sa.UniqueConstraint("asset_id", "product_id", "source", name="uq_asset_product_src"),
    )
    op.create_index(
        op.f("ix_asset_product_asset_id"), "asset_product", ["asset_id"], unique=False
    )
    op.create_index(
        "ix_asset_product_product_id", "asset_product", ["product_id"], unique=False
    )

    op.create_table(
        "shot_review_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shot_id", sa.Integer(), nullable=False),
        sa.Column("shot_generation", sa.Integer(), nullable=False),
        sa.Column("source_ai_analysis_id", sa.Integer(), nullable=True),
        sa.Column("source_input_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("result_schema_version", sa.Integer(), nullable=True),
        sa.Column(
            "review_status",
            postgresql.ENUM(name="review_status", create_type=False),
            nullable=False,
        ),
        sa.Column("confirmed_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confirmed_product_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_label", sa.String(length=255), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stale_reason", sa.String(length=64), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["confirmed_product_id"], ["product.id"],
            name=op.f("fk_shot_review_state_confirmed_product_id_product"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shot_id"], ["shot.id"],
            name=op.f("fk_shot_review_state_shot_id_shot"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_ai_analysis_id"], ["ai_shot_analysis.id"],
            name=op.f("fk_shot_review_state_source_ai_analysis_id_ai_shot_analysis"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shot_review_state")),
        sa.UniqueConstraint("shot_id", "shot_generation", name="uq_shot_review_shot_gen"),
    )
    op.create_index(
        op.f("ix_shot_review_state_shot_id"), "shot_review_state", ["shot_id"], unique=False
    )
    op.create_index(
        "ix_srs_review_status", "shot_review_state", ["review_status"], unique=False
    )
    op.create_index("ix_srs_stale_at", "shot_review_state", ["stale_at"], unique=False)
    op.create_index(
        "ix_srs_confirmed_product", "shot_review_state", ["confirmed_product_id"], unique=False
    )

    op.create_table(
        "shot_tag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shot_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column(
            "source", postgresql.ENUM(name="tag_source", create_type=False), nullable=False
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_ai_analysis_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_by", sa.String(length=255), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["shot_id"], ["shot.id"],
            name=op.f("fk_shot_tag_shot_id_shot"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_ai_analysis_id"], ["ai_shot_analysis.id"],
            name=op.f("fk_shot_tag_source_ai_analysis_id_ai_shot_analysis"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tag.id"], name=op.f("fk_shot_tag_tag_id_tag"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shot_tag")),
    )
    op.create_index(op.f("ix_shot_tag_shot_id"), "shot_tag", ["shot_id"], unique=False)
    op.create_index("ix_shot_tag_tag_active", "shot_tag", ["tag_id", "active"], unique=False)
    op.create_index(op.f("ix_shot_tag_tag_id"), "shot_tag", ["tag_id"], unique=False)
    # 同一 (shot, tag, source) 至多一条 active；历史 inactive 可多条共存
    op.create_index(
        "uq_shot_tag_active",
        "shot_tag",
        ["shot_id", "tag_id", "source"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    op.create_index(
        "ix_shot_tag_shot_src_active", "shot_tag", ["shot_id", "source", "active"], unique=False
    )
    op.create_index(
        "ix_shot_tag_tag_src_active", "shot_tag", ["tag_id", "source", "active"], unique=False
    )
    op.create_index(
        "ix_shot_tag_src_ai", "shot_tag", ["source_ai_analysis_id"], unique=False
    )

    op.add_column("asset", sa.Column("primary_product_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_asset_primary_product_id_product"),
        "asset", "product", ["primary_product_id"], ["id"], ondelete="SET NULL",
    )
    # PR-03B.1：AI 分析的标签投影状态（ok/error）
    op.add_column(
        "ai_shot_analysis",
        sa.Column("projection_status", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_shot_analysis", "projection_status")
    op.drop_constraint(
        op.f("fk_asset_primary_product_id_product"), "asset", type_="foreignkey"
    )
    op.drop_column("asset", "primary_product_id")

    op.drop_index("uq_shot_tag_active", table_name="shot_tag")
    op.drop_index(op.f("ix_shot_tag_tag_id"), table_name="shot_tag")
    op.drop_index("ix_shot_tag_tag_active", table_name="shot_tag")
    op.drop_index(op.f("ix_shot_tag_shot_id"), table_name="shot_tag")
    op.drop_table("shot_tag")

    op.drop_index(op.f("ix_shot_review_state_shot_id"), table_name="shot_review_state")
    op.drop_table("shot_review_state")

    op.drop_index("ix_asset_product_product_id", table_name="asset_product")
    op.drop_index(op.f("ix_asset_product_asset_id"), table_name="asset_product")
    op.drop_table("asset_product")

    op.drop_index(op.f("ix_product_image_product_id"), table_name="product_image")
    op.drop_table("product_image")

    op.drop_index(op.f("ix_product_alias_product_id"), table_name="product_alias")
    op.drop_index(op.f("ix_product_alias_normalized_alias"), table_name="product_alias")
    op.drop_table("product_alias")

    op.drop_index(op.f("ix_tag_normalized_name"), table_name="tag")
    op.drop_table("tag")

    op.drop_index(op.f("ix_review_event_object_id"), table_name="review_event")
    op.drop_table("review_event")

    op.drop_index(op.f("ix_product_normalized_name"), table_name="product")
    op.drop_table("product")

    bind = op.get_bind()
    for e in (tag_source, review_status, tag_type, review_action, product_status):
        e.drop(bind, checkfirst=True)
