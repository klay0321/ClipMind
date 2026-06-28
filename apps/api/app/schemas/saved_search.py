"""PR-06B 保存搜索 schema。"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models.enums import SearchKind
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import Page


class SavedSearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    search_kind: SearchKind
    query: dict  # 原始搜索请求；由 service 经 query_serde 校验并去分页
    project_id: int | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("名称不能为空")
        return v


class SavedSearchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    query: dict | None = None
    lock_version: int = Field(ge=1)


class SavedSearchOut(BaseModel):
    id: int
    project_id: int | None
    name: str
    search_kind: SearchKind
    query: dict
    lock_version: int
    created_at: datetime
    updated_at: datetime


SavedSearchPage = Page[SavedSearchOut]
