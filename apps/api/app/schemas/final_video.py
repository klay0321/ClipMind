"""PR-B 最终成片 / 使用血缘 schema。

- 使用次数一律为派生统计（实时聚合），schema 中没有任何可写的 usage_count 字段。
- evidence_summary / evidence_refs 只承载脱敏受控信息；绝不暴露服务器绝对路径。
- 手工创建 Usage 仅允许 evidence_method=manual；clipmind_project 只能由
  propose-from-project 产生；其余证据来源为后续 PR 预留，本阶段不得伪造。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clipmind_shared.models.enums import FinalVideoStatus, FinalVideoUsageStatus
from pydantic import BaseModel, Field, field_validator

from app.schemas.shot import ShotOut

TITLE_MAX = 255
DESC_MAX = 2000
VERSION_LABEL_MAX = 64
ACTOR_LABEL_MAX = 120
NOTE_MAX = 2000
EVIDENCE_SUMMARY_MAX = 2000

# PATCH /final-videos 允许写入的状态（archived 只能走 archive 端点）
PATCHABLE_FINAL_VIDEO_STATUSES: tuple[FinalVideoStatus, ...] = (
    FinalVideoStatus.DRAFT,
    FinalVideoStatus.READY,
    FinalVideoStatus.COMPLETED,
)


def _strip(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


# ============================ Final Video ============================


class FinalVideoCreateRequest(BaseModel):
    asset_id: int
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESC_MAX)
    version_label: str | None = Field(default=None, max_length=VERSION_LABEL_MAX)
    project_id: int | None = None
    script_project_id: int | None = None
    status: FinalVideoStatus = FinalVideoStatus.DRAFT
    completed_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def _title_strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        return v

    @field_validator("description", "version_label")
    @classmethod
    def _optional_strip(cls, v: str | None) -> str | None:
        return _strip(v)

    @field_validator("status")
    @classmethod
    def _status_not_archived(cls, v: FinalVideoStatus) -> FinalVideoStatus:
        if v not in PATCHABLE_FINAL_VIDEO_STATUSES:
            raise ValueError("创建时状态只能为 draft/ready/completed（归档走 archive 接口）")
        return v


class FinalVideoUpdateRequest(BaseModel):
    """PATCH：仅更新显式提供的字段；project_id/script_project_id 传 null 表示解绑。"""

    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESC_MAX)
    version_label: str | None = Field(default=None, max_length=VERSION_LABEL_MAX)
    project_id: int | None = None
    script_project_id: int | None = None
    status: FinalVideoStatus | None = None
    completed_at: datetime | None = None

    @field_validator("title", "description", "version_label")
    @classmethod
    def _strip_fields(cls, v: str | None) -> str | None:
        return _strip(v)

    @field_validator("status")
    @classmethod
    def _status_not_archived(cls, v: FinalVideoStatus | None) -> FinalVideoStatus | None:
        if v is not None and v not in PATCHABLE_FINAL_VIDEO_STATUSES:
            raise ValueError("状态只能改为 draft/ready/completed（归档/恢复走专用接口）")
        return v


class FinalVideoUsageStatsOut(BaseModel):
    """成片的血缘统计（派生值，实时聚合）。"""

    source_shot_count: int = 0   # 关系总数（含各状态）
    confirmed_count: int = 0
    proposed_count: int = 0
    suspected_count: int = 0
    rejected_count: int = 0
    revoked_count: int = 0


class FinalVideoOut(BaseModel):
    id: int
    asset_id: int
    project_id: int | None
    script_project_id: int | None
    title: str
    description: str | None
    version_label: str | None
    status: FinalVideoStatus
    completed_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime

    # 便利展示字段（service 填充；不暴露路径）
    asset_filename: str | None = None
    asset_duration: float | None = None
    asset_has_poster: bool = False
    project_name: str | None = None
    script_project_name: str | None = None
    usage_stats: FinalVideoUsageStatsOut = FinalVideoUsageStatsOut()

    model_config = {"from_attributes": True}


class FinalVideoListResponse(BaseModel):
    items: list[FinalVideoOut]
    total: int
    page: int
    page_size: int


# ============================ Usage ============================


class UsageCreateRequest(BaseModel):
    """手工添加候选引用（仅 manual；创建即 proposed，确认另走 confirm）。"""

    source_shot_id: int
    evidence_method: str = "manual"
    evidence_summary: str | None = Field(default=None, max_length=EVIDENCE_SUMMARY_MAX)
    confidence: float | None = Field(default=None, ge=0, le=1)
    actor_label: str | None = Field(default=None, max_length=ACTOR_LABEL_MAX)
    review_note: str | None = Field(default=None, max_length=NOTE_MAX)

    @field_validator("evidence_summary", "actor_label", "review_note")
    @classmethod
    def _strip_fields(cls, v: str | None) -> str | None:
        return _strip(v)

    @field_validator("evidence_method")
    @classmethod
    def _manual_only(cls, v: str) -> str:
        if v != "manual":
            raise ValueError(
                "手工添加只允许 evidence_method=manual；"
                "clipmind_project 由 propose-from-project 生成，其余来源本阶段未实现"
            )
        return v


class UsageUpdateRequest(BaseModel):
    evidence_summary: str | None = Field(default=None, max_length=EVIDENCE_SUMMARY_MAX)
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_note: str | None = Field(default=None, max_length=NOTE_MAX)
    actor_label: str | None = Field(default=None, max_length=ACTOR_LABEL_MAX)

    @field_validator("evidence_summary", "review_note", "actor_label")
    @classmethod
    def _strip_fields(cls, v: str | None) -> str | None:
        return _strip(v)


class UsageActionRequest(BaseModel):
    """confirm / reject / revoke / restore-proposal 的可选说明。"""

    actor_label: str | None = Field(default=None, max_length=ACTOR_LABEL_MAX)
    note: str | None = Field(default=None, max_length=NOTE_MAX)

    @field_validator("actor_label", "note")
    @classmethod
    def _strip_fields(cls, v: str | None) -> str | None:
        return _strip(v)


class UsageOut(BaseModel):
    id: int
    final_video_id: int
    source_shot_id: int
    source_asset_id: int
    source_shot_generation: int | None
    status: FinalVideoUsageStatus
    evidence_method: str
    confidence: float | None
    evidence_summary: str | None
    evidence_refs: dict[str, Any] | None
    confirmed_at: datetime | None
    rejected_at: datetime | None
    revoked_at: datetime | None
    actor_label: str | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime

    # 便利展示字段（service 填充）
    shot: ShotOut | None = None
    source_asset_filename: str | None = None
    occurrence_count: int = 0
    product_name: str | None = None  # 镜头人工确认产品，缺省回退素材主产品

    model_config = {"from_attributes": True}


class UsageListResponse(BaseModel):
    items: list[UsageOut]
    total: int


# ============================ Occurrence ============================


class OccurrenceCreateRequest(BaseModel):
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    final_start_ms: int = Field(ge=0)
    final_end_ms: int = Field(gt=0)


class OccurrenceUpdateRequest(BaseModel):
    source_start_ms: int | None = Field(default=None, ge=0)
    source_end_ms: int | None = Field(default=None, gt=0)
    final_start_ms: int | None = Field(default=None, ge=0)
    final_end_ms: int | None = Field(default=None, gt=0)


class OccurrenceOut(BaseModel):
    id: int
    usage_id: int
    occurrence_index: int
    source_start_ms: int
    source_end_ms: int
    final_start_ms: int
    final_end_ms: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OccurrenceListResponse(BaseModel):
    items: list[OccurrenceOut]


# ============================ Project proposal ============================


class ProposeFromProjectRequest(BaseModel):
    actor_label: str | None = Field(default=None, max_length=ACTOR_LABEL_MAX)

    @field_validator("actor_label")
    @classmethod
    def _strip_fields(cls, v: str | None) -> str | None:
        return _strip(v)


class ProposeFromProjectOut(BaseModel):
    """幂等生成结果统计（重跑不会覆盖人工 confirmed/rejected/revoked）。"""

    created: int = 0              # 新建 proposed
    existing: int = 0             # 已有关系（任何状态），跳过
    skipped_unavailable: int = 0  # 镜头/素材不可用，跳过
    conflicts: int = 0            # 与成片自引用等冲突，跳过
    segments_scanned: int = 0     # 扫描的脚本段落数
    created_usage_ids: list[int] = []


# ============================ 事件 / 统计 ============================


class UsageEventOut(BaseModel):
    id: int
    usage_id: int
    action: str
    before_status: str | None
    after_status: str | None
    actor_label: str | None
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UsageEventListResponse(BaseModel):
    items: list[UsageEventOut]


class FinalVideoBriefOut(BaseModel):
    """Shot 使用统计里的成片引用（仅 confirmed 引用出现在此列表）。"""

    final_video_id: int
    title: str
    status: FinalVideoStatus
    confirmed_at: datetime | None


class ShotUsageSummaryOut(BaseModel):
    shot_id: int
    confirmed_usage_count: int = 0
    proposed_count: int = 0
    suspected_count: int = 0
    last_used_at: datetime | None = None
    final_videos: list[FinalVideoBriefOut] = []


class ShotUsageCountOut(BaseModel):
    """批量轻量统计（镜头卡片徽标用，避免 N+1）。"""

    shot_id: int
    confirmed_usage_count: int = 0
    proposed_count: int = 0


class ShotUsageCountsResponse(BaseModel):
    items: list[ShotUsageCountOut]


class AssetUsageSummaryOut(BaseModel):
    asset_id: int
    total_shots: int = 0                 # 当前 ready 镜头数
    used_shot_count: int = 0             # confirmed 使用次数 >0 的镜头数
    never_used_shot_count: int = 0
    distinct_final_video_count: int = 0  # 引用过本素材镜头的去重成片数（confirmed）
    usage_distribution: dict[str, int] = {}  # {"0":n, "1":m, "2":k, ...}
    last_used_at: datetime | None = None
    # PR-C Gate B：历史弱证据（独立展示，绝不并入上面的 confirmed 统计）
    confirmed_usage_count: int = 0                # 本素材 confirmed 使用总次数
    accepted_legacy_evidence_count: int = 0
    pending_legacy_evidence_count: int = 0
    rejected_legacy_evidence_count: int = 0
    conflict_legacy_evidence_count: int = 0
    legacy_usage_state: str = "no_legacy_evidence"
    usage_count_known: bool = False               # = confirmed_usage_count > 0
    final_video_known: bool = False               # = distinct_final_video_count > 0


class UsageWithOccurrencesOut(UsageOut):
    occurrences: list[OccurrenceOut] = []


class FinalVideoLineageOut(BaseModel):
    """成片血缘全景（详情页一次拉取）。"""

    final_video: FinalVideoOut
    usages: list[UsageWithOccurrencesOut]
