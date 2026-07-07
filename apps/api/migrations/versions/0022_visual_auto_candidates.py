"""VIS-AUTO：视觉嵌入持久化 + 自动产品候选。

- visual_media_embedding：asset 海报 / shot 关键帧 / 产品参考图的 SigLIP
  向量（768 维，cosine HNSW——同时为以图搜图铺路）；(target, provider,
  model) 唯一；candidates_ref_revision 记录候选决策所依据的参考集摘要。
- visual_product_candidate：自动候选（pending 可重算置换；dismissed/
  confirmed 为人工事实保留）；(target, family) 部分唯一 WHERE pending。

Revision ID: 0022_visual_auto
Revises: 0021_asset_level_search
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers（rev_id ≤32 字符）
revision: str = "0022_visual_auto"
down_revision: str | None = "0021_asset_level_search"
branch_labels = None
depends_on = None

VISUAL_EMBEDDING_DIM = 768


def upgrade() -> None:
    op.create_table(
        "visual_media_embedding",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(VISUAL_EMBEDDING_DIM), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="completed"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("candidates_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidates_ref_revision", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "target_type", "target_id", "provider", "model_id",
            name="uq_vme_target_provider_model",
        ),
    )
    op.create_index("ix_vme_target", "visual_media_embedding", ["target_type", "target_id"])
    op.create_index("ix_vme_status", "visual_media_embedding", ["status"])
    op.create_index(
        "ix_vme_ref_revision", "visual_media_embedding", ["candidates_ref_revision"]
    )
    op.create_index(
        "ix_vme_embedding_hnsw",
        "visual_media_embedding",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )

    op.create_table(
        "visual_product_candidate",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column(
            "family_id",
            sa.Integer(),
            sa.ForeignKey("product_family.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("margin", sa.Float(), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column(
            "best_reference_id",
            sa.Integer(),
            sa.ForeignKey("product_reference_asset.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("thresholds", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column(
            "source_embedding_id",
            sa.Integer(),
            sa.ForeignKey("visual_media_embedding.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "confirmed_link_id",
            sa.Integer(),
            sa.ForeignKey("product_media_link.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_vpc_pending_target_family",
        "visual_product_candidate",
        ["target_type", "target_id", "family_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_vpc_target", "visual_product_candidate", ["target_type", "target_id"])
    op.create_index("ix_vpc_family_status", "visual_product_candidate", ["family_id", "status"])
    op.create_index("ix_vpc_status", "visual_product_candidate", ["status"])


def downgrade() -> None:
    op.drop_table("visual_product_candidate")
    op.drop_table("visual_media_embedding")
