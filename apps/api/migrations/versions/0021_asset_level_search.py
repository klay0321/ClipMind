"""P2a 素材级统一搜索：asset_image_analysis + asset_search_document

- asset_image_analysis：图片素材 AI 理解结果（与 ai_shot_analysis 对称，
  asset_id 唯一 + input_fingerprint 缓存去重）。
- asset_search_document：素材级检索文档（视频=镜头有效文档聚合，图片=
  图片分析结果构建；同一嵌入身份/状态机语义，trgm GIN + HNSW cosine）。

复用既有枚举（ai_shot_analysis_status / search_document_status /
search_embedding_status），不创建新枚举类型。vector/pg_trgm 扩展由 0007 保证。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0021_asset_level_search"
down_revision: str | None = "0020_product_media_operations"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    op.create_table(
        "asset_image_analysis",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("input_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parsed_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_response_excerpt", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="ai_shot_analysis_status", create_type=False),
            nullable=False,
        ),
        sa.Column("degraded_reason", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"],
            name=op.f("fk_asset_image_analysis_asset_id_asset"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["ai_analysis_run.id"],
            name=op.f("fk_asset_image_analysis_run_id_ai_analysis_run"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_image_analysis")),
        sa.UniqueConstraint("asset_id", name=op.f("uq_asset_image_analysis_asset_id")),
    )
    op.create_index(
        "ix_asset_image_analysis_input_fingerprint",
        "asset_image_analysis", ["input_fingerprint"], unique=False,
    )
    op.create_index("ix_aia_status", "asset_image_analysis", ["status"], unique=False)
    op.create_index("ix_aia_run_id", "asset_image_analysis", ["run_id"], unique=False)

    op.create_table(
        "asset_search_document",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("media_kind", sa.String(length=8), nullable=False),
        sa.Column("effective_source", sa.String(length=16), nullable=True),
        sa.Column("source_image_analysis_id", sa.Integer(), nullable=True),
        sa.Column("aggregate_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("result_schema_version", sa.Integer(), nullable=True),
        sa.Column("search_document", sa.Text(), nullable=True),
        sa.Column("normalized_document", sa.Text(), nullable=True),
        sa.Column("search_document_hash", sa.String(length=64), nullable=True),
        sa.Column("document_template_version", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_provider", sa.String(length=64), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("embedding_model_revision", sa.String(length=128), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
        sa.Column("embedding_version", sa.String(length=255), nullable=True),
        sa.Column("normalization_version", sa.String(length=32), nullable=True),
        sa.Column(
            "document_status",
            postgresql.ENUM(name="search_document_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "embedding_status",
            postgresql.ENUM(name="search_embedding_status", create_type=False),
            nullable=False,
        ),
        sa.Column("is_searchable", sa.Boolean(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"],
            name=op.f("fk_asset_search_document_asset_id_asset"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_image_analysis_id"], ["asset_image_analysis.id"],
            name=op.f("fk_asset_search_document_source_image_analysis_id_asset_image_analysis"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_search_document")),
        sa.UniqueConstraint("asset_id", name=op.f("uq_asset_search_document_asset_id")),
    )
    op.create_index("ix_asd_media_kind", "asset_search_document", ["media_kind"], unique=False)
    op.create_index(
        "ix_asd_document_status", "asset_search_document", ["document_status"], unique=False
    )
    op.create_index(
        "ix_asd_embedding_status", "asset_search_document", ["embedding_status"], unique=False
    )
    op.create_index(
        "ix_asd_is_searchable", "asset_search_document", ["is_searchable"], unique=False
    )
    op.create_index(
        "ix_asd_norm_trgm",
        "asset_search_document",
        ["normalized_document"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"normalized_document": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_asd_embedding_hnsw",
        "asset_search_document",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )


def downgrade() -> None:
    op.drop_table("asset_search_document")
    op.drop_table("asset_image_analysis")
