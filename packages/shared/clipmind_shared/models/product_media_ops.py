"""OPS：产品素材操作审计（append-only）与可撤销批量绑定。

- 每次单个/批量绑定、解除、撤销都落一行操作事件（绝不更新既有事件语义，
  undo 只补写 undone_* 字段与新的 undo 事件行）；
- `created_link_ids` 只存该操作创建的 link id 列表（不复制业务行——素材
  事实仍只在 product_media_link）；
- undo 语义：只删"该批创建、此后未被修改（updated_at==created_at）且仍
  存在"的关系；其余记入 undone_detail 不可撤销明细。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, utcnow

# 操作类型白名单（String+service 校验，免迁移扩展）
OPERATION_KINDS: tuple[str, ...] = (
    "single_link",      # 单个绑定
    "bulk_link",        # 批量绑定
    "unlink",           # 单个解除
    "bulk_unlink",      # 批量解除
    "undo",             # 撤销（指向被撤销的操作）
)


class ProductMediaOperation(Base):
    """产品素材操作事件（append-only；撤销依据与运营审计）。"""

    __tablename__ = "product_media_operation"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))  # OPERATION_KINDS
    family_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_family.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    # 该操作创建的 link id 列表（undo 依据）；unlink 操作存被删的 link 描述
    created_link_ids: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # undo 状态（append-only：undo 本身也是一行 kind=undo 事件，这里只记标记）
    undone_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    undone_by_operation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    undone_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_pmo_created_at", "created_at"),
        Index("ix_pmo_kind", "kind"),
    )
