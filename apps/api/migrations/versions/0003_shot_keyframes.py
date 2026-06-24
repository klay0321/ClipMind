"""shot keyframe strip: shot.keyframe_paths

Revision ID: 0003_shot_keyframes
Revises: 0002_shot_processing
Create Date: 2026-06-24

为镜头详情「关键帧条」新增 shot.keyframe_paths（JSONB，存沿镜头均匀采样的多帧相对路径）。
仅新增可空列；不修改历史迁移、不动其他表。现有镜头该列为 NULL（重新分析后回填）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_shot_keyframes"
down_revision: str | None = "0002_shot_processing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shot",
        sa.Column("keyframe_paths", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shot", "keyframe_paths")
