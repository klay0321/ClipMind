"""shot processing: media_processing_run, shot, export

Revision ID: 0002_shot_processing
Revises: 0001_initial
Create Date: 2026-06-23

PR-02 拆镜头 + 派生文件。新增三表与三个枚举类型。
不修改 0001；仍不创建 pgvector 扩展/向量列（PR-04 独立迁移）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_shot_processing"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


shot_status = postgresql.ENUM(
    "pending",
    "processing",
    "ready",
    "failed",
    name="shot_status",
)
media_run_status = postgresql.ENUM(
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    name="media_run_status",
)
export_status = postgresql.ENUM(
    "queued",
    "running",
    "completed",
    "failed",
    name="export_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    shot_status.create(bind, checkfirst=True)
    media_run_status.create(bind, checkfirst=True)
    export_status.create(bind, checkfirst=True)

    op.create_table(
        "media_processing_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_uuid", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="media_run_status", create_type=False),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("current_step", sa.String(length=32), nullable=True),
        sa.Column("total_shots", sa.Integer(), nullable=False),
        sa.Column("completed_shots", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset.id"],
            name="fk_media_processing_run_asset_id_asset",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_media_processing_run"),
        sa.UniqueConstraint("run_uuid", name="uq_media_processing_run_run_uuid"),
    )
    op.create_index(
        "ix_media_processing_run_asset_id",
        "media_processing_run",
        ["asset_id"],
        unique=False,
    )
    # 每素材至多一个活动镜头分析（queued/running）
    op.create_index(
        "uq_active_media_run",
        "media_processing_run",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "shot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("processing_run_id", sa.Integer(), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("duration", sa.Float(), nullable=False),
        sa.Column("detector_type", sa.String(length=32), nullable=False),
        sa.Column("detector_confidence", sa.Float(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="shot_status", create_type=False),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("keyframe_path", sa.String(length=2048), nullable=True),
        sa.Column("thumbnail_path", sa.String(length=2048), nullable=True),
        sa.Column("proxy_path", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("start_time >= 0", name="ck_shot_start_nonneg"),
        sa.CheckConstraint("end_time > start_time", name="ck_shot_end_gt_start"),
        sa.CheckConstraint("duration >= 0", name="ck_shot_duration_nonneg"),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset.id"],
            name="fk_shot_asset_id_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["media_processing_run.id"],
            name="fk_shot_processing_run_id_media_processing_run",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shot"),
        sa.UniqueConstraint(
            "asset_id", "generation", "sequence_no", name="uq_shot_asset_gen_seq"
        ),
    )
    op.create_index("ix_shot_asset_id", "shot", ["asset_id"], unique=False)
    op.create_index("ix_shot_asset_status", "shot", ["asset_id", "status"], unique=False)

    op.create_table(
        "export",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("export_uuid", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("shot_id", sa.Integer(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="export_status", create_type=False),
            nullable=False,
        ),
        sa.Column("mode", sa.String(length=16), nullable=False),
        # 来源快照（不为空，永久可追溯）
        sa.Column("source_asset_id", sa.Integer(), nullable=False),
        sa.Column("source_shot_id", sa.Integer(), nullable=False),
        sa.Column("source_generation", sa.Integer(), nullable=False),
        sa.Column("source_sequence_no", sa.Integer(), nullable=False),
        sa.Column("source_start_time", sa.Float(), nullable=False),
        sa.Column("source_end_time", sa.Float(), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("source_relative_path", sa.String(length=2048), nullable=False),
        sa.Column("output_path", sa.String(length=2048), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset.id"],
            name="fk_export_asset_id_asset",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shot_id"],
            ["shot.id"],
            name="fk_export_shot_id_shot",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_export"),
        sa.UniqueConstraint("export_uuid", name="uq_export_export_uuid"),
    )
    op.create_index("ix_export_asset_id", "export", ["asset_id"], unique=False)
    op.create_index("ix_export_shot_id", "export", ["shot_id"], unique=False)
    op.create_index("ix_export_status", "export", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_export_status", table_name="export")
    op.drop_index("ix_export_shot_id", table_name="export")
    op.drop_index("ix_export_asset_id", table_name="export")
    op.drop_table("export")

    op.drop_index("ix_shot_asset_status", table_name="shot")
    op.drop_index("ix_shot_asset_id", table_name="shot")
    op.drop_table("shot")

    op.drop_index("uq_active_media_run", table_name="media_processing_run")
    op.drop_index("ix_media_processing_run_asset_id", table_name="media_processing_run")
    op.drop_table("media_processing_run")

    bind = op.get_bind()
    export_status.drop(bind, checkfirst=True)
    media_run_status.drop(bind, checkfirst=True)
    shot_status.drop(bind, checkfirst=True)
