"""AAP：批量分析与全局处理概览 schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BatchAnalyzeIn(BaseModel):
    """批量分析请求：显式 asset_ids 或按源目录筛选，二者至少给一个。

    stages：shots=拆镜头（对无可用镜头的视频）；ai=AI 打标（对有可用镜头
    且存在未打标镜头的视频）。绝不隐式全库：无任何条件时 422。
    """

    asset_ids: list[int] | None = None
    source_directory_id: int | None = None
    stages: list[Literal["shots", "ai"]] = Field(default_factory=lambda: ["shots"])
    max_items: int = Field(200, ge=1, le=500)


class BatchAnalyzeOut(BaseModel):
    matched: int
    enqueued_shots: int
    enqueued_ai: int
    skipped_active: int        # 已有活动运行（幂等跳过）
    skipped_ineligible: int    # 不符合条件（图片/缺源/无待处理内容）
    truncated: bool = False    # 匹配数超过 max_items，仅处理前 max_items


class QueueCounts(BaseModel):
    queued: int
    running: int


class ProcessingTotals(BaseModel):
    videos_total: int
    videos_with_shots: int
    shots_ready: int
    shots_ai_labeled: int
    images_total: int
    searchable_docs: int


class ProcessingConfigOut(BaseModel):
    auto_analyze_on_scan: bool
    auto_ai_after_shots: bool
    scan_interval_minutes: int
    ai_daily_budget: float
    ai_spent_today: float


class ProcessingOverviewOut(BaseModel):
    scan: QueueCounts
    shots: QueueCounts
    ai: QueueCounts
    totals: ProcessingTotals
    config: ProcessingConfigOut
