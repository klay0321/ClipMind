"""PR-06B：收藏（PRD §7.14.2 四类：素材 / 镜头 / 搜索结果 / 脚本匹配结果）。

- ``asset`` 类型关联 ``asset_id``；``shot`` / ``search_result`` / ``script_match_result``
  最终都引用真实 ``shot_id``（搜索结果/脚本候选解析到底层镜头）。
- ``context`` 仅存**安全**来源快照（来源/分数/query 摘要/segment 信息），有长度上限，
  不存完整隐私脚本、不存本机路径。
- 去重：同一 ``(target_type, 底层实体)`` 不重复收藏（部分唯一索引）。
- 无鉴权体系，单租户全局；删除收藏只删 ``favorite`` 行，绝不删 Asset/Shot。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import FavoriteTargetType

# context JSONB 序列化后的字节上限（service 层校验，防止塞入完整脚本）
FAVORITE_CONTEXT_MAX_BYTES = 4096


class Favorite(Base):
    __tablename__ = "favorite"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[FavoriteTargetType] = mapped_column(
        pg_enum(FavoriteTargetType, "favorite_target_type")
    )
    # asset 类型用 asset_id；其余三类用 shot_id（二者互斥，由 CheckConstraint 保证）
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), nullable=True, index=True
    )
    shot_id: Mapped[int | None] = mapped_column(
        ForeignKey("shot.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 安全来源快照（分数 / query 摘要 / segment 信息 / 来源标识），有长度上限
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        # target 一致性：asset 类型只能挂 asset_id；其余只能挂 shot_id
        CheckConstraint(
            "(target_type = 'asset' AND asset_id IS NOT NULL AND shot_id IS NULL) OR "
            "(target_type <> 'asset' AND shot_id IS NOT NULL AND asset_id IS NULL)",
            name="favorite_target_consistency",
        ),
        # 去重：asset 按 asset_id 唯一
        Index(
            "uq_favorite_asset",
            "asset_id",
            unique=True,
            postgresql_where=sa_text("target_type = 'asset'"),
        ),
        # 去重：shot 类（含 search_result / script_match_result）按 (类型, shot_id) 唯一
        Index(
            "uq_favorite_shot",
            "target_type",
            "shot_id",
            unique=True,
            postgresql_where=sa_text("shot_id IS NOT NULL"),
        ),
    )
