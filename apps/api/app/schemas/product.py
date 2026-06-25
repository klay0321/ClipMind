"""产品库相关 schema（PR-03B）。"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models.enums import ProductStatus, TagSource
from pydantic import BaseModel, ConfigDict, Field


class ProductIn(BaseModel):
    brand: str | None = Field(None, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    model: str | None = Field(None, max_length=255)
    sku: str | None = Field(None, max_length=255)
    selling_points: list[str] | None = None


class ProductUpdateIn(BaseModel):
    brand: str | None = None
    name: str | None = Field(None, max_length=255)
    model: str | None = None
    sku: str | None = None
    selling_points: list[str] | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand: str | None
    name: str
    model: str | None
    sku: str | None
    selling_points: list[str] | None = None
    status: ProductStatus
    created_at: datetime
    updated_at: datetime


class AliasIn(BaseModel):
    alias: str = Field(..., min_length=1, max_length=255)


class ProductAliasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    alias: str
    normalized_alias: str


class ProductImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    created_at: datetime


class AssetProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: int
    product_id: int
    source: TagSource
    confidence: float | None = None
    match_type: str | None = None
    match_score: float | None = None
    active: bool


class AssetProductsIn(BaseModel):
    product_ids: list[int]
    reviewer_label: str | None = Field(None, max_length=255)


class PrimaryProductIn(BaseModel):
    product_id: int | None = None


class CandidateOut(BaseModel):
    product_id: int
    product_name: str
    brand: str | None = None
    model: str | None = None
    sku: str | None = None
    match_type: str
    match_score: float
    match_reason: str
