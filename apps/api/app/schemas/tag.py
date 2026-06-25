"""标签字典 schema（PR-03B）。"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models.enums import ProductStatus, TagType
from pydantic import BaseModel, ConfigDict, Field


class TagIn(BaseModel):
    tag_type: TagType
    tag_name: str = Field(..., min_length=1, max_length=255)


class TagUpdateIn(BaseModel):
    tag_name: str = Field(..., min_length=1, max_length=255)


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tag_type: TagType
    tag_name: str
    normalized_name: str
    status: ProductStatus
    created_at: datetime
    updated_at: datetime
