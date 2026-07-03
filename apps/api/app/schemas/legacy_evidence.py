"""PR-C Gate B 历史使用证据 schema。

弱证据语义（docs/LEGACY_USAGE_EVIDENCE.md）：accept 只代表"该 Asset 很可能曾被
使用过"——次数/来源 Shot/成片均未知；绝不影响 confirmed 使用次数。
路径只暴露 root 显示名 + 相对路径；无任意正则输入。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

RULE_NAME_MAX = 200
PATTERN_MAX = 256
NOTE_MAX = 2000
ACTOR_LABEL_MAX = 120


def _strip(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


# ============================ Rule ============================


class RuleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=RULE_NAME_MAX)
    description: str | None = Field(default=None, max_length=NOTE_MAX)
    source_directory_id: int | None = None
    match_target: str
    match_operator: str
    pattern: str = Field(min_length=1, max_length=PATTERN_MAX)
    case_sensitive: bool = False
    include_present_locations: bool = True
    include_missing_locations: bool = True
    include_historical_locations: bool = True
    priority: int = Field(default=100, ge=0, le=10000)

    @field_validator("name", "pattern")
    @classmethod
    def _strip_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v

    @field_validator("description")
    @classmethod
    def _strip_opt(cls, v: str | None) -> str | None:
        return _strip(v)


class RuleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=RULE_NAME_MAX)
    description: str | None = Field(default=None, max_length=NOTE_MAX)
    source_directory_id: int | None = None
    match_target: str | None = None
    match_operator: str | None = None
    pattern: str | None = Field(default=None, min_length=1, max_length=PATTERN_MAX)
    case_sensitive: bool | None = None
    include_present_locations: bool | None = None
    include_missing_locations: bool | None = None
    include_historical_locations: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)


class RuleOut(BaseModel):
    id: int
    name: str
    description: str | None
    source_directory_id: int | None
    source_directory_name: str | None = None
    match_target: str
    match_operator: str
    pattern: str
    case_sensitive: bool
    include_present_locations: bool
    include_missing_locations: bool
    include_historical_locations: bool
    enabled: bool
    priority: int
    # 语义版本（影响匹配语义的修改 +1；展示字段修改不加）与当前语义指纹
    version: int = 1
    snapshot_hash: str | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    evidence_count: int = 0

    model_config = {"from_attributes": True}


class RuleListResponse(BaseModel):
    items: list[RuleOut]
    total: int


# ============================ Preview / Import ============================


class ImportRequest(BaseModel):
    """preview 与正式导入共用的范围参数。"""

    source_directory_id: int | None = None
    rule_ids: list[int] | None = Field(default=None, max_length=100)
    dry_run: bool = False
    actor_label: str | None = Field(default=None, max_length=ACTOR_LABEL_MAX)


class PreviewSampleOut(BaseModel):
    asset_id: int
    relative_path: str  # 安全相对路径（截断）
    location_status: str
    rule_id: int
    rule_name: str
    matched_component: str
    already_exists: bool


class PreviewOut(BaseModel):
    scanned_location_count: int
    matched_location_count: int
    matched_asset_count: int
    would_create_count: int
    existing_evidence_count: int
    conflict_count: int
    error_count: int
    by_rule: dict[str, int]            # rule_id → 命中的不同 AssetLocation 数
    by_location_status: dict[str, int]  # 位置状态 → 命中的不同 AssetLocation 数
    samples: list[PreviewSampleOut]


class ImportRunOut(BaseModel):
    id: int
    source_directory_id: int | None
    status: str
    dry_run: bool
    location_scope: list[str] | None
    scanned_location_count: int
    matched_location_count: int
    matched_asset_count: int
    created_evidence_count: int
    existing_evidence_count: int
    conflict_count: int
    error_count: int
    error_summary: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ImportRunListResponse(BaseModel):
    items: list[ImportRunOut]
    total: int


# ============================ Evidence / Review ============================


class EvidenceOut(BaseModel):
    id: int
    asset_id: int
    asset_filename: str | None = None
    asset_status: str | None = None
    product_name: str | None = None
    asset_location_id: int | None
    location_relative_path: str | None = None
    location_status: str | None = None
    source_root_name: str | None = None
    rule_id: int | None
    rule_name: str | None = None
    # 证据来源规则的语义版本（快照冻结，不随规则后续修改变化）
    rule_version: int = 1
    evidence_type: str
    matched_target: str
    matched_component: str
    review_status: str
    review_note: str | None
    actor_label: str | None
    first_observed_at: datetime
    last_observed_at: datetime
    observation_count: int
    reviewed_at: datetime | None
    created_at: datetime
    # 正式血缘对照（只读；证据绝不影响它们）
    confirmed_usage_count: int = 0
    has_final_video_usage: bool = False

    model_config = {"from_attributes": True}


class EvidenceListResponse(BaseModel):
    items: list[EvidenceOut]
    total: int
    page: int
    page_size: int


class ReviewActionRequest(BaseModel):
    actor_label: str | None = Field(default=None, max_length=ACTOR_LABEL_MAX)
    note: str | None = Field(default=None, max_length=NOTE_MAX)

    @field_validator("actor_label", "note")
    @classmethod
    def _strip_fields(cls, v: str | None) -> str | None:
        return _strip(v)


class BulkReviewRequest(BaseModel):
    evidence_ids: list[int] = Field(min_length=1, max_length=500)
    actor_label: str | None = Field(default=None, max_length=ACTOR_LABEL_MAX)
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class BulkReviewOut(BaseModel):
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    skipped_ids: list[int] = []


class EvidenceEventOut(BaseModel):
    id: int
    evidence_id: int
    action: str
    before_status: str | None
    after_status: str | None
    actor_label: str | None
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceEventListResponse(BaseModel):
    items: list[EvidenceEventOut]


class AssetLegacySummaryOut(BaseModel):
    """Asset 详情页只读区（历史使用证据）。"""

    asset_id: int
    legacy_usage_state: str = "no_legacy_evidence"
    accepted_count: int = 0
    pending_count: int = 0
    rejected_count: int = 0
    conflict_count: int = 0
    evidences: list[EvidenceOut] = []


class RuleSnapshotOut(BaseModel):
    """证据/运行中保存的规则脱敏快照展示。"""

    rule_id: int | None = None
    name: str | None = None
    match_target: str | None = None
    match_operator: str | None = None
    pattern: str | None = None
    case_sensitive: bool | None = None
    extra: dict[str, Any] | None = None
