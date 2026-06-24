"""PR-03A AI 分析数据模型（以 PostgreSQL 为事实来源）。

三表：
- ``ai_analysis_run``：素材级 AI 分析运行（仿 ``MediaProcessingRun``）。部分唯一索引
  ``uq_active_ai_run`` 保证同一素材同一时刻至多一个活动运行（queued/running）。
- ``ai_shot_analysis``：每个镜头当前的 AI 结构化结果（每 shot 一行，``shot_id`` 唯一）。
  结构化 JSON 存 ``parsed_result``，**本 PR 不拆解为标签/产品**（PR-03B）。
  ``input_fingerprint`` 用于缓存去重：相同输入命中已 completed 的分析则跳过、不重复计费。
- ``ai_call_log``：每次外部 provider 调用的**脱敏台账**（tokens/成本/耗时/状态/错误码）。
  不含密钥与敏感原文，供成本归因与排障；shot/run 删除后仍保留（``SET NULL``）。

边界：PR-03A 不写 Shot 的 AI 字段（description/quality_score/risk_level/review_status），
不建 pgvector 向量列——留待 PR-03B / PR-04。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.constants import AI_SCHEMA_VERSION
from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import (
    AICallStatus,
    AIRunStatus,
    AIShotAnalysisStatus,
)


class AIAnalysisRun(Base):
    __tablename__ = "ai_analysis_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 与 MediaProcessingRun 一致：用 UUID 作为对外/文件命名稳定标识
    run_uuid: Mapped[str] = mapped_column(String(36), unique=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), index=True
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[AIRunStatus] = mapped_column(
        pg_enum(AIRunStatus, "ai_run_status"), default=AIRunStatus.QUEUED
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    current_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total_shots: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_shots: Mapped[int] = mapped_column(Integer, default=0)
    failed_shots: Mapped[int] = mapped_column(Integer, default=0)
    skipped_cached: Mapped[int] = mapped_column(Integer, default=0)
    # 本次运行是否发生过能力降级（如 provider 不支持图片）
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)

    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=AI_SCHEMA_VERSION)
    # 启动时探测/缓存到的 ProviderCapabilities 快照
    capabilities_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        # 每素材同一时刻至多一个活动 AI 运行（queued/running）——数据库层防重
        Index(
            "uq_active_ai_run",
            "asset_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )


class AIShotAnalysis(Base):
    __tablename__ = "ai_shot_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 每个镜头至多一行"当前结果"（重新分析时 upsert；镜头被重检测删除则随之级联删除）
    shot_id: Mapped[int] = mapped_column(
        ForeignKey("shot.id", ondelete="CASCADE"), unique=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_analysis_run.id", ondelete="SET NULL"), nullable=True
    )
    # 反规范化便于按素材聚合查询
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), index=True
    )

    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=AI_SCHEMA_VERSION)

    # 输入指纹：相同输入（帧内容+模型+prompt+schema+参数）命中已 completed 则跳过
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    input_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # AI 结构化结果（遵循 shot_analysis JSON Schema）；缺字段留空不编造
    parsed_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # 脱敏截断的原始响应（排障用；不含密钥/敏感原文）
    raw_response_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[AIShotAnalysisStatus] = mapped_column(
        pg_enum(AIShotAnalysisStatus, "ai_shot_analysis_status"),
        default=AIShotAnalysisStatus.PENDING,
    )
    degraded_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AICallLog(Base):
    __tablename__ = "ai_call_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    # run/shot/asset 删除后台账仍保留（成本归因不可丢）
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_analysis_run.id", ondelete="SET NULL"), nullable=True
    )
    shot_id: Mapped[int | None] = mapped_column(
        ForeignKey("shot.id", ondelete="SET NULL"), nullable=True
    )
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset.id", ondelete="SET NULL"), nullable=True
    )

    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    method: Mapped[str] = mapped_column(String(64))  # 如 analyze_frames
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    input_images: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    est_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[AICallStatus] = mapped_column(pg_enum(AICallStatus, "ai_call_status"))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_ai_call_log_asset_id", "asset_id"),
        Index("ix_ai_call_log_created_at", "created_at"),
    )
