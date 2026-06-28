"""PR-06A 静态镜头集合数据模型（以 PostgreSQL 为事实来源）。

两表：
- ``collection``：手工镜头集合，**必须归属一个 Project**（PR-06A 不实现独立集合，也不实现
  动态查询集合；绝不保存查询 JSON 或 shot id 数组）。
- ``collection_shot``：集合↔镜头成员（手工排序）。

关键约束/安全（PR-06A）：
- ``project_id`` ``ON DELETE CASCADE``：集合随项目消亡（项目删除属 PR-07）。
- ``collection_shot`` ``(collection_id, shot_id)`` 唯一防重复；``(collection_id, order_index)`` 唯一
  支撑稳定手工排序；``shot_id`` ``CASCADE``：删集合只级联删 ``collection_shot``，**绝不删除 Shot**；
  镜头被再分析删除时成员行随之清理。
- 同一 Shot 可出现在不同 Collection（多对多）。
- ``lock_version >= 1``：改名/重排并发用乐观锁保护。
- 归档项目下不允许新建/修改 Collection（service 层统一保护）。
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

from clipmind_shared.db.base import Base, utcnow

COLLECTION_NAME_MAX = 200
COLLECTION_DESC_MAX = 2000


class Collection(Base):
    __tablename__ = "collection"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(COLLECTION_NAME_MAX))
    description: Mapped[str | None] = mapped_column(
        String(COLLECTION_DESC_MAX), nullable=True
    )

    lock_version: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("lock_version >= 1", name="lock_version_min1"),
    )


class CollectionShot(Base):
    __tablename__ = "collection_shot"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collection.id", ondelete="CASCADE"), index=True
    )
    shot_id: Mapped[int] = mapped_column(
        ForeignKey("shot.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "collection_id", "shot_id", name="uq_collection_shot_collection_shot"
        ),
        UniqueConstraint(
            "collection_id", "order_index", name="uq_collection_shot_collection_order"
        ),
        CheckConstraint("order_index >= 0", name="order_index_nonneg"),
    )
