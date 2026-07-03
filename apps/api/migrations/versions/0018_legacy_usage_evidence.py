"""PR-C Gate B：历史"已使用"路径证据导入与人工审核。

新增四表（不改 0017 及更早迁移、不删库重建）：
- legacy_usage_rule：可配置路径规则（受控 target/operator 白名单，无任意正则；
  **不预置任何公司真实规则** —— 真实规则一律经 UI/API 创建）
- legacy_usage_import_run：预演/导入运行（进度与错误事实来源；脱敏 rule_snapshot）
- legacy_usage_evidence：弱使用证据（绑定 Asset；evidence_key 唯一 ⇒ 幂等；
  与 final_video_usage 零关联，绝不影响 confirmed 使用次数）
- legacy_usage_evidence_event：append-only 审核审计

迁移不读取真实媒体、不修改 AssetLocation、不导入证据、不更新 usage_count、
不创建 FinalVideoUsage。downgrade 删四表，不触碰任何媒体文件与既有业务数据。

Revision ID: 0018_legacy_usage_evidence
Revises: 0017_asset_stable_identity
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_legacy_usage_evidence"
down_revision: str | None = "0017_asset_stable_identity"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ---- legacy_usage_rule ----
    op.create_table(
        "legacy_usage_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_directory_id", sa.Integer(), nullable=True),
        sa.Column("match_target", sa.String(length=32), nullable=False),
        sa.Column("match_operator", sa.String(length=16), nullable=False),
        sa.Column("pattern", sa.String(length=256), nullable=False),
        sa.Column("normalized_pattern", sa.String(length=256), nullable=False),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "include_present_locations", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "include_missing_locations", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "include_historical_locations",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legacy_usage_rule")),
        sa.ForeignKeyConstraint(
            ["source_directory_id"], ["source_directory.id"],
            name=op.f("fk_legacy_usage_rule_source_directory_id_source_directory"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("length(pattern) >= 1", name="rule_pattern_nonempty"),
    )
    op.create_index(
        op.f("ix_legacy_usage_rule_source_directory_id"),
        "legacy_usage_rule",
        ["source_directory_id"],
    )
    op.create_index("ix_legacy_rule_enabled", "legacy_usage_rule", ["enabled"])

    # ---- legacy_usage_import_run ----
    op.create_table(
        "legacy_usage_import_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_directory_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rule_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("location_scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("scanned_location_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_location_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_asset_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("existing_evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legacy_usage_import_run")),
        sa.ForeignKeyConstraint(
            ["source_directory_id"], ["source_directory.id"],
            name=op.f("fk_legacy_usage_import_run_source_directory_id_source_directory"),
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_legacy_import_run_status", "legacy_usage_import_run", ["status"])

    # ---- legacy_usage_evidence ----
    op.create_table(
        "legacy_usage_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("asset_location_id", sa.Integer(), nullable=True),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("import_run_id", sa.Integer(), nullable=True),
        sa.Column("evidence_key", sa.String(length=64), nullable=False),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("matched_target", sa.String(length=32), nullable=False),
        sa.Column("matched_component", sa.String(length=256), nullable=False),
        sa.Column("rule_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "review_status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("actor_label", sa.String(length=120), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legacy_usage_evidence")),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"],
            name=op.f("fk_legacy_usage_evidence_asset_id_asset"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_location_id"], ["asset_location.id"],
            name=op.f("fk_legacy_usage_evidence_asset_location_id_asset_location"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["legacy_usage_rule.id"],
            name=op.f("fk_legacy_usage_evidence_rule_id_legacy_usage_rule"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id"], ["legacy_usage_import_run.id"],
            name=op.f("fk_legacy_usage_evidence_import_run_id_legacy_usage_import_run"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("evidence_key", name="uq_legacy_evidence_key"),
        sa.CheckConstraint("observation_count >= 1", name="evidence_observation_min1"),
    )
    op.create_index(
        op.f("ix_legacy_usage_evidence_asset_id"), "legacy_usage_evidence", ["asset_id"]
    )
    op.create_index(
        op.f("ix_legacy_usage_evidence_rule_id"), "legacy_usage_evidence", ["rule_id"]
    )
    op.create_index("ix_legacy_evidence_review", "legacy_usage_evidence", ["review_status"])
    op.create_index(
        "ix_legacy_evidence_asset_review",
        "legacy_usage_evidence",
        ["asset_id", "review_status"],
    )

    # ---- legacy_usage_evidence_event（append-only）----
    op.create_table(
        "legacy_usage_evidence_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before_status", sa.String(length=16), nullable=True),
        sa.Column("after_status", sa.String(length=16), nullable=True),
        sa.Column("actor_label", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legacy_usage_evidence_event")),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["legacy_usage_evidence.id"],
            name=op.f("fk_legacy_usage_evidence_event_evidence_id_legacy_usage_evidence"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_legacy_usage_evidence_event_evidence_id"),
        "legacy_usage_evidence_event",
        ["evidence_id"],
    )
    op.create_index(
        "ix_legacy_evidence_event_created", "legacy_usage_evidence_event", ["created_at"]
    )


def downgrade() -> None:
    # 只删四张新表；不触碰媒体文件、AssetLocation 与任何既有业务数据
    op.drop_table("legacy_usage_evidence_event")
    op.drop_table("legacy_usage_evidence")
    op.drop_table("legacy_usage_import_run")
    op.drop_table("legacy_usage_rule")
