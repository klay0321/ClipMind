"""PR-06A 素材集合 API schema。

集合必须归属一个 Project；成员只含 Shot（静态手工集合）。改名/重排用 ``lock_version`` 乐观锁。
归档项目下不允许新建/修改集合（service 层统一保护，返回 409）。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import Page


class CollectionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("集合名称不能为空")
        return v


class CollectionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lock_version: int = Field(ge=1, description="当前集合 lock_version；不匹配返回 409")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("集合名称不能为空")
        return v


class CollectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    description: str | None
    lock_version: int
    created_at: datetime
    updated_at: datetime
    # 成员数（列表/详情由 service 批量填充，避免 N+1；默认 0 仅占位）
    shot_count: int = 0


class CollectionListResponse(Page[CollectionOut]):
    pass
