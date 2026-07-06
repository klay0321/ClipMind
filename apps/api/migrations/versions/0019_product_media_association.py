"""PM：产品素材正式关系 + 图片素材支持。

新增（不改 0018 及更早迁移、不删库重建）：
- product_media_link：媒体（Asset）/镜头（Shot）→ 产品（Family/可选 Variant）
  的**人工正式关系**（primary 部分唯一 + 同目标同 Family 唯一；6 种来源白名单
  在 service 层校验——候选绝不自动写入本表）
- asset.media_kind：'video'|'image'（现有行回填 'video'；图片素材走同一
  Asset 管线但无拆镜头/代理派生）

迁移不读取真实媒体、不创建任何关系数据、不修改 asset_product /
shot_review_state / 搜索文档。downgrade 删新表与新列，不触碰媒体文件与
既有业务数据。

Revision ID: 0019_product_media_association
Revises: 0018_legacy_usage_evidence
Create Date: 2026-07-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0019_product_media_association"
down_revision: str | None = "0018_legacy_usage_evidence"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "asset",
        sa.Column(
            "media_kind", sa.String(length=8), nullable=False, server_default="video"
        ),
    )

    op.create_table(
        "product_media_link",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("asset.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "shot_id",
            sa.Integer(),
            sa.ForeignKey("shot.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "family_id",
            sa.Integer(),
            sa.ForeignKey("product_family.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.Integer(),
            sa.ForeignKey("product_variant.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="related"),
        sa.Column("origin", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("actor_label", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN asset_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN shot_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="pml_exactly_one_target",
        ),
    )
    op.create_index(
        "uq_pml_asset_family",
        "product_media_link",
        ["asset_id", "family_id"],
        unique=True,
        postgresql_where=sa.text("asset_id IS NOT NULL"),
    )
    op.create_index(
        "uq_pml_shot_family",
        "product_media_link",
        ["shot_id", "family_id"],
        unique=True,
        postgresql_where=sa.text("shot_id IS NOT NULL"),
    )
    op.create_index(
        "uq_pml_asset_primary",
        "product_media_link",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("asset_id IS NOT NULL AND role = 'primary'"),
    )
    op.create_index(
        "uq_pml_shot_primary",
        "product_media_link",
        ["shot_id"],
        unique=True,
        postgresql_where=sa.text("shot_id IS NOT NULL AND role = 'primary'"),
    )
    op.create_index("ix_pml_family_id", "product_media_link", ["family_id"])
    op.create_index("ix_pml_family_role", "product_media_link", ["family_id", "role"])


def downgrade() -> None:
    op.drop_table("product_media_link")
    op.drop_column("asset", "media_kind")
