"""PR-06B export center: export/script_export 项目关联 + 多格式列宽 + download_log

Revision ID: 0011_export_center
Revises: 0010_projects_collections
Create Date: 2026-06-28

PR-06B（不改既有迁移、不删既有表/列、不回填历史数据、不合并 export 与 script_export）：
- export 增可空列 project_id（SET NULL；历史导出保持 NULL，不回填）。
- script_export 增可空列 project_id（SET NULL）；export_format 列宽 8→16（容纳 'printable'）。
- 新建 download_log（导出下载记录，多态 kind+export_id，无鉴权不记 user）。

project_id 用 SET NULL：项目删除（PR-07）时清空引用而非删导出记录，导出可追溯。
downgrade 回退新增列/列宽/表，**绝不删除导出文件或任何业务数据**，回到 0010。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_export_center"
down_revision: str | None = "0010_projects_collections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- export.project_id（可空 SET NULL；历史导出保持 NULL，不回填）----
    op.add_column("export", sa.Column("project_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_export_project_id_project"),
        "export", "project", ["project_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(op.f("ix_export_project_id"), "export", ["project_id"])

    # ---- script_export.project_id + export_format 列宽 8→16 ----
    op.add_column("script_export", sa.Column("project_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_script_export_project_id_project"),
        "script_export", "project", ["project_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_script_export_project_id"), "script_export", ["project_id"]
    )
    op.alter_column(
        "script_export", "export_format",
        existing_type=sa.String(length=8),
        type_=sa.String(length=16),
        existing_nullable=False,
    )

    # ---- download_log（导出下载记录）----
    op.create_table(
        "download_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("export_kind", sa.String(length=16), nullable=False),
        sa.Column("export_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_download_log")),
    )
    op.create_index(
        "ix_download_log_kind_export", "download_log", ["export_kind", "export_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_download_log_kind_export", table_name="download_log")
    op.drop_table("download_log")

    op.alter_column(
        "script_export", "export_format",
        existing_type=sa.String(length=16),
        type_=sa.String(length=8),
        existing_nullable=False,
    )
    op.drop_index(op.f("ix_script_export_project_id"), table_name="script_export")
    op.drop_constraint(
        op.f("fk_script_export_project_id_project"), "script_export", type_="foreignkey"
    )
    op.drop_column("script_export", "project_id")

    op.drop_index(op.f("ix_export_project_id"), table_name="export")
    op.drop_constraint(
        op.f("fk_export_project_id_project"), "export", type_="foreignkey"
    )
    op.drop_column("export", "project_id")
