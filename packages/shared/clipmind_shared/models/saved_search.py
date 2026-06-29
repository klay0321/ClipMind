"""PR-06B：保存搜索（PRD §7.14.1「保存搜索条件」）。

保存一次完整搜索表单（``ShotSearchRequest`` 或 ``DescriptionMatchRequest``，去掉
分页参数）到 ``query`` JSONB；re-run 时按当前真实搜索服务重新计算，不复制搜索算法。

- ``project_id`` 可空（兼容项目级 §7.14.1 与全局列表级 §15.2），项目删除 SET NULL。
- ``lock_version`` 乐观锁（改名等并发冲突 409）。
- 与动态集合（``dynamic_collection``）**分表**：保存搜索是搜索页便捷件，动态集合归属项目。
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

SAVED_SEARCH_NAME_MAX = 200


class SavedSearch(Base):
    __tablename__ = "saved_search"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(SAVED_SEARCH_NAME_MAX))
    search_kind: Mapped[SearchKind] = mapped_column(pg_enum(SearchKind, "search_kind"))
    # 序列化的搜索请求（去 page/page_size；兼容旧字段，re-run 时再校验）
    query: Mapped[dict] = mapped_column(JSONB)

    lock_version: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("lock_version >= 1", name="lock_version_min1"),
    )
