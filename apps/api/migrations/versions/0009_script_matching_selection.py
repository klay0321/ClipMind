"""script matching gate B: segment selection/match summary + script_export

Revision ID: 0009_script_matching_selection
Revises: 0008_script_matching
Create Date: 2026-06-27

PR-05 Gate B 持久化补充（不改既有迁移、不删既有表/列）：
- script_segment 增列：
  - selected_shot_id（人工选择的镜头，区别于 locked_shot_id；SET NULL）；
  - match_status（pending/matched/gap/degraded，区分"从未匹配"与"匹配后真实无结果"）；
  - match_summary（JSONB：best_score/candidate_count/gap_reasons/reshoot_recommendation/
    requires_human_confirmation/degraded/generation/match_token 等，规则派生）；
  - matched_at（上次匹配完成时刻，NULL=从未匹配）。
- 新建 script_export（脚本剪辑清单 CSV 导出记录，复用 export_status 枚举与 export 队列；
  与片段视频导出 export 表分离，语义不同）。

downgrade 删除本迁移新增的列与表，回到 0008。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_script_matching_selection"
down_revision: str | None = "0008_script_matching"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- script_segment 增列 ----
    op.add_column(
        "script_segment",
        sa.Column("selected_shot_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_script_segment_selected_shot_id_shot"),
        "script_segment",
        "shot",
        ["selected_shot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # match_status NOT NULL：用 server_default 回填既有段落，随后移除默认（与模型一致由应用层赋值）
    op.add_column(
        "script_segment",
        sa.Column(
            "match_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
    )
    op.alter_column("script_segment", "match_status", server_default=None)
    op.add_column(
        "script_segment",
        sa.Column(
            "match_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "script_segment",
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ---- script_export（复用既有 export_status 枚举）----
    op.create_table(
        "script_export",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("export_uuid", sa.String(length=36), nullable=False),
        sa.Column("script_project_id", sa.Integer(), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="export_status", create_type=False),
            nullable=False,
        ),
        sa.Column("export_format", sa.String(length=8), nullable=False),
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
            ["script_project_id"],
            ["script_project.id"],
            name=op.f("fk_script_export_script_project_id_script_project"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_script_export")),
        sa.UniqueConstraint("export_uuid", name="uq_script_export_export_uuid"),
    )
    op.create_index(
        op.f("ix_script_export_script_project_id"),
        "script_export",
        ["script_project_id"],
        unique=False,
    )
    op.create_index("ix_script_export_status", "script_export", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_script_export_status", table_name="script_export")
    op.drop_index(
        op.f("ix_script_export_script_project_id"), table_name="script_export"
    )
    op.drop_table("script_export")

    op.drop_column("script_segment", "matched_at")
    op.drop_column("script_segment", "match_summary")
    op.drop_column("script_segment", "match_status")
    op.drop_constraint(
        op.f("fk_script_segment_selected_shot_id_shot"),
        "script_segment",
        type_="foreignkey",
    )
    op.drop_column("script_segment", "selected_shot_id")
