"""PR-06A projects & collections: project/collection 组织层 + script_project.project_id

Revision ID: 0010_projects_collections
Revises: 0009_script_matching_selection
Create Date: 2026-06-28

PR-06A Gate A（不改既有迁移、不删既有表/列、不回填历史数据）：
- 新建 project（业务工作空间，status=active/archived，乐观锁）。
- 新建 project_asset / project_shot / project_product（项目↔素材/镜头/产品显式关联，手工排序）。
- 新建 collection（必须归属 project）/ collection_shot（集合↔镜头成员，手工排序）。
- script_project 增可空列 project_id（SET NULL；历史脚本保持 NULL，不回填）。

关联表从 project/collection/asset/shot/product 侧均 CASCADE：删项目/集合只删自身关联行，
素材/镜头被删除时关联随之清理；绝不反向删除业务实体。script_project.project_id 用 SET NULL，
项目删除（PR-07）时清空引用而非删脚本。

downgrade 删除本迁移新增的列、关联表、collection、project 与 project_status 枚举，回到 0009；
不影响 0009 及之前任何结构，不触碰 asset/shot/product/AI/搜索/导出数据。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_projects_collections"
down_revision: str | None = "0009_script_matching_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


project_status = postgresql.ENUM("active", "archived", name="project_status")


def upgrade() -> None:
    bind = op.get_bind()
    project_status.create(bind, checkfirst=True)

    # ---- project ----
    op.create_table(
        "project",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="project_status", create_type=False),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("lock_version >= 1", name="ck_project_lock_version_min1"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project")),
    )

    # ---- project_asset ----
    op.create_table(
        "project_asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("order_index >= 0", name="ck_project_asset_order_index_nonneg"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"],
            name=op.f("fk_project_asset_project_id_project"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"],
            name=op.f("fk_project_asset_asset_id_asset"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_asset")),
        sa.UniqueConstraint("project_id", "asset_id", name="uq_project_asset_project_asset"),
        sa.UniqueConstraint("project_id", "order_index", name="uq_project_asset_project_order"),
    )
    op.create_index(op.f("ix_project_asset_project_id"), "project_asset", ["project_id"])
    op.create_index(op.f("ix_project_asset_asset_id"), "project_asset", ["asset_id"])

    # ---- project_shot ----
    op.create_table(
        "project_shot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("shot_id", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("order_index >= 0", name="ck_project_shot_order_index_nonneg"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"],
            name=op.f("fk_project_shot_project_id_project"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shot_id"], ["shot.id"],
            name=op.f("fk_project_shot_shot_id_shot"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_shot")),
        sa.UniqueConstraint("project_id", "shot_id", name="uq_project_shot_project_shot"),
        sa.UniqueConstraint("project_id", "order_index", name="uq_project_shot_project_order"),
    )
    op.create_index(op.f("ix_project_shot_project_id"), "project_shot", ["project_id"])
    op.create_index(op.f("ix_project_shot_shot_id"), "project_shot", ["shot_id"])

    # ---- project_product ----
    op.create_table(
        "project_product",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"],
            name=op.f("fk_project_product_project_id_project"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["product.id"],
            name=op.f("fk_project_product_product_id_product"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_product")),
        sa.UniqueConstraint(
            "project_id", "product_id", name="uq_project_product_project_product"
        ),
    )
    op.create_index(op.f("ix_project_product_project_id"), "project_product", ["project_id"])
    op.create_index(op.f("ix_project_product_product_id"), "project_product", ["product_id"])

    # ---- collection（必须归属 project，CASCADE）----
    op.create_table(
        "collection",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("lock_version >= 1", name="ck_collection_lock_version_min1"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"],
            name=op.f("fk_collection_project_id_project"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection")),
    )
    op.create_index(op.f("ix_collection_project_id"), "collection", ["project_id"])

    # ---- collection_shot ----
    op.create_table(
        "collection_shot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("shot_id", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "order_index >= 0", name="ck_collection_shot_order_index_nonneg"
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collection.id"],
            name=op.f("fk_collection_shot_collection_id_collection"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shot_id"], ["shot.id"],
            name=op.f("fk_collection_shot_shot_id_shot"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_shot")),
        sa.UniqueConstraint(
            "collection_id", "shot_id", name="uq_collection_shot_collection_shot"
        ),
        sa.UniqueConstraint(
            "collection_id", "order_index", name="uq_collection_shot_collection_order"
        ),
    )
    op.create_index(
        op.f("ix_collection_shot_collection_id"), "collection_shot", ["collection_id"]
    )
    op.create_index(op.f("ix_collection_shot_shot_id"), "collection_shot", ["shot_id"])

    # ---- script_project.project_id（可空 SET NULL；历史脚本保持 NULL，不回填）----
    op.add_column(
        "script_project",
        sa.Column("project_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_script_project_project_id_project"),
        "script_project",
        "project",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_script_project_project_id"), "script_project", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_script_project_project_id"), table_name="script_project")
    op.drop_constraint(
        op.f("fk_script_project_project_id_project"),
        "script_project",
        type_="foreignkey",
    )
    op.drop_column("script_project", "project_id")

    op.drop_index(op.f("ix_collection_shot_shot_id"), table_name="collection_shot")
    op.drop_index(
        op.f("ix_collection_shot_collection_id"), table_name="collection_shot"
    )
    op.drop_table("collection_shot")

    op.drop_index(op.f("ix_collection_project_id"), table_name="collection")
    op.drop_table("collection")

    op.drop_index(op.f("ix_project_product_product_id"), table_name="project_product")
    op.drop_index(op.f("ix_project_product_project_id"), table_name="project_product")
    op.drop_table("project_product")

    op.drop_index(op.f("ix_project_shot_shot_id"), table_name="project_shot")
    op.drop_index(op.f("ix_project_shot_project_id"), table_name="project_shot")
    op.drop_table("project_shot")

    op.drop_index(op.f("ix_project_asset_asset_id"), table_name="project_asset")
    op.drop_index(op.f("ix_project_asset_project_id"), table_name="project_asset")
    op.drop_table("project_asset")

    op.drop_table("project")

    project_status.drop(op.get_bind(), checkfirst=True)
