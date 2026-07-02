"""PR-B Gate A：最终成片与 Shot 使用血缘核心。

新增四表 + 两个原生枚举（不改 0015 及更早迁移、不删库重建）：
- final_video：最终成片业务实体（引用已有 Asset，不复制视频文件；
  同一 Asset 至多一个未归档成片：部分唯一索引）
- final_video_usage：成片↔Source Shot 引用关系（UNIQUE(final_video_id, source_shot_id)；
  confirmed 行数 = 按成片去重的正式使用次数；无 usage_count 缓存列）
- final_video_usage_occurrence：Usage 内出现时间段（毫秒；不影响使用次数）
- final_video_usage_event：append-only 审计（与业务变更同事务）

外键策略：asset/shot 侧 RESTRICT（血缘不被静默删除），project/script 侧 SET NULL
（项目/脚本删除绝不删除成片与已确认血缘）。
downgrade 删四表与两枚举，不触碰任何原始媒体或成片媒体文件。

Revision ID: 0016_final_video_usage_lineage
Revises: 0015_product_onboarding_gov
Create Date: 2026-07-02

注：revision id ≤32 字符（alembic_version.version_num 为 VARCHAR(32)）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_final_video_usage_lineage"
down_revision: str | None = "0015_product_onboarding_gov"
branch_labels: str | None = None
depends_on: str | None = None

final_video_status = postgresql.ENUM(
    "draft", "ready", "completed", "archived",
    name="final_video_status",
)
final_video_usage_status = postgresql.ENUM(
    "proposed", "suspected", "confirmed", "rejected", "revoked",
    name="final_video_usage_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    final_video_status.create(bind, checkfirst=True)
    final_video_usage_status.create(bind, checkfirst=True)

    # ---- final_video ----
    op.create_table(
        "final_video",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("script_project_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("version_label", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="final_video_status", create_type=False),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_final_video")),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"],
            name=op.f("fk_final_video_asset_id_asset"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"],
            name=op.f("fk_final_video_project_id_project"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["script_project_id"], ["script_project.id"],
            name=op.f("fk_final_video_script_project_id_script_project"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(op.f("ix_final_video_asset_id"), "final_video", ["asset_id"])
    op.create_index(op.f("ix_final_video_project_id"), "final_video", ["project_id"])
    op.create_index(
        op.f("ix_final_video_script_project_id"), "final_video", ["script_project_id"]
    )
    op.create_index("ix_final_video_status", "final_video", ["status"])
    # 同一 Asset 至多一个未归档 FinalVideo
    op.create_index(
        "uq_final_video_active_asset",
        "final_video",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("status != 'archived'"),
    )

    # ---- final_video_usage ----
    op.create_table(
        "final_video_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("final_video_id", sa.Integer(), nullable=False),
        sa.Column("source_shot_id", sa.Integer(), nullable=False),
        sa.Column("source_asset_id", sa.Integer(), nullable=False),
        sa.Column("source_shot_generation", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="final_video_usage_status", create_type=False),
            nullable=False,
        ),
        sa.Column("evidence_method", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_label", sa.String(length=120), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_final_video_usage")),
        sa.ForeignKeyConstraint(
            ["final_video_id"], ["final_video.id"],
            name=op.f("fk_final_video_usage_final_video_id_final_video"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_shot_id"], ["shot.id"],
            name=op.f("fk_final_video_usage_source_shot_id_shot"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"], ["asset.id"],
            name=op.f("fk_final_video_usage_source_asset_id_asset"), ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "final_video_id", "source_shot_id",
            name="uq_final_video_usage_video_shot",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="usage_confidence_0_1",
        ),
    )
    op.create_index(
        op.f("ix_final_video_usage_final_video_id"), "final_video_usage", ["final_video_id"]
    )
    op.create_index(
        op.f("ix_final_video_usage_source_shot_id"), "final_video_usage", ["source_shot_id"]
    )
    op.create_index(
        op.f("ix_final_video_usage_source_asset_id"),
        "final_video_usage",
        ["source_asset_id"],
    )
    op.create_index("ix_final_video_usage_status", "final_video_usage", ["status"])
    op.create_index(
        "ix_fv_usage_shot_status", "final_video_usage", ["source_shot_id", "status"]
    )
    op.create_index(
        "ix_fv_usage_asset_status", "final_video_usage", ["source_asset_id", "status"]
    )

    # ---- final_video_usage_occurrence ----
    op.create_table(
        "final_video_usage_occurrence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usage_id", sa.Integer(), nullable=False),
        sa.Column("occurrence_index", sa.Integer(), nullable=False),
        sa.Column("source_start_ms", sa.Integer(), nullable=False),
        sa.Column("source_end_ms", sa.Integer(), nullable=False),
        sa.Column("final_start_ms", sa.Integer(), nullable=False),
        sa.Column("final_end_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_final_video_usage_occurrence")),
        sa.ForeignKeyConstraint(
            ["usage_id"], ["final_video_usage.id"],
            name=op.f("fk_final_video_usage_occurrence_usage_id_final_video_usage"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "usage_id", "occurrence_index", name="uq_fv_occurrence_usage_index"
        ),
        sa.CheckConstraint("occurrence_index >= 0", name="occurrence_index_nonneg"),
        sa.CheckConstraint("source_start_ms >= 0", name="occ_source_start_nonneg"),
        sa.CheckConstraint("final_start_ms >= 0", name="occ_final_start_nonneg"),
        sa.CheckConstraint(
            "source_end_ms > source_start_ms", name="occ_source_end_gt_start"
        ),
        sa.CheckConstraint("final_end_ms > final_start_ms", name="occ_final_end_gt_start"),
    )
    op.create_index(
        op.f("ix_final_video_usage_occurrence_usage_id"),
        "final_video_usage_occurrence",
        ["usage_id"],
    )

    # ---- final_video_usage_event（append-only）----
    op.create_table(
        "final_video_usage_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usage_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before_status", sa.String(length=32), nullable=True),
        sa.Column("after_status", sa.String(length=32), nullable=True),
        sa.Column("actor_label", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_final_video_usage_event")),
        sa.ForeignKeyConstraint(
            ["usage_id"], ["final_video_usage.id"],
            name=op.f("fk_final_video_usage_event_usage_id_final_video_usage"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_final_video_usage_event_usage_id"), "final_video_usage_event", ["usage_id"]
    )
    op.create_index(
        "ix_fv_usage_event_created_at", "final_video_usage_event", ["created_at"]
    )


def downgrade() -> None:
    # 只删表与枚举；不触碰任何原始媒体、成片媒体文件或其他业务表
    op.drop_table("final_video_usage_event")
    op.drop_table("final_video_usage_occurrence")
    op.drop_table("final_video_usage")
    op.drop_table("final_video")
    bind = op.get_bind()
    final_video_usage_status.drop(bind, checkfirst=True)
    final_video_status.drop(bind, checkfirst=True)
