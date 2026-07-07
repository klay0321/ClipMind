"""PM：产品素材关系 API 契约（人工确认 = 正式事实）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LinkCreateIn(BaseModel):
    target_type: str  # asset | shot
    target_id: int
    family_id: int
    variant_id: int | None = None
    role: str = "related"          # primary | related
    origin: str = "manual"         # PRODUCT_LINK_ORIGINS（候选确认由前端传对应值）
    note: str | None = Field(default=None, max_length=500)


class LinkUpdateIn(BaseModel):
    role: str | None = None
    variant_id: int | None = None
    clear_variant: bool = False
    note: str | None = Field(default=None, max_length=500)


class LinkOut(BaseModel):
    id: int
    asset_id: int | None
    shot_id: int | None
    family_id: int
    family_name: str | None = None
    family_code: str | None = None
    variant_id: int | None
    variant_name: str | None = None
    role: str
    origin: str
    actor_label: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class BulkLinkIn(BaseModel):
    items: list[dict] = Field(min_length=1, max_length=200)  # {target_type, target_id}
    family_id: int
    variant_id: int | None = None
    role: str = "related"
    origin: str = "bulk_manual"


class BulkDeleteIn(BaseModel):
    link_ids: list[int] = Field(min_length=1, max_length=200)


class BulkResultOut(BaseModel):
    completed: list[dict]
    skipped: list[dict]
    failed: list[dict]
    operation_id: int | None = None  # OPS：本次批量的操作事件 id（撤销入口）


class FamilySummaryOut(BaseModel):
    family_id: int
    code: str
    name_zh: str
    status: str
    onboarding_status: str | None = None
    variant_count: int
    reference_count: int
    image_count: int
    video_count: int
    shot_link_count: int
    effective_shot_count: int = 0
    final_video_count: int = 0
    confirmed_usage_count: int
    coverage_status: str = ""
    coverage_gaps: list[str] = []


class ShotLinksViewOut(BaseModel):
    shot_id: int
    generation: int
    is_historical: bool
    effective_source: str  # shot_override | asset_inherited
    own: list[LinkOut]
    inherited: list[LinkOut]
    effective: list[LinkOut]


class SuggestionOut(BaseModel):
    family_id: int
    family_name: str
    family_code: str
    suggestion_type: str    # path | filename | alias | ai_text | visual
    matched_text: str
    matched_in: str
    origin_on_confirm: str  # 人工确认时应携带的 origin
    score: float | None = None          # 仅 visual：相似度分数
    candidate_id: int | None = None     # 仅 visual：候选行 id（dismiss 用）
