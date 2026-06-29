"""PR-06B 动态集合 schema（查询型集合，必须归属 Project，实时 re-run）。"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models.enums import SearchKind
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import Page


class DynamicCollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    search_kind: SearchKind
    query: dict  # 原始搜索请求；service 经 query_serde 校验并去分页

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("名称不能为空")
        return v


class DynamicCollectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    search_kind: SearchKind | None = None
    query: dict | None = None
    lock_version: int = Field(ge=1)


class DynamicCollectionOut(BaseModel):
    id: int
    project_id: int
    name: str
    description: str | None
    search_kind: SearchKind
    query: dict
    lock_version: int
    created_at: datetime
    updated_at: datetime


DynamicCollectionPage = Page[DynamicCollectionOut]
