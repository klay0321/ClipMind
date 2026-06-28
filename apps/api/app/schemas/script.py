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
    selected_shot_id: int | None = None
    locked_shot_id: int | None
    lock_version: int
    match_status: str = "pending"
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


# ======================= Gate B：匹配 / 候选 / 选择锁定 =======================

# 候选数硬上限（与 clipmind_shared.script.editlist.MAX_CANDIDATE_LIMIT 一致）
MAX_CANDIDATE_LIMIT = 50


class ScriptMatchRequest(BaseModel):
    """全脚本匹配（同步逐段复用描述匹配）。match_token 提供幂等。"""

    model_config = ConfigDict(extra="forbid")

    candidate_limit: int | None = Field(default=None, ge=1, le=MAX_CANDIDATE_LIMIT)
    match_token: str | None = Field(default=None, max_length=128)
    skip_locked: bool = True  # 锁定段默认跳过、不覆盖


class SegmentMatchRequest(BaseModel):
    """单段匹配 / 重匹配。"""

    model_config = ConfigDict(extra="forbid")

    candidate_limit: int | None = Field(default=None, ge=1, le=MAX_CANDIDATE_LIMIT)
    match_token: str | None = Field(default=None, max_length=128)


class SegmentSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: int
    lock_version: int
    allow_override: bool = False  # 允许指定不在当前候选中的镜头


class SegmentLockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: int
    lock_version: int
    allow_override: bool = False
    force: bool = False  # 替换已存在的不同锁定须显式


class SegmentUnlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lock_version: int


# ---- 候选 / 状态响应 ----


class ScriptCandidateOut(BaseModel):
    shot_id: int
    asset_id: int | None = None
    rank: int
    final_score: float
    semantic_score: float | None = None
    lexical_score: float | None = None
    tag_score: float | None = None
    product_score: float | None = None
    quality_score: float | None = None
    review_bonus: float | None = None
    risk_penalty: float | None = None
    matched_reasons: list[str] = []
    unmatched_requirements: list[str] = []
    risk_warnings: list[str] = []
    # 镜头展示 brief（人工核对/预览）
    sequence_no: int | None = None
    start_time: float | None = None
    end_time: float | None = None
    duration: float | None = None
    preview_url: str | None = None
    thumbnail_url: str | None = None
    keyframe_url: str | None = None


class SegmentCandidatesResponse(BaseModel):
    segment_id: int
    generation: int           # 返回的代次（默认当前代次）
    current_generation: int
    match_status: str         # pending | matched | gap | degraded
    candidate_count: int
    best_score: float | None = None
    gap_reasons: list[str] = []
    reshoot_recommendation: list[str] = []
    requires_human_confirmation: bool = False
    degraded: bool = False
    candidates_stale: bool = False
    selected_shot_id: int | None = None
    locked_shot_id: int | None = None
    lock_version: int
    candidates: list[ScriptCandidateOut] = []


class ScriptMatchResponse(BaseModel):
    script_id: int
    total_segments: int
    completed_segments: list[int]
    skipped_locked_segments: list[int]
    failed_segments: list[dict]
    match_token: str | None = None


class SegmentMatchStatusOut(BaseModel):
    segment_id: int
    order_index: int
    match_status: str
    current_generation: int
    candidate_count: int
    best_score: float | None = None
    gap_reasons: list[str] = []
    reshoot_recommendation: list[str] = []
    requires_human_confirmation: bool = False
    degraded: bool = False
    candidates_stale: bool = False
    selected_shot_id: int | None = None
    locked_shot_id: int | None = None
    lock_version: int


class ScriptMatchStatusResponse(BaseModel):
    script_id: int
    total_segments: int
    matched_segments: int
    gap_segments: int
    locked_segments: int
    selected_segments: int
    pending_segments: int
    segments: list[SegmentMatchStatusOut] = []


# ---- 剪辑清单 ----


class EditListRowOut(BaseModel):
    segment_id: int
    segment_order: int
    segment_text: str
    target_duration_min: float | None = None
    target_duration_max: float | None = None
    selection_status: str       # locked | selected | recommended | none
    match_status: str
    shot_id: int | None = None
    asset_id: int | None = None
    source_start: float | None = None
    source_end: float | None = None
    source_duration: float | None = None
    suggested_in: float | None = None
    suggested_out: float | None = None
    suggested_duration: float | None = None
    duration_status: str | None = None
    duration_warnings: list[str] = []
    product_name: str | None = None
    scene: str | None = None
    action: str | None = None
    match_score: float | None = None
    matched_reasons: list[str] = []
    unmatched_requirements: list[str] = []
    risk_warnings: list[str] = []
    gap_reasons: list[str] = []
    reshoot_recommendation: list[str] = []
    requires_human_confirmation: bool = False
    reused: bool = False
    shot_invalid: bool = False


class EditListSummaryOut(BaseModel):
    total_segments: int
    matched_segments: int
    selected_segments: int
    locked_segments: int
    recommended_segments: int
    gap_segments: int
    risk_segments: int
    target_total_duration_min: float | None = None
    target_total_duration_max: float | None = None
    suggested_total_duration: float
    duplicate_shot_count: int
    allocation_warnings: list[str] = []


class EditListResponse(BaseModel):
    script_id: int
    summary: EditListSummaryOut
    rows: list[EditListRowOut] = []


# ---- 导出 ----


class ScriptExportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    script_project_id: int
    status: str
    export_format: str
    filename: str | None = None
    row_count: int | None = None
    has_file: bool = False
    error_message: str | None = None
    celery_task_id: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
