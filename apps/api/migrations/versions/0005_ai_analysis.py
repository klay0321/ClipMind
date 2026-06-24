"""ai analysis: ai_analysis_run, ai_shot_analysis, ai_call_log

Revision ID: 0005_ai_analysis
Revises: 0004_asset_poster
Create Date: 2026-06-24

PR-03A AI 理解分析基础。新增三表与三个枚举类型。
不修改既有迁移；仍不创建 pgvector 扩展/向量列（PR-04 独立迁移）。
不在本迁移改动 Shot 的 AI 字段（描述/质量/风险/审核留待 PR-03B）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_ai_analysis"
down_revision: str | None = "0004_asset_poster"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ai_run_status = postgresql.ENUM(
    "queued",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
    name="ai_run_status",
)
ai_shot_analysis_status = postgresql.ENUM(
    "pending",
    "completed",
    "degraded",
    "failed",
    "skipped",
    name="ai_shot_analysis_status",
)
ai_call_status = postgresql.ENUM(
    "success",
    "retry",
    "failed",
    "timeout",
    "rate_limited",
    "degraded",
    name="ai_call_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    ai_run_status.create(bind, checkfirst=True)
    ai_shot_analysis_status.create(bind, checkfirst=True)
    ai_call_status.create(bind, checkfirst=True)

    op.create_table(
        "ai_analysis_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_uuid", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="ai_run_status", create_type=False),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("current_step", sa.String(length=32), nullable=True),
        sa.Column("total_shots", sa.Integer(), nullable=False),
        sa.Column("analyzed_shots", sa.Integer(), nullable=False),
        sa.Column("failed_shots", sa.Integer(), nullable=False),
        sa.Column("skipped_cached", sa.Integer(), nullable=False),
        sa.Column("degraded", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "capabilities_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            name=op.f("fk_ai_analysis_run_asset_id_asset"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_analysis_run")),
        sa.UniqueConstraint("run_uuid", name=op.f("uq_ai_analysis_run_run_uuid")),
    )
    op.create_index(
        op.f("ix_ai_analysis_run_asset_id"), "ai_analysis_run", ["asset_id"], unique=False
    )
    # 每素材至多一个活动 AI 运行（queued/running）
    op.create_index(
        "uq_active_ai_run",
        "ai_analysis_run",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "ai_call_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("shot_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("method", sa.String(length=64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("input_images", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("est_cost", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="ai_call_status", create_type=False),
            nullable=False,
        ),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset.id"],
            name=op.f("fk_ai_call_log_asset_id_asset"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ai_analysis_run.id"],
            name=op.f("fk_ai_call_log_run_id_ai_analysis_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shot_id"],
            ["shot.id"],
            name=op.f("fk_ai_call_log_shot_id_shot"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_call_log")),
    )
    op.create_index("ix_ai_call_log_asset_id", "ai_call_log", ["asset_id"], unique=False)
    op.create_index("ix_ai_call_log_created_at", "ai_call_log", ["created_at"], unique=False)

    op.create_table(
        "ai_shot_analysis",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shot_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
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
            ["asset_id"],
            ["asset.id"],
            name=op.f("fk_ai_shot_analysis_asset_id_asset"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ai_analysis_run.id"],
            name=op.f("fk_ai_shot_analysis_run_id_ai_analysis_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shot_id"],
            ["shot.id"],
            name=op.f("fk_ai_shot_analysis_shot_id_shot"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_shot_analysis")),
        sa.UniqueConstraint("shot_id", name=op.f("uq_ai_shot_analysis_shot_id")),
    )
    op.create_index(
        op.f("ix_ai_shot_analysis_asset_id"), "ai_shot_analysis", ["asset_id"], unique=False
    )
    op.create_index(
        op.f("ix_ai_shot_analysis_input_fingerprint"),
        "ai_shot_analysis",
        ["input_fingerprint"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_ai_shot_analysis_input_fingerprint"), table_name="ai_shot_analysis"
    )
    op.drop_index(op.f("ix_ai_shot_analysis_asset_id"), table_name="ai_shot_analysis")
    op.drop_table("ai_shot_analysis")

    op.drop_index("ix_ai_call_log_created_at", table_name="ai_call_log")
    op.drop_index("ix_ai_call_log_asset_id", table_name="ai_call_log")
    op.drop_table("ai_call_log")

    op.drop_index(
        "uq_active_ai_run",
        table_name="ai_analysis_run",
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.drop_index(op.f("ix_ai_analysis_run_asset_id"), table_name="ai_analysis_run")
    op.drop_table("ai_analysis_run")

    bind = op.get_bind()
    ai_call_status.drop(bind, checkfirst=True)
    ai_shot_analysis_status.drop(bind, checkfirst=True)
    ai_run_status.drop(bind, checkfirst=True)
