"""PM：产品素材正式关系（product_media_link；docs/PRODUCT_MEDIA.md）。

冻结语义：
- **人工确认的产品素材关系 = 系统正式事实**；文件名/路径/文本/视觉模型结果
  只是辅助候选，绝不自动写入本表。
- 单目标：asset_id / shot_id 恰好一个非空（沿用 alias/reference 范式）。
- 目标产品：family_id 必填；variant_id 可选精化（service 校验归属，绝不从
  Family 自动推断 Variant）。
- role：primary 至多一个（部分唯一索引），related 多条（多产品同框）。
- origin ∈ PRODUCT_LINK_ORIGINS；visual_suggestion_confirmed 仅接受
  local provider（fake 结果禁止落正式关系，service 强制）。
- Shot 继承：**查询期合成**（shot 无自身 link 时取 asset links 标记
  inherited），不复制行 → 重新分析不迁移历史事实、Asset 移动（稳定身份）
  不断链；历史（retired）shot 的 link 保留可查。
- 删除=物理删链接行（关系非 append-only 账本；不触碰任何媒体文件）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, utcnow


class ProductMediaLink(Base):
    """媒体（Asset）或镜头（Shot）→ 产品（Family/可选 Variant）的正式关系。"""

    __tablename__ = "product_media_link"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), nullable=True
    )
    shot_id: Mapped[int | None] = mapped_column(
        ForeignKey("shot.id", ondelete="CASCADE"), nullable=True
    )
    family_id: Mapped[int] = mapped_column(
        ForeignKey("product_family.id", ondelete="CASCADE")
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variant.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(16), default="related")  # PRODUCT_LINK_ROLES
    origin: Mapped[str] = mapped_column(String(32), default="manual")  # PRODUCT_LINK_ORIGINS
    actor_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN asset_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN shot_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="pml_exactly_one_target",
        ),
        # 同目标对同 Family 至多一条（role/variant 经 PATCH 变更）
        Index(
            "uq_pml_asset_family",
            "asset_id",
            "family_id",
            unique=True,
            postgresql_where=text("asset_id IS NOT NULL"),
        ),
        Index(
            "uq_pml_shot_family",
            "shot_id",
            "family_id",
            unique=True,
            postgresql_where=text("shot_id IS NOT NULL"),
        ),
        # primary 至多一个
        Index(
            "uq_pml_asset_primary",
            "asset_id",
            unique=True,
            postgresql_where=text("asset_id IS NOT NULL AND role = 'primary'"),
        ),
        Index(
            "uq_pml_shot_primary",
            "shot_id",
            unique=True,
            postgresql_where=text("shot_id IS NOT NULL AND role = 'primary'"),
        ),
        Index("ix_pml_family_id", "family_id"),
        Index("ix_pml_family_role", "family_id", "role"),
    )
