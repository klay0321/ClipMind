"""PR-06A 项目 API schema。

设计：
- 创建只接受名称 + 可选描述；状态变更走 archive/unarchive（不在 PATCH 里改 status）。
- PATCH 用 ``model_fields_set`` 区分"未提供"与"显式置空"，且 ``extra=forbid`` 拒绝任意字段。
- 改名/归档/重排用 ``lock_version`` 乐观锁，不匹配返回 409。
- 批量添加成员返回 completed/skipped/failed（重复=skipped，目标不存在=failed），不整批失败。
- 绝不暴露源文件绝对路径；镜头资源由前端按 shot_id 拼 URL。
"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models.enums import ProjectStatus
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.asset import AssetOut
from app.schemas.common import Page

# 批量成员操作单次上限（防止超大请求；超出由 422 拒绝）
MEMBER_BATCH_MAX = 500


# ---- 请求 ----


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("项目名称不能为空")
        return v


class ProjectUpdateRequest(BaseModel):
    """改名/改描述（乐观锁）。仅提供的字段被更新；不允许改 status（用 archive/unarchive）。"""

    model_config = ConfigDict(extra="forbid")

    lock_version: int = Field(ge=1, description="当前项目 lock_version；不匹配返回 409")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("项目名称不能为空")
        return v


class ProjectArchiveRequest(BaseModel):
    lock_version: int = Field(ge=1, description="当前项目 lock_version；不匹配返回 409")


class MemberBatchRequest(BaseModel):
    """批量加入成员。重复成员幂等跳过（依赖唯一约束），可选 token 仅用于客户端去抖。"""

    ids: list[int] = Field(min_length=1, max_length=MEMBER_BATCH_MAX)
    token: str | None = Field(default=None, max_length=64)


class MemberReorderRequest(BaseModel):
    """成员重排：给出完整目标顺序（必须恰好覆盖当前全部成员）；用父对象 lock_version 乐观锁。"""

    ids: list[int] = Field(min_length=1, max_length=MEMBER_BATCH_MAX)
    lock_version: int = Field(ge=1, description="父对象（项目）lock_version；不匹配/已归档返回 409")


# ---- 响应 ----


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    status: ProjectStatus
    archived_at: datetime | None
    lock_version: int
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(Page[ProjectOut]):
    pass


class ProjectStatsOut(BaseModel):
    project_id: int
    asset_count: int
    visible_shot_count: int
    explicit_shot_count: int
    collection_count: int
    collection_shot_count: int
    product_count: int
    script_count: int
    active_script_count: int
    locked_segment_count: int
    gap_segment_count: int
    completed_script_export_count: int
    risk_shot_count: int
    searchable_shot_count: int
    updated_at: datetime


class ProjectAssetItemOut(BaseModel):
    """项目素材成员：素材信息 + 项目内手工排序位次。"""

    order_index: int
    asset: AssetOut


class ProjectAssetListResponse(Page[ProjectAssetItemOut]):
    pass


class BatchFailureOut(BaseModel):
    id: int
    error: str


class BatchResultOut(BaseModel):
    completed: list[int]
    skipped: list[int]
    failed: list[BatchFailureOut]
