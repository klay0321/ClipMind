"""IMG-REVIEW：图片素材 AI 理解的人工审核状态。

asset_image_review_state：每 asset 一条（图片无代次）；对齐镜头审核范式
（乐观锁 / 来源分析行 + 指纹做 stale / confirmed_result 同 schema）。
审核事件复用既有多态 review_event（object_type="asset_image"），零新事件表。

Revision ID: 0023_image_review
Revises: 0022_visual_auto
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB

revision: str = "0023_image_review"
down_revision: str | None = "0022_visual_auto"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_image_review_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("asset.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "source_image_analysis_id",
            sa.Integer(),
            sa.ForeignKey("asset_image_analysis.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_input_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("result_schema_version", sa.Integer(), nullable=True),
        sa.Column(
            "review_status",
            ENUM(name="review_status", create_type=False),  # 复用 0005 的既有枚举
            nullable=False,
            server_default="unreviewed",
        ),
        sa.Column("confirmed_result", JSONB(), nullable=True),
        sa.Column("reviewer_label", sa.String(length=255), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stale_reason", sa.String(length=64), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_airs_review_status", "asset_image_review_state", ["review_status"])
    op.create_index("ix_airs_stale_at", "asset_image_review_state", ["stale_at"])
    op.create_index(
        "ix_asset_image_review_state_asset_id", "asset_image_review_state", ["asset_id"]
    )


def downgrade() -> None:
    op.drop_table("asset_image_review_state")
