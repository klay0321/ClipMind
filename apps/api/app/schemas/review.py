"""审核相关响应/请求模型（PR-03B）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clipmind_shared.models.enums import ReviewAction, ReviewStatus
from pydantic import BaseModel, ConfigDict, Field


class ReviewActionIn(BaseModel):
    # 乐观锁版本（首次审核时为 0）
    lock_version: int = 0
    reviewer_label: str | None = Field(None, max_length=255)
    comment: str | None = Field(None, max_length=2000)
    # modify 时必需
    confirmed_result: dict[str, Any] | None = None
    confirmed_product_id: int | None = None
    # 客户端断言所审核的 AI 版本（用于一致性追溯，可空）
    source_ai_analysis_id: int | None = None
    source_input_fingerprint: str | None = None


class ReviewStateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shot_id: int
    shot_generation: int
    review_status: ReviewStatus
    confirmed_result: dict[str, Any] | None = None
    confirmed_product_id: int | None = None
    reviewer_label: str | None = None
    review_comment: str | None = None
    reviewed_at: datetime | None = None
    stale_at: datetime | None = None
    stale_reason: str | None = None
    lock_version: int
    updated_at: datetime | None = None


class EffectiveResultOut(BaseModel):
    shot_id: int
    review_status: str
    source: str
    confirmed: bool
    searchable: bool
    result: dict[str, Any] | None = None
    ai_status: str | None = None
    has_newer_ai_result: bool
    review_is_stale: bool
    stale_reason: str | None = None


class AssetSummaryOut(BaseModel):
    asset_id: int
    total_shots: int
    ai_unanalyzed_count: int
    ai_running_count: int
    ai_failed_count: int
    pending_review_count: int
    unreviewed_count: int
    confirmed_count: int
    modified_count: int
    rejected_count: int
    unable_count: int
    stale_review_count: int
    risk_shot_count: int
    primary_product: dict[str, Any] | None = None
    related_products: list[dict[str, Any]] = []
    ai_overall_status: str


class ReviewEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: ReviewAction
    reviewer_label: str | None = None
    shot_generation_snapshot: int | None = None
    source_ai_analysis_id: int | None = None
    before_data: dict[str, Any] | None = None
    after_data: dict[str, Any] | None = None
    comment: str | None = None
    created_at: datetime
    # 当前无登录体系：明确标记尚无正式 user_id
    reviewer_id: int | None = None
