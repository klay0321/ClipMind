"""PR-06A 项目（业务工作空间）数据模型（以 PostgreSQL 为事实来源）。

四表：
- ``project``：业务项目（名称 + 描述 + 状态 + 归档时间 + 乐观锁）。是组织层，
  **不是文件夹**，与 ``source_directory``（文件来源）完全分离。
- ``project_asset``：项目↔素材显式关联（手工排序）。
- ``project_shot``：项目↔单独镜头显式关联（手工排序）。
- ``project_product``：项目↔产品引用（项目关注/允许的产品；Product 仍是全局实体）。

关键约束/安全（PR-06A）：
- ``status`` 仅 ``active`` / ``archived``（不实现 completed/删除/软删 deleted_at）。
- ``lock_version >= 1``：改名/归档/重排并发用乐观锁保护。
- 关联表 ``(project_id, *_id)`` 唯一防重复；``(project_id, order_index)`` 唯一支撑稳定手工排序。
- 关联从 ``project`` / ``asset`` / ``shot`` / ``product`` 侧均 ``CASCADE``：删项目只删自身关联行；
  素材/镜头被再分析等删除时关联行随之清理。**绝不反向删除 Asset/Shot/Product。**
- Project **本阶段不提供删除接口**（真正删除留待 PR-07 权限/审计/二次确认具备后）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import ProjectStatus

# 名称/描述长度上限（DB 兜底；schema 层亦校验并 strip）
PROJECT_NAME_MAX = 200
PROJECT_DESC_MAX = 2000


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(PROJECT_NAME_MAX))
    description: Mapped[str | None] = mapped_column(String(PROJECT_DESC_MAX), nullable=True)

    status: Mapped[ProjectStatus] = mapped_column(
        pg_enum(ProjectStatus, "project_status"), default=ProjectStatus.ACTIVE
    )
    # 归档时刻（NULL=未归档）。不是软删除：项目永远可见，只是写操作被冻结。
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 乐观锁：改名/归档/成员重排并发保护（>=1，创建即 1）
    lock_version: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("lock_version >= 1", name="lock_version_min1"),
    )


class ProjectAsset(Base):
    """项目↔素材显式关联。加入整段 Asset；其当前 Shot 在项目内可见，但不复制 Shot 数据。"""

    __tablename__ = "project_asset"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "asset_id", name="uq_project_asset_project_asset"),
        UniqueConstraint("project_id", "order_index", name="uq_project_asset_project_order"),
        CheckConstraint("order_index >= 0", name="order_index_nonneg"),
    )


class ProjectShot(Base):
    """项目↔单独镜头显式关联（只保存显式加入的镜头，不含 Asset 派生镜头）。"""

    __tablename__ = "project_shot"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    shot_id: Mapped[int] = mapped_column(
        ForeignKey("shot.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "shot_id", name="uq_project_shot_project_shot"),
        UniqueConstraint("project_id", "order_index", name="uq_project_shot_project_order"),
        CheckConstraint("order_index >= 0", name="order_index_nonneg"),
    )


class ProjectProduct(Base):
    """项目↔产品引用（项目关注/允许的产品）。仅引用关系，不改 Product/AssetProduct/审核。"""

    __tablename__ = "project_product"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "project_id", "product_id", name="uq_project_product_project_product"
        ),
    )
