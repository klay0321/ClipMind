"""PR-A1 通用产品目录 schema。"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models.enums import CatalogStatus
from pydantic import BaseModel, ConfigDict, Field


# ---------------- Category ----------------
class CategoryIn(BaseModel):
    code: str | None = Field(None, max_length=64)
    name_zh: str = Field(..., min_length=1, max_length=255)
    name_en: str | None = Field(None, max_length=255)
    description: str | None = None
    sort_order: int | None = 0


class CategoryUpdateIn(BaseModel):
    name_zh: str | None = Field(None, min_length=1, max_length=255)
    name_en: str | None = None
    description: str | None = None
    sort_order: int | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name_zh: str
    name_en: str | None
    description: str | None = None
    status: CatalogStatus
    sort_order: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


# ---------------- Family ----------------
class FamilyIn(BaseModel):
    code: str | None = Field(None, max_length=64)
    category_id: int | None = None
    name_zh: str = Field(..., min_length=1, max_length=255)
    name_en: str | None = Field(None, max_length=255)
    description: str | None = None
    legacy_product_id: int | None = None


class FamilyUpdateIn(BaseModel):
    name_zh: str | None = Field(None, min_length=1, max_length=255)
    name_en: str | None = None
    description: str | None = None
    category_id: int | None = None


class FamilyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    category_id: int | None
    name_zh: str
    name_en: str | None
    description: str | None = None
    status: CatalogStatus
    merged_into_id: int | None = None
    legacy_product_id: int | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


# ---------------- Variant ----------------
class VariantIn(BaseModel):
    code: str | None = Field(None, max_length=64)
    family_id: int
    name_zh: str = Field(..., min_length=1, max_length=255)
    name_en: str | None = Field(None, max_length=255)
    description: str | None = None


class VariantUpdateIn(BaseModel):
    name_zh: str | None = Field(None, min_length=1, max_length=255)
    name_en: str | None = None
    description: str | None = None


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    family_id: int
    name_zh: str
    name_en: str | None
    description: str | None = None
    status: CatalogStatus
    merged_into_id: int | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


# ---------------- SKU ----------------
class SkuIn(BaseModel):
    code: str | None = Field(None, max_length=64)
    family_id: int
    variant_id: int | None = None
    sku_code: str | None = Field(None, max_length=128)
    name_zh: str = Field(..., min_length=1, max_length=255)
    name_en: str | None = Field(None, max_length=255)


class SkuUpdateIn(BaseModel):
    name_zh: str | None = Field(None, min_length=1, max_length=255)
    name_en: str | None = None
    sku_code: str | None = Field(None, max_length=128)


class SkuOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    family_id: int
    variant_id: int | None
    sku_code: str | None
    name_zh: str
    name_en: str | None
    status: CatalogStatus
    merged_into_id: int | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


# ---------------- Alias ----------------
class CatalogAliasIn(BaseModel):
    target_level: str = Field(..., pattern="^(category|family|variant|sku)$")
    target_id: int
    alias: str = Field(..., min_length=1, max_length=255)
    language: str | None = Field(None, max_length=16)
    alias_type: str = Field("zh_name", max_length=32)
    is_primary: bool = False


class CatalogAliasUpdateIn(BaseModel):
    alias: str | None = Field(None, min_length=1, max_length=255)
    language: str | None = None
    alias_type: str | None = Field(None, max_length=32)
    is_primary: bool | None = None


class CatalogAliasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category_id: int | None
    family_id: int | None
    variant_id: int | None
    sku_id: int | None
    alias: str
    normalized_alias: str
    language: str | None
    alias_type: str
    is_primary: bool


# ---------------- 通用 ----------------
class StatusIn(BaseModel):
    status: CatalogStatus


class MergeIn(BaseModel):
    target_id: int


class CatalogNode(BaseModel):
    level: str
    id: int | None
    code: str
    name_zh: str
    name_en: str | None = None
    sku_code: str | None = None
    status: CatalogStatus
    redirected: bool | None = None


class TreeNode(BaseModel):
    level: str
    id: int | None
    code: str
    name_zh: str
    name_en: str | None = None
    status: CatalogStatus
    children: list[TreeNode] = []


TreeNode.model_rebuild()


class CategoryListResponse(BaseModel):
    items: list[CategoryOut]
    total: int


class FamilyListResponse(BaseModel):
    items: list[FamilyOut]
    total: int


class VariantListResponse(BaseModel):
    items: list[VariantOut]
    total: int


class SkuListResponse(BaseModel):
    items: list[SkuOut]
    total: int
