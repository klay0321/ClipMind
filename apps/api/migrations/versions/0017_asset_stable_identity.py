"""PR-C Gate A：稳定素材身份、路径历史与可追溯 Shot 代次。

变更（不改 0016 及更早迁移、不删库重建）：
- asset：新增分级指纹字段（复用既有 full_hash 列，补 full_hash_algorithm /
  quick_fingerprint(+version) / fingerprint_state / fingerprint_error /
  fingerprinted_at / content_size 与 full_hash、quick_fingerprint 索引）；
  取消 (source_directory_id, normalized_relative_path) 唯一约束——路径不再是
  Asset 身份，活动路径唯一性由 asset_location 部分唯一索引接管；原列保留为兼容投影。
- asset_location：新表（一个 Asset 的一个物理位置；移动/复制不改变 Asset 身份；
  位置历史不物理删除）。为每个现有 Asset 回填一条兼容 primary 位置
  （纯 SQL 派生自现有行：不读媒体文件、不计算/伪造 full_hash、不合并 Asset）。
- fingerprint_job：新表（quick/full 指纹任务进度跟踪）。
- shot：新增 retired_at（NULL=当前代次；重新分析不再物理删除旧 Shot）+ 部分索引。
- scan_run：新增 reconciliation JSONB（移动/复制识别结果，脱敏明细）。

downgrade：删两张新表与新增列/索引，恢复 asset 路径唯一约束；
不触碰任何媒体文件、不删除 Shot、不删除既有业务数据。

Revision ID: 0017_asset_stable_identity
Revises: 0016_final_video_usage_lineage
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_asset_stable_identity"
down_revision: str | None = "0016_final_video_usage_lineage"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ---- asset：分级指纹字段（full_hash 列已存在于 0001，此处只补元数据列与索引）----
    op.add_column("asset", sa.Column("full_hash_algorithm", sa.String(length=16), nullable=True))
    op.add_column("asset", sa.Column("quick_fingerprint", sa.String(length=64), nullable=True))
    op.add_column(
        "asset", sa.Column("quick_fingerprint_version", sa.String(length=8), nullable=True)
    )
    op.add_column(
        "asset",
        sa.Column(
            "fingerprint_state",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column("asset", sa.Column("fingerprint_error", sa.Text(), nullable=True))
    op.add_column(
        "asset", sa.Column("fingerprinted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("asset", sa.Column("content_size", sa.BigInteger(), nullable=True))
    op.create_index(op.f("ix_asset_full_hash"), "asset", ["full_hash"])
    op.create_index(op.f("ix_asset_quick_fingerprint"), "asset", ["quick_fingerprint"])

    # 路径不再是 Asset 唯一身份：唯一约束 → 普通复合索引（投影查询仍需要）
    op.drop_constraint("uq_asset_sd_norm_path", "asset", type_="unique")
    op.create_index(
        "ix_asset_sd_norm_path", "asset", ["source_directory_id", "normalized_relative_path"]
    )

    # ---- asset_location ----
    op.create_table(
        "asset_location",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("source_root_id", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.String(length=2048), nullable=False),
        sa.Column("normalized_path", sa.String(length=2048), nullable=False),
        sa.Column(
            "location_status", sa.String(length=16), nullable=False, server_default="present"
        ),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("mtime_ns", sa.BigInteger(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("missing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_location")),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"],
            name=op.f("fk_asset_location_asset_id_asset"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_root_id"], ["source_directory.id"],
            name=op.f("fk_asset_location_source_root_id_source_directory"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_asset_location_asset_id"), "asset_location", ["asset_id"])
    op.create_index(
        op.f("ix_asset_location_source_root_id"), "asset_location", ["source_root_id"]
    )
    op.create_index("ix_asset_location_status", "asset_location", ["location_status"])
    op.create_index(
        "uq_asset_location_active_path",
        "asset_location",
        ["source_root_id", "normalized_path"],
        unique=True,
        postgresql_where=sa.text("location_status != 'historical'"),
    )
    op.create_index(
        "uq_asset_location_primary",
        "asset_location",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    # 兼容回填：每个现有 Asset 一条 primary 位置（纯 SQL 派生；不读媒体、不算哈希、不合并）
    op.execute(
        """
        INSERT INTO asset_location (
            asset_id, source_root_id, relative_path, normalized_path,
            location_status, is_primary, file_size, mtime_ns,
            first_seen_at, last_seen_at, missing_at, verified_at,
            created_at, updated_at
        )
        SELECT
            a.id, a.source_directory_id, a.relative_path, a.normalized_relative_path,
            CASE WHEN a.status = 'source_missing' THEN 'missing' ELSE 'present' END,
            TRUE, a.file_size, NULL,
            a.first_seen_at, a.last_seen_at,
            CASE WHEN a.status = 'source_missing' THEN a.last_seen_at ELSE NULL END,
            NULL, NOW(), NOW()
        FROM asset a
        """
    )

    # ---- fingerprint_job ----
    op.create_table(
        "fingerprint_job",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("asset_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fingerprint_job")),
    )
    op.create_index("ix_fingerprint_job_status", "fingerprint_job", ["status"])

    # ---- shot：代次保留 ----
    op.add_column("shot", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_shot_asset_current",
        "shot",
        ["asset_id"],
        postgresql_where=sa.text("retired_at IS NULL"),
    )

    # ---- scan_run：识别结果 ----
    op.add_column(
        "scan_run",
        sa.Column("reconciliation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    # 只回退结构：不触碰媒体文件、不删除 Shot、不删除业务数据
    op.drop_column("scan_run", "reconciliation")
    op.drop_index("ix_shot_asset_current", table_name="shot")
    op.drop_column("shot", "retired_at")
    op.drop_table("fingerprint_job")
    op.drop_table("asset_location")
    op.drop_index("ix_asset_sd_norm_path", table_name="asset")
    op.create_unique_constraint(
        "uq_asset_sd_norm_path", "asset", ["source_directory_id", "normalized_relative_path"]
    )
    op.drop_index(op.f("ix_asset_quick_fingerprint"), table_name="asset")
    op.drop_index(op.f("ix_asset_full_hash"), table_name="asset")
    op.drop_column("asset", "content_size")
    op.drop_column("asset", "fingerprinted_at")
    op.drop_column("asset", "fingerprint_error")
    op.drop_column("asset", "fingerprint_state")
    op.drop_column("asset", "quick_fingerprint_version")
    op.drop_column("asset", "quick_fingerprint")
    op.drop_column("asset", "full_hash_algorithm")
    # full_hash 列本身属于 0001，保留
