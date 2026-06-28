"""PR-05 Gate A：脚本项目 / 段落 API schema。

设计：
- 创建只接受脚本文本与名称；拆段由 ``/parse`` 触发（解析器由服务端按配置装配，前端不指定列名）。
- 段落编辑用 ``lock_version`` 乐观锁，避免与（Gate B）重匹配/并发编辑互相覆盖。
- PATCH 用 ``model_fields_set`` 区分"未提供"与"显式置空"。
"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.script.schema import _sanitize_terms
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import Page

# 段落结构化需求允许的键（与解析器 _structured_from_parsed 一致）；其余键丢弃
_ALLOWED_STRUCTURED_KEYS = (
    "products",
    "scenes",
    "actions",
    "shot_types",
    "marketing_uses",
    "people",
    "objects",
    "quality_requirements",
    "selling_points",
    "must_include",
)

# ---- 请求 ----


class ScriptCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    raw_script: str = Field(min_length=1)
    source_format: str = Field(default="paste", max_length=16)


class ScriptUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class ScriptParseRequest(BaseModel):
    """可选解析覆盖（默认按服务端配置）。"""

    parser: str | None = Field(default=None, description="rulebased/fake/mimo；空=按配置")


class SegmentUpdateRequest(BaseModel):
    """单段编辑（乐观锁）。仅提供的字段被更新。"""

    model_config = ConfigDict(extra="forbid")

    lock_version: int = Field(description="当前段落 lock_version；不匹配返回 409")
    segment_text: str | None = None
    visual_requirement: str | None = None
    target_duration_min: float | None = None
    target_duration_max: float | None = None
    product_id: int | None = None
    structured_requirements: dict | None = None
    negative_terms: list[str] | None = None
    excluded_risks: list[str] | None = None
    allow_similar_scene: bool | None = None
    allow_similar_action: bool | None = None
    locked_shot_id: int | None = None

    @field_validator("structured_requirements")
    @classmethod
    def _clean_structured(cls, v: dict | None) -> dict | None:
        """白名单键 + 每键强制为净化后的字符串列表；丢弃未知键，防注入/膨胀。"""
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("structured_requirements 必须是对象")
        return {k: _sanitize_terms(v.get(k)) for k in _ALLOWED_STRUCTURED_KEYS if k in v}


class SegmentReorderRequest(BaseModel):
    """整项目段落重排：给出全部段落 id 的目标顺序（必须是该项目的完整集合）。"""

    segment_ids: list[int] = Field(min_length=1)


# ---- 响应 ----


class ScriptSegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    script_project_id: int
    order_index: int
    segment_text: str
    visual_requirement: str | None
    normalized_text: str | None
    target_duration_min: float | None
    target_duration_max: float | None
    product_id: int | None
    structured_requirements: dict | None
    negative_terms: list[str] | None
    excluded_risks: list[str] | None
    allow_similar_scene: bool
    allow_similar_action: bool
    current_generation: int
    locked_shot_id: int | None
    lock_version: int
    candidates_stale: bool
    parser_warnings: list[str] | None
    created_at: datetime
    updated_at: datetime


class ScriptProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source_format: str
    status: str
    parse_status: str
    parser_provider: str | None
    parser_model: str | None
    parser_warnings: list[str] | None
    result_schema_version: int
    segment_count: int = 0
    created_at: datetime
    updated_at: datetime


class ScriptDetailOut(ScriptProjectOut):
    segments: list[ScriptSegmentOut] = []


class ScriptListResponse(Page[ScriptProjectOut]):
    pass
