"""OPS：产品素材操作审计表（append-only；批量撤销依据）。

新增单表 product_media_operation（不改 0019 及更早迁移、不删库重建）：
记录单个/批量绑定、解除与撤销事件；`created_link_ids` 只存 link id 列表
（不复制素材事实行）。迁移不读取媒体、不创建任何事件行。
downgrade 删本表，不触碰 product_media_link 与任何业务数据。

Revision ID: 0020_product_media_operations
Revises: 0019_product_media_association
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_product_media_operations"
down_revision: str | None = "0019_product_media_association"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "product_media_operation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column(
            "family_id",
            sa.Integer(),
            sa.ForeignKey("product_family.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=True),
        sa.Column("actor_label", sa.String(length=64), nullable=True),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_link_ids", postgresql.JSONB(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone_by_operation_id", sa.Integer(), nullable=True),
        sa.Column("undone_detail", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pmo_created_at", "product_media_operation", ["created_at"])
    op.create_index("ix_pmo_kind", "product_media_operation", ["kind"])


def downgrade() -> None:
    op.drop_table("product_media_operation")
