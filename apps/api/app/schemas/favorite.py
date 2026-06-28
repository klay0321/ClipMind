"""PR-06B 收藏 schema（四类：asset / shot / search_result / script_match_result）。"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models.enums import FavoriteTargetType
from pydantic import BaseModel

from app.schemas.common import Page
from app.schemas.shot import ShotOut


class FavoriteCreate(BaseModel):
    target_type: FavoriteTargetType
    asset_id: int | None = None
    shot_id: int | None = None
    # 安全来源快照（分数/query 摘要/segment 信息/来源标识）；service 校验长度上限、剔除敏感字段
    context: dict | None = None


class AssetMini(BaseModel):
    id: int
    filename: str
    duration: float | None = None
    width: int | None = None
    height: int | None = None


class FavoriteOut(BaseModel):
    id: int
    target_type: FavoriteTargetType
    asset_id: int | None
    shot_id: int | None
    context: dict | None
    created_at: datetime
    # 解析视图（便于 /favorites 直接渲染，不必二次取数）
    shot: ShotOut | None = None
    asset: AssetMini | None = None


FavoritePage = Page[FavoriteOut]
