"""PR-06B saved search / favorite / dynamic collection / bundle export

Revision ID: 0012_library_export_features
Revises: 0011_export_center
Create Date: 2026-06-28

（revision id 受 alembic_version.version_num varchar(32) 限制取简短名
``0012_library_export_features``；内容即 saved_search + favorite + dynamic_collection
+ bundle_export 四张表。）

PR-06B（新建表，不改既有表、不回填）：
- saved_search：保存搜索条件（query JSONB，project_id 可空 SET NULL）。
- favorite：四类收藏（asset→asset_id / 其余→shot_id，部分唯一索引去重）。
- dynamic_collection：查询型集合（必须归属 project，CASCADE；query JSONB，实时 re-run）。
- bundle_export：多镜头 ZIP 打包导出（复用 export_status 枚举，project_id 可空 SET NULL）。

新增枚举 search_kind / favorite_target_type；复用既有 export_status（create_type=False）。
downgrade 逆序删表与新枚举，**不删 export_status（共享）**，绝不触碰业务/导出数据，回到 0011。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_library_export_features"
down_revision: str | None = "0011_export_center"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


search_kind = postgresql.ENUM(
    "shot_search", "description_match", name="search_kind"
)
favorite_target_type = postgresql.ENUM(
    "asset", "shot", "search_result", "script_match_result",
    name="favorite_target_type",
)


def upgrade() -> None:
    bind = op.get_bind()
    search_kind.create(bind, checkfirst=True)
    favorite_target_type.create(bind, checkfirst=True)

    # ---- saved_search ----
    op.create_table(
        "saved_search",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "search_kind",
            postgresql.ENUM(name="search_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("query", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("lock_version >= 1", name="ck_saved_search_lock_version_min1"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"],
            name=op.f("fk_saved_search_project_id_project"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_search")),
    )
    op.create_index(op.f("ix_saved_search_project_id"), "saved_search", ["project_id"])

    # ---- favorite ----
    op.create_table(
        "favorite",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "target_type",
            postgresql.ENUM(name="favorite_target_type", create_type=False),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("shot_id", sa.Integer(), nullable=True),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(target_type = 'asset' AND asset_id IS NOT NULL AND shot_id IS NULL) OR "
            "(target_type <> 'asset' AND shot_id IS NOT NULL AND asset_id IS NULL)",
            name="ck_favorite_favorite_target_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"],
            name=op.f("fk_favorite_asset_id_asset"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shot_id"], ["shot.id"],
            name=op.f("fk_favorite_shot_id_shot"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_favorite")),
    )
    op.create_index(op.f("ix_favorite_asset_id"), "favorite", ["asset_id"])
    op.create_index(op.f("ix_favorite_shot_id"), "favorite", ["shot_id"])
    op.create_index(
        "uq_favorite_asset", "favorite", ["asset_id"], unique=True,
        postgresql_where=sa.text("target_type = 'asset'"),
    )
    op.create_index(
        "uq_favorite_shot", "favorite", ["target_type", "shot_id"], unique=True,
        postgresql_where=sa.text("shot_id IS NOT NULL"),
    )

    # ---- dynamic_collection（必须归属 project，CASCADE）----
    op.create_table(
        "dynamic_collection",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column(
            "search_kind",
            postgresql.ENUM(name="search_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("query", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "lock_version >= 1", name="ck_dynamic_collection_lock_version_min1"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"],
            name=op.f("fk_dynamic_collection_project_id_project"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dynamic_collection")),
    )
    op.create_index(
        op.f("ix_dynamic_collection_project_id"), "dynamic_collection", ["project_id"]
    )

    # ---- bundle_export（复用 export_status 枚举，不新建类型）----
    op.create_table(
        "bundle_export",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("export_uuid", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="export_status", create_type=False),
            nullable=False,
        ),
        sa.Column("shot_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("output_path", sa.String(length=2048), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"],
            name=op.f("fk_bundle_export_project_id_project"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bundle_export")),
        sa.UniqueConstraint("export_uuid", name=op.f("uq_bundle_export_export_uuid")),
    )
    op.create_index(
        op.f("ix_bundle_export_project_id"), "bundle_export", ["project_id"]
    )
    op.create_index("ix_bundle_export_status", "bundle_export", ["status"])


def downgrade() -> None:
    op.drop_index("ix_bundle_export_status", table_name="bundle_export")
    op.drop_index(op.f("ix_bundle_export_project_id"), table_name="bundle_export")
    op.drop_table("bundle_export")

    op.drop_index(
        op.f("ix_dynamic_collection_project_id"), table_name="dynamic_collection"
    )
    op.drop_table("dynamic_collection")

    op.drop_index("uq_favorite_shot", table_name="favorite")
    op.drop_index("uq_favorite_asset", table_name="favorite")
    op.drop_index(op.f("ix_favorite_shot_id"), table_name="favorite")
    op.drop_index(op.f("ix_favorite_asset_id"), table_name="favorite")
    op.drop_table("favorite")

    op.drop_index(op.f("ix_saved_search_project_id"), table_name="saved_search")
    op.drop_table("saved_search")

    bind = op.get_bind()
    favorite_target_type.drop(bind, checkfirst=True)
    search_kind.drop(bind, checkfirst=True)
