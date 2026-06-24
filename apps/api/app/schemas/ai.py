"""AI 分析相关响应模型（PR-03A）。

镜头页/素材页展示**真实** AI 状态；parsed_result 为 AI 原始结构化结果（标注"待人工审核"，
人工审核与标签拆解属 PR-03B）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clipmind_shared.models.enums import AIRunStatus, AIShotAnalysisStatus
from pydantic import BaseModel


class AnalyzeAIAcceptedOut(BaseModel):
    asset_id: int
    run_id: int
    status: AIRunStatus
    celery_task_id: str | None = None
    detail: str = "已入队 AI 分析"


class AIAnalysisOut(BaseModel):
    asset_id: int
    has_run: bool
    run_id: int | None = None
    status: AIRunStatus | None = None
    progress: int = 0
    current_step: str | None = None
    total_shots: int = 0
    analyzed_shots: int = 0
    failed_shots: int = 0
    skipped_cached: int = 0
    degraded: bool = False
    provider: str | None = None
    model: str | None = None
    error_message: str | None = None
    celery_task_id: str | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # 该素材当前已有 AI 结果（completed）的镜头数
    analyzed_total: int = 0


class ShotAIOut(BaseModel):
    shot_id: int
    has_analysis: bool
    status: AIShotAnalysisStatus | None = None
    provider: str | None = None
    model: str | None = None
    confidence: float | None = None
    needs_human_review: bool = False
    degraded_reason: str | None = None
    # AI 原始结构化结果（待人工审核；PR-03B 拆解为标签/产品并提供审核）
    result: dict[str, Any] | None = None
    updated_at: datetime | None = None


class AIProviderHealthOut(BaseModel):
    provider: str
    configured: bool
    supports_images: bool | None = None
    max_images: int | None = None
    detail: str = ""


def to_ai_analysis_out(asset_id: int, run, completed_total: int) -> AIAnalysisOut:
    if run is None:
        return AIAnalysisOut(asset_id=asset_id, has_run=False, analyzed_total=completed_total)
    return AIAnalysisOut(
        asset_id=asset_id,
        has_run=True,
        run_id=run.id,
        status=run.status,
        progress=run.progress,
        current_step=run.current_step,
        total_shots=run.total_shots,
        analyzed_shots=run.analyzed_shots,
        failed_shots=run.failed_shots,
        skipped_cached=run.skipped_cached,
        degraded=run.degraded,
        provider=run.provider,
        model=run.model,
        error_message=run.error_message,
        celery_task_id=run.celery_task_id,
        queued_at=run.queued_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        analyzed_total=completed_total,
    )


def to_shot_ai_out(shot_id: int, row) -> ShotAIOut:
    if row is None:
        return ShotAIOut(shot_id=shot_id, has_analysis=False)
    parsed = row.parsed_result or {}
    return ShotAIOut(
        shot_id=shot_id,
        has_analysis=True,
        status=row.status,
        provider=row.provider,
        model=row.model,
        confidence=row.confidence,
        needs_human_review=bool(parsed.get("needs_human_review")),
        degraded_reason=row.degraded_reason,
        result=row.parsed_result,
        updated_at=row.updated_at,
    )
