"""semantic search: pgvector/pg_trgm + shot_search_document

Revision ID: 0007_semantic_search
Revises: 0006_ai_review_products
Create Date: 2026-06-25

PR-04 语义检索基础（Gate A）：
- 启用 pgvector 与 pg_trgm 扩展（IF NOT EXISTS，幂等）；
- 新建 search_document_status / search_embedding_status 枚举与 shot_search_document 表
  （每 (shot_id, shot_generation) 一条有效检索文档：归一化文本 + vector(384) + 嵌入身份 +
  文档/嵌入两层正交状态）；
- 建词法 GIN(pg_trgm) 与向量 HNSW(vector_cosine_ops) 索引。

不修改既有迁移、不改任何既有表/列。downgrade 删除本迁移创建的表/索引/枚举，但**不删除
vector / pg_trgm 扩展**（扩展为共享能力，删除可能破坏其它对象）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0007_semantic_search"
down_revision: str | None = "0006_ai_review_products"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 384

search_document_status = postgresql.ENUM(
    "pending", "indexed", "excluded", name="search_document_status",
)
search_embedding_status = postgresql.ENUM(
    "pending", "embedding", "completed", "degraded", "failed",
    name="search_embedding_status",
)


def upgrade() -> None:
    # 扩展为共享能力，幂等创建（postgres 镜像 pgvector/pgvector:pg16 已内置 vector）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    bind = op.get_bind()
    search_document_status.create(bind, checkfirst=True)
    search_embedding_status.create(bind, checkfirst=True)

    op.create_table(
        "shot_search_document",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shot_id", sa.Integer(), nullable=False),
        sa.Column("shot_generation", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("effective_source", sa.String(length=16), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=True),
        sa.Column("source_ai_analysis_id", sa.Integer(), nullable=True),
        sa.Column("source_review_state_id", sa.Integer(), nullable=True),
        sa.Column("source_review_lock_version", sa.Integer(), nullable=True),
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
            ["shot_id"], ["shot.id"],
            name=op.f("fk_shot_search_document_shot_id_shot"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"],
            name=op.f("fk_shot_search_document_asset_id_asset"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_ai_analysis_id"], ["ai_shot_analysis.id"],
            name=op.f("fk_shot_search_document_source_ai_analysis_id_ai_shot_analysis"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_review_state_id"], ["shot_review_state.id"],
            name=op.f("fk_shot_search_document_source_review_state_id_shot_review_state"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shot_search_document")),
        sa.UniqueConstraint("shot_id", "shot_generation", name="uq_search_doc_shot_gen"),
    )
    op.create_index("ix_ssd_asset_id", "shot_search_document", ["asset_id"], unique=False)
    op.create_index(
        "ix_ssd_document_status", "shot_search_document", ["document_status"], unique=False
    )
    op.create_index(
        "ix_ssd_embedding_status", "shot_search_document", ["embedding_status"], unique=False
    )
    op.create_index("ix_ssd_is_searchable", "shot_search_document", ["is_searchable"], unique=False)
    op.create_index(
        "ix_ssd_doc_hash", "shot_search_document", ["search_document_hash"], unique=False
    )
    op.create_index(
        "ix_ssd_embedding_version", "shot_search_document", ["embedding_version"], unique=False
    )
    op.create_index(
        "ix_ssd_source_ai", "shot_search_document", ["source_ai_analysis_id"], unique=False
    )
    op.create_index(
        "ix_ssd_source_review", "shot_search_document", ["source_review_state_id"], unique=False
    )
    # 词法召回：归一化文档 trigram GIN
    op.create_index(
        "ix_ssd_norm_trgm",
        "shot_search_document",
        ["normalized_document"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"normalized_document": "gin_trgm_ops"},
    )
    # 向量召回：HNSW + cosine（m/ef_construction 默认值，见 models/search.py）
    op.create_index(
        "ix_ssd_embedding_hnsw",
        "shot_search_document",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )


def downgrade() -> None:
    op.drop_index("ix_ssd_embedding_hnsw", table_name="shot_search_document")
    op.drop_index("ix_ssd_norm_trgm", table_name="shot_search_document")
    op.drop_index("ix_ssd_source_review", table_name="shot_search_document")
    op.drop_index("ix_ssd_source_ai", table_name="shot_search_document")
    op.drop_index("ix_ssd_embedding_version", table_name="shot_search_document")
    op.drop_index("ix_ssd_doc_hash", table_name="shot_search_document")
    op.drop_index("ix_ssd_is_searchable", table_name="shot_search_document")
    op.drop_index("ix_ssd_embedding_status", table_name="shot_search_document")
    op.drop_index("ix_ssd_document_status", table_name="shot_search_document")
    op.drop_index("ix_ssd_asset_id", table_name="shot_search_document")
    op.drop_table("shot_search_document")

    bind = op.get_bind()
    search_embedding_status.drop(bind, checkfirst=True)
    search_document_status.drop(bind, checkfirst=True)
    # 注意：不删除 vector / pg_trgm 扩展（共享能力，删除可能破坏其它对象）。
