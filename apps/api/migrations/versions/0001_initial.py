"""initial schema: source_directory, scan_run, asset

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-23

PR-01 初始结构。不创建 pgvector 扩展/向量列（推迟到 PR-04 独立迁移）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


asset_status = postgresql.ENUM(
    "discovered",
    "indexed",
    "error",
    "source_missing",
    "pending",
    "processing",
    "shot_split",
    "ai_analyzing",
    "pending_review",
    "searchable",
    "paused",
    "archived",
    name="asset_status",
)
scan_status = postgresql.ENUM(
    "never_scanned",
    "queued",
    "scanning",
    "completed",
    "failed",
    "cancelled",
    name="scan_status",
)
scan_run_status = postgresql.ENUM(
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    name="scan_run_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    asset_status.create(bind, checkfirst=True)
    scan_status.create(bind, checkfirst=True)
    scan_run_status.create(bind, checkfirst=True)

    op.create_table(
        "source_directory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("mount_path", sa.String(length=1024), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("recursive", sa.Boolean(), nullable=False),
        sa.Column("include_extensions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("exclude_patterns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column(
            "scan_status",
            postgresql.ENUM(name="scan_status", create_type=False),
            nullable=False,
        ),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_source_directory"),
    )

    op.create_table(
        "scan_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_directory_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="scan_run_status", create_type=False),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_name", sa.String(length=255), nullable=True),
        sa.Column("files_discovered", sa.Integer(), nullable=False),
        sa.Column("files_new", sa.Integer(), nullable=False),
        sa.Column("files_modified", sa.Integer(), nullable=False),
        sa.Column("files_missing", sa.Integer(), nullable=False),
        sa.Column("files_errored", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_directory_id"],
            ["source_directory.id"],
            name="fk_scan_run_source_directory_id_source_directory",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scan_run"),
    )
    op.create_index(
        "ix_scan_run_source_directory_id", "scan_run", ["source_directory_id"], unique=False
    )
    # 每目录至多一个活动扫描（queued/running）
    op.create_index(
        "uq_active_scan_run",
        "scan_run",
        ["source_directory_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_directory_id", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.String(length=2048), nullable=False),
        sa.Column("normalized_relative_path", sa.String(length=2048), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quick_hash", sa.String(length=64), nullable=True),
        sa.Column("full_hash", sa.String(length=64), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("video_codec", sa.String(length=64), nullable=True),
        sa.Column("audio_codec", sa.String(length=64), nullable=True),
        sa.Column("orientation", sa.String(length=16), nullable=True),
        sa.Column("has_audio", sa.Boolean(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="asset_status", create_type=False),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_seen_scan_id", sa.Integer(), nullable=True),
        sa.Column("metadata_version", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_directory_id"],
            ["source_directory.id"],
            name="fk_asset_source_directory_id_source_directory",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_scan_id"],
            ["scan_run.id"],
            name="fk_asset_last_seen_scan_id_scan_run",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asset"),
        sa.UniqueConstraint(
            "source_directory_id",
            "normalized_relative_path",
            name="uq_asset_sd_norm_path",
        ),
    )
    op.create_index("ix_asset_filename", "asset", ["filename"], unique=False)
    op.create_index("ix_asset_sd_status", "asset", ["source_directory_id", "status"], unique=False)
    op.create_index(
        "ix_asset_sd_last_seen_scan",
        "asset",
        ["source_directory_id", "last_seen_scan_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_asset_sd_last_seen_scan", table_name="asset")
    op.drop_index("ix_asset_sd_status", table_name="asset")
    op.drop_index("ix_asset_filename", table_name="asset")
    op.drop_table("asset")

    op.drop_index("uq_active_scan_run", table_name="scan_run")
    op.drop_index("ix_scan_run_source_directory_id", table_name="scan_run")
    op.drop_table("scan_run")

    op.drop_table("source_directory")

    bind = op.get_bind()
    scan_run_status.drop(bind, checkfirst=True)
    scan_status.drop(bind, checkfirst=True)
    asset_status.drop(bind, checkfirst=True)
