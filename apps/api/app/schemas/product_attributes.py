"""PR-A2 Gate A schema：动态属性定义/值 + 产品参考图 + profile 聚合。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from clipmind_shared.models.enums import CatalogStatus
from pydantic import BaseModel, ConfigDict, Field

_LEVEL = "^(family|variant|sku)$"


# ---------------- 属性定义 ----------------
class AttributeDefinitionIn(BaseModel):
    category_id: int | None = None
    key: str | None = Field(None, max_length=64)
    name_zh: str = Field(..., min_length=1, max_length=255)
    name_en: str | None = Field(None, max_length=255)
    description: str | None = None
    value_type: str = Field(..., max_length=16)
    unit: str | None = Field(None, max_length=32)
    allowed_values: list[str] | None = None
    validation_rules: dict[str, Any] | None = None
    required: bool = False
    searchable: bool = False
    identity_relevant: bool = False
    multi_value: bool = False
    sort_order: int | None = 0


class AttributeDefinitionUpdate(BaseModel):
    name_zh: str | None = Field(None, min_length=1, max_length=255)
    name_en: str | None = None
    description: str | None = None
    unit: str | None = Field(None, max_length=32)
    allowed_values: list[str] | None = None
    validation_rules: dict[str, Any] | None = None
    required: bool | None = None
    searchable: bool | None = None
    identity_relevant: bool | None = None
    sort_order: int | None = None


class AttributeDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category_id: int | None
    key: str
    name_zh: str
    name_en: str | None
    description: str | None = None
    value_type: str
    unit: str | None = None
    allowed_values: list[str] | None = None
    validation_rules: dict[str, Any] | None = None
    required: bool
    searchable: bool
    identity_relevant: bool
    multi_value: bool
    sort_order: int
    status: CatalogStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class AttributeDefinitionListResponse(BaseModel):
    items: list[AttributeDefinitionOut]
    total: int


class AttributeStatusIn(BaseModel):
    status: CatalogStatus


# ---------------- 属性值 ----------------
class AttributeValueSetIn(BaseModel):
    definition_id: int
    target_level: str = Field(..., pattern=_LEVEL)
    target_id: int
    value: Any  # 类型由 definition.value_type 决定（后端强校验）


class AttributeValueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    definition_id: int
    family_id: int | None
    variant_id: int | None
    sku_id: int | None
    value_text: str | None = None
    value_number: Decimal | None = None
    value_boolean: bool | None = None
    value_json: list[Any] | None = None
    value_date: date | None = None
    unit: str | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ---------------- 参考图 ----------------
class ReferenceAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    family_id: int | None
    variant_id: int | None
    sku_id: int | None
    media_type: str
    angle: str
    state: str
    quality_status: str
    is_primary: bool
    sort_order: int
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    sha256: str | None = None
    original_filename: str | None = None
    content_type: str | None = None
    description: str | None = None
    source_type: str | None = None
    has_thumbnail: bool = False
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class ReferenceAssetUpdateIn(BaseModel):
    angle: str | None = Field(None, max_length=32)
    quality_status: str | None = Field(None, max_length=16)
    state: str | None = Field(None, max_length=16)
    description: str | None = None
    sort_order: int | None = None


class ReferenceUploadError(BaseModel):
    filename: str
    detail: str


class ReferenceUploadResult(BaseModel):
    created: list[ReferenceAssetOut]
    errors: list[ReferenceUploadError]


class ReferenceBatchAngleIn(BaseModel):
    ids: list[int] = Field(..., min_length=1)
    angle: str = Field(..., max_length=32)


class ReferenceBatchIdsIn(BaseModel):
    ids: list[int] = Field(..., min_length=1)


# ---------------- profile 聚合 ----------------
class ProfileMissingItem(BaseModel):
    definition_id: int
    key: str
    name_zh: str


class ProfileOut(BaseModel):
    level: str
    id: int
    code: str | None = None
    name_zh: str
    category_id: int | None = None
    definition_count: int
    value_count: int
    required_total: int
    required_filled: int
    missing_required: list[ProfileMissingItem]
    completeness: float | None = None
    reference_total: int
    reference_by_angle: dict[str, int]
    reference_primary_id: int | None = None
    ai_recognition_enabled: bool = False
