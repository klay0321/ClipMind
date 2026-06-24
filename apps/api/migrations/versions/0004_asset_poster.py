"""asset poster: asset.poster_path

Revision ID: 0004_asset_poster
Revises: 0003_shot_keyframes
Create Date: 2026-06-24

为「素材海报」（未分析素材也能有真实封面）新增 asset.poster_path。
该列存 FFmpeg 抽一帧的派生封面相对路径（相对 data_dir）。
仅新增可空列；不改历史迁移、不动其他表。现有素材为 NULL（重扫/重生成回填）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_asset_poster"
down_revision: str | None = "0003_shot_keyframes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("asset", sa.Column("poster_path", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column("asset", "poster_path")
