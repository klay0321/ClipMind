"""PR-06B：动态镜头集合（查询型集合）。

与静态 ``collection``（``collection_shot`` 落地成员）**不同**：动态集合保存查询条件
（``query`` JSONB），打开时实时调用搜索服务 re-run 计算成员，**绝不落地 CollectionShot**、
不把搜索结果全部写库。与 ``saved_search`` **分表**：动态集合**必须归属一个 Project**，
出现在项目的 Collections 上下文，与静态集合在 UI 中明确区分。

- ``project_id`` 非空、``ON DELETE CASCADE``（随项目消亡，项目删除属 PR-07）。
- ``lock_version`` 乐观锁；归档项目下只读（service 层统一保护）。
- 删除动态集合不删除任何 Shot。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import SearchKind

DYNAMIC_COLLECTION_NAME_MAX = 200
DYNAMIC_COLLECTION_DESC_MAX = 2000


class DynamicCollection(Base):
    __tablename__ = "dynamic_collection"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(DYNAMIC_COLLECTION_NAME_MAX))
    description: Mapped[str | None] = mapped_column(
        String(DYNAMIC_COLLECTION_DESC_MAX), nullable=True
    )
    search_kind: Mapped[SearchKind] = mapped_column(pg_enum(SearchKind, "search_kind"))
    # 序列化的搜索请求（去 page/page_size；re-run 时再校验）
    query: Mapped[dict] = mapped_column(JSONB)

    lock_version: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("lock_version >= 1", name="lock_version_min1"),
    )
