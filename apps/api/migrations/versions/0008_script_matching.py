"""script matching: script_project / script_segment / script_shot_candidate

Revision ID: 0008_script_matching
Revises: 0007_semantic_search
Create Date: 2026-06-27

PR-05 Gate A 脚本拆段数据基础：
- 新建 script_status / script_parse_status 枚举；
- script_project（脚本原文 + 归一 + 哈希 + 拆段状态）；
- script_segment（顺序/文案/画面需求/结构化要求/产品/目标时长 + current_generation +
  locked_shot_id + lock_version，为 Gate B 重匹配与人工锁定预留）；
- script_shot_candidate（每段每代次候选镜头 + 评分 + 规则派生理由；Gate A 只建表不写入）。

不修改既有迁移、不改既有表/列。downgrade 删除本迁移创建的表与枚举。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_script_matching"
down_revision: str | None = "0007_semantic_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

script_status = postgresql.ENUM(
    "draft", "parsing", "parsed", "matched", "failed", name="script_status",
)
script_parse_status = postgresql.ENUM(
    "pending", "ok", "degraded", "failed", name="script_parse_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    script_status.create(bind, checkfirst=True)
    script_parse_status.create(bind, checkfirst=True)

    op.create_table(
        "script_project",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("raw_script", sa.Text(), nullable=False),
        sa.Column("normalized_script", sa.Text(), nullable=True),
        sa.Column("script_hash", sa.String(length=64), nullable=True),
        sa.Column("source_format", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="script_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "parse_status",
            postgresql.ENUM(name="script_parse_status", create_type=False),
            nullable=False,
        ),
        sa.Column("parser_provider", sa.String(length=64), nullable=True),
        sa.Column("parser_model", sa.String(length=128), nullable=True),
        sa.Column("parser_warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_script_project")),
        sa.UniqueConstraint("script_hash", name="uq_script_project_script_hash"),
    )

    op.create_table(
        "script_segment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("script_project_id", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("segment_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("visual_requirement", sa.Text(), nullable=True),
        sa.Column("target_duration_min", sa.Float(), nullable=True),
        sa.Column("target_duration_max", sa.Float(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column(
            "structured_requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("negative_terms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("excluded_risks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("allow_similar_scene", sa.Boolean(), nullable=False),
        sa.Column("allow_similar_action", sa.Boolean(), nullable=False),
        sa.Column("current_generation", sa.Integer(), nullable=False),
        sa.Column("locked_shot_id", sa.Integer(), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("parser_warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("candidates_stale", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["script_project_id"], ["script_project.id"],
            name=op.f("fk_script_segment_script_project_id_script_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["product.id"],
            name=op.f("fk_script_segment_product_id_product"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["locked_shot_id"], ["shot.id"],
            name=op.f("fk_script_segment_locked_shot_id_shot"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_script_segment")),
        sa.UniqueConstraint(
            "script_project_id", "order_index", name="uq_script_segment_project_order"
        ),
        sa.CheckConstraint("order_index >= 0", name=op.f("ck_script_segment_order_index_nonneg")),
        sa.CheckConstraint(
            "current_generation >= 1", name=op.f("ck_script_segment_current_generation_min1")
        ),
    )
    op.create_index(
        op.f("ix_script_segment_script_project_id"),
        "script_segment", ["script_project_id"], unique=False,
    )

    op.create_table(
        "script_shot_candidate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("script_segment_id", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("shot_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("semantic_score", sa.Float(), nullable=True),
        sa.Column("lexical_score", sa.Float(), nullable=True),
        sa.Column("tag_score", sa.Float(), nullable=True),
        sa.Column("product_score", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("review_bonus", sa.Float(), nullable=True),
        sa.Column("risk_penalty", sa.Float(), nullable=True),
        sa.Column("matched_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("unmatched_requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("risk_warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["script_segment_id"], ["script_segment.id"],
            name=op.f("fk_script_shot_candidate_script_segment_id_script_segment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shot_id"], ["shot.id"],
            name=op.f("fk_script_shot_candidate_shot_id_shot"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_script_shot_candidate")),
        sa.UniqueConstraint(
            "script_segment_id", "generation", "shot_id",
            name="uq_script_candidate_seg_gen_shot",
        ),
        sa.CheckConstraint(
            "generation >= 1", name=op.f("ck_script_shot_candidate_candidate_generation_min1")
        ),
        sa.CheckConstraint(
            "rank >= 0", name=op.f("ck_script_shot_candidate_candidate_rank_nonneg")
        ),
    )
    op.create_index(
        op.f("ix_script_shot_candidate_script_segment_id"),
        "script_shot_candidate", ["script_segment_id"], unique=False,
    )
    op.create_index(
        "ix_script_candidate_seg_gen",
        "script_shot_candidate", ["script_segment_id", "generation"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_script_candidate_seg_gen", table_name="script_shot_candidate")
    op.drop_index(
        op.f("ix_script_shot_candidate_script_segment_id"), table_name="script_shot_candidate"
    )
    op.drop_table("script_shot_candidate")

    op.drop_index(op.f("ix_script_segment_script_project_id"), table_name="script_segment")
    op.drop_table("script_segment")

    op.drop_table("script_project")

    bind = op.get_bind()
    script_parse_status.drop(bind, checkfirst=True)
    script_status.drop(bind, checkfirst=True)
