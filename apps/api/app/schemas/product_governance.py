"""PR-A2 Gate B schema：完整度策略 / readiness / 入驻审核 / 混淆关系 / 变更历史。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clipmind_shared.models.enums import CatalogStatus
from pydantic import BaseModel, ConfigDict, Field


# ---------------- Readiness Policy ----------------
class ReadinessPolicyIn(BaseModel):
    category_id: int
    name: str | None = Field(None, max_length=255)
    min_reference_count: int | None = Field(None, ge=0, le=100)
    required_angles: list[str] | None = None
    min_identity_attribute_count: int | None = Field(None, ge=0, le=50)
    require_primary_reference: bool | None = None
    require_name_en: bool | None = None
    require_alias: bool | None = None
    require_sku_for_active_variant: bool | None = None


class ReadinessPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category_id: int
    version: int
    name: str
    min_reference_count: int
    required_angles: list[str] | None
    min_identity_attribute_count: int
    require_primary_reference: bool
    require_name_en: bool
    require_alias: bool
    require_sku_for_active_variant: bool
    status: CatalogStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class ReadinessPolicyListResponse(BaseModel):
    items: list[ReadinessPolicyOut]
    total: int


# ---------------- Readiness 计算结果 ----------------
class ReadinessCheck(BaseModel):
    key: str
    passed: bool
    current: Any = None
    required: Any = None


class ReadinessOut(BaseModel):
    target_level: str
    target_id: int
    score: int
    complete: bool
    policy_id: int | None
    policy_version: int
    checks: list[ReadinessCheck]
    missing_items: list[dict[str, Any]]
    blocking_items: list[dict[str, Any]]
    evaluated_at: str
    ai_recognition_enabled: bool


# ---------------- Onboarding ----------------
class OnboardingActionIn(BaseModel):
    note: str | None = Field(None, max_length=2000)
    # 非可信人工显示名（当前无用户认证，不作为权限审计依据）
    actor_label: str | None = Field(None, max_length=64)


class OnboardingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    family_id: int | None
    variant_id: int | None
    sku_id: int | None
    status: str
    policy_id: int | None
    policy_version: int | None
    readiness_score: int | None
    readiness_snapshot: dict[str, Any] | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    reviewer_note: str | None
    submitted_by: str | None
    reviewed_by: str | None
    created_at: datetime
    updated_at: datetime


class OnboardingListResponse(BaseModel):
    items: list[OnboardingOut]
    total: int


# ---------------- Confusion Pair ----------------
class ConfusionFeature(BaseModel):
    feature: str = Field(..., min_length=1, max_length=100)
    left_value: str = Field("", max_length=300)
    right_value: str = Field("", max_length=300)
    visible_in_reference: bool = False
    identity_relevant: bool = False


class ConfusionPairIn(BaseModel):
    target_level: str = Field(..., pattern="^(family|variant|sku)$")
    left_target_id: int
    right_target_id: int
    severity: str | None = Field(None, max_length=16)
    reason: str | None = None
    distinguishing_features: list[ConfusionFeature] | None = None
    review_note: str | None = None


class ConfusionPairUpdateIn(BaseModel):
    severity: str | None = Field(None, max_length=16)
    reason: str | None = None
    distinguishing_features: list[ConfusionFeature] | None = None
    review_note: str | None = None


class ConfusionSide(BaseModel):
    id: int
    name_zh: str
    code: str | None
    status: CatalogStatus


class ConfusionPairOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    target_level: str
    left_target_id: int
    right_target_id: int
    severity: str
    reason: str | None
    distinguishing_features: list[dict[str, Any]] | None
    review_note: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    # 两侧展示信息（列表/详情响应时补充）
    left: ConfusionSide | None = None
    right: ConfusionSide | None = None


class ConfusionPairListResponse(BaseModel):
    items: list[ConfusionPairOut]
    total: int


# ---------------- Catalog Revision（只读）----------------
class RevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    revision_number: int
    entity_type: str
    entity_id: int
    action: str
    before_data: dict[str, Any] | None
    after_data: dict[str, Any] | None
    change_summary: str | None
    correlation_id: str
    actor_label: str | None
    created_at: datetime


class RevisionListResponse(BaseModel):
    items: list[RevisionOut]
    total: int
