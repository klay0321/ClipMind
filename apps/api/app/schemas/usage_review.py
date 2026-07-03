"""PR-D 统一使用记录中心 schema（展示统一、事实分离）。

冻结原则（docs/USAGE_REVIEW_CENTER.md）：
- ReviewItemOut 是**纯输出模型**——不存在把两类记录混在一起的事实表；
- confirmed lineage 永远高于 legacy evidence；accepted legacy 绝不显示成 confirmed；
- 两类计数并列展示、**绝不相加为"总使用次数"**；正式次数只来自 confirmed
  FinalVideoUsage；legacy 行 shot_id / final_video_id 恒为 null（不造占位对象）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ITEM_TYPES = ("final_video_usage", "legacy_usage_evidence")
REVIEW_GROUPS = (
    "needs_review", "accepted_or_confirmed", "rejected", "conflict", "revoked",
)
SOURCE_STRENGTHS = (
    "confirmed_lineage",
    "manual_proposed_lineage",
    "project_proposed_lineage",
    "suspected_lineage",
    "accepted_legacy_evidence",
    "pending_legacy_evidence",
    "rejected_or_conflict",
)

# 动作白名单（按 item_type；混合类型批次一律 422）
FORMAL_BULK_ACTIONS = ("confirm", "reject", "revoke", "restore_proposal")
LEGACY_BULK_ACTIONS = ("accept", "reject", "mark_conflict", "reset")

ItemType = Literal["final_video_usage", "legacy_usage_evidence"]


class ReviewItemOut(BaseModel):
    """统一审核条目（只读投影；available_actions 由原状态机导出）。"""

    item_type: ItemType
    item_id: int
    review_group: str
    source_strength: str
    review_status: str                     # 原始领域状态原样透出
    asset_id: int | None = None
    asset_filename: str | None = None
    shot_id: int | None = None             # legacy 恒 null（证据没有 Shot）
    shot_sequence_no: int | None = None
    final_video_id: int | None = None      # legacy 恒 null（证据没有成片）
    final_video_title: str | None = None
    product: str | None = None
    source_label: str | None = None        # 证据来源（方法/规则名 vN）
    evidence_summary: str | None = None
    created_at: datetime
    last_observed_at: datetime | None = None
    reviewed_at: datetime | None = None
    available_actions: list[str] = []


class ReviewListResponse(BaseModel):
    items: list[ReviewItemOut]
    total: int
    page: int
    page_size: int


class FormalSummaryOut(BaseModel):
    confirmed: int = 0
    proposed: int = 0
    suspected: int = 0
    rejected: int = 0
    revoked: int = 0


class LegacySummaryOut(BaseModel):
    pending: int = 0
    accepted: int = 0
    rejected: int = 0
    conflict: int = 0


class ReviewSummaryOut(BaseModel):
    """两组计数并列；needs_review_total 是审核工作量口径，不是使用次数。

    刻意不存在 total_used_count —— confirmed 与 accepted_legacy 永远不相加。
    """

    formal: FormalSummaryOut
    legacy: LegacySummaryOut
    needs_review_total: int = 0


class ReviewItemDetailOut(BaseModel):
    """详情：统一头 + 原始领域数据 + 各自事件时间线（不拼成单一事件对象）。"""

    item: ReviewItemOut
    # 原始领域对象（formal=UsageWithOccurrences 形状；legacy=EvidenceOut 形状）
    formal_usage: dict[str, Any] | None = None
    legacy_evidence: dict[str, Any] | None = None
    # 事件时间线（各自结构原样；item_type 已区分语义）
    events: list[dict[str, Any]] = []


class BulkItemRef(BaseModel):
    item_type: ItemType
    item_id: int


class BulkReviewRequest(BaseModel):
    items: list[BulkItemRef] = Field(min_length=1, max_length=500)
    action: str
    actor_label: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("actor_label", "note")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class BulkItemResult(BaseModel):
    item_type: ItemType
    item_id: int
    outcome: Literal["succeeded", "skipped", "failed"]
    reason: str | None = None


class BulkReviewOut(BaseModel):
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[BulkItemResult] = []
