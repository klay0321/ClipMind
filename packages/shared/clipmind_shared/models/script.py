"""PR-05 脚本匹配数据模型（以 PostgreSQL 为事实来源）。

三表：
- ``script_project``：粘贴/上传的脚本项目（原文 + 归一文本 + 内容哈希 + 拆段状态）。
- ``script_segment``：脚本段落（顺序、文案、画面需求、结构化要求、产品、目标时长）。
  ``current_generation`` + ``locked_shot_id`` 为 Gate B 的"单段重匹配原子代次替换"与
  "人工锁定不被重匹配覆盖"提供数据基础（Gate A 仅建结构，不运行匹配）。
- ``script_shot_candidate``：每段每代次的候选镜头（评分 + 规则派生理由/不匹配/风险）。
  Gate A 仅建结构，**不写入候选**（Gate B 复用 Hybrid Search / Description Match 填充）。

关键约束：
- ``(script_project_id, order_index)`` 唯一：项目内段落顺序唯一。
- ``(script_segment_id, generation, shot_id)`` 唯一：同段同代次内镜头唯一；新代次不覆盖旧代次。
- ``generation >= 1``、``order_index >= 0``、``rank >= 0``。
- 删除项目级联删除段落与候选；删除候选**不触碰** ``locked_shot_id``（人工锁定在段落上）。
- ``locked_shot_id`` / ``product_id`` 用 ``SET NULL``：被引用的 Shot/Product 删除时清空引用而非删段。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.constants import SCRIPT_PARSE_SCHEMA_VERSION
from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import ScriptParseStatus, ScriptStatus


class ScriptProject(Base):
    __tablename__ = "script_project"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    raw_script: Mapped[str] = mapped_column(Text)
    normalized_script: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 内容哈希：同一脚本重复创建据此幂等复用。唯一约束在 DB 层兜底并发竞态
    # （检查-插入之间的并发由 IntegrityError 捕获后复用既有项目）。PG 下多 NULL 不冲突。
    script_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    source_format: Mapped[str] = mapped_column(String(16), default="paste")  # paste/txt/md/docx

    status: Mapped[ScriptStatus] = mapped_column(
        pg_enum(ScriptStatus, "script_status"), default=ScriptStatus.DRAFT
    )
    parse_status: Mapped[ScriptParseStatus] = mapped_column(
        pg_enum(ScriptParseStatus, "script_parse_status"),
        default=ScriptParseStatus.PENDING,
    )
    parser_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser_warnings: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    result_schema_version: Mapped[int] = mapped_column(
        Integer, default=SCRIPT_PARSE_SCHEMA_VERSION
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ScriptSegment(Base):
    __tablename__ = "script_segment"

    id: Mapped[int] = mapped_column(primary_key=True)
    script_project_id: Mapped[int] = mapped_column(
        ForeignKey("script_project.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)

    segment_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    visual_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)

    target_duration_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_duration_max: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 产品硬约束（Gate B 用）；产品删除时清空引用，不删段
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("product.id", ondelete="SET NULL"), nullable=True
    )

    # 结构化画面需求（scenes/actions/shot_types/marketing_uses/people/objects/quality/selling_points/must_include 等）
    structured_requirements: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    negative_terms: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    excluded_risks: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    allow_similar_scene: Mapped[bool] = mapped_column(default=True)
    allow_similar_action: Mapped[bool] = mapped_column(default=True)

    # 重匹配代次：候选随代次原子替换（Gate B）
    current_generation: Mapped[int] = mapped_column(Integer, default=1)
    # 人工选择的镜头（Gate B）：当前人工选中的 shot；区别于"锁定"。
    # 选择 = 当前选中；锁定 = 后续自动匹配不得覆盖。镜头删除时清空（SET NULL）。
    selected_shot_id: Mapped[int | None] = mapped_column(
        ForeignKey("shot.id", ondelete="SET NULL"), nullable=True
    )
    # 人工锁定的镜头：重匹配不覆盖；镜头删除时清空（SET NULL）
    locked_shot_id: Mapped[int | None] = mapped_column(
        ForeignKey("shot.id", ondelete="SET NULL"), nullable=True
    )
    # 乐观锁版本：人工编辑/锁定并发保护（Gate B 重匹配须校验）
    lock_version: Mapped[int] = mapped_column(Integer, default=0)

    # 上次匹配结果摘要（Gate B；规则派生，绝不由 LLM 编造）：
    # - match_status：pending（从未匹配）/ matched（有候选）/ gap（匹配后真实无结果）/ degraded（降级匹配）。
    # - match_summary(JSONB)：best_score / candidate_count / gap_reasons / reshoot_recommendation /
    #   requires_human_confirmation / degraded / generation / match_token（幂等）等。
    # - matched_at：上次匹配完成时刻（NULL=从未匹配，用于区分 pending 与真实 gap）。
    match_status: Mapped[str] = mapped_column(String(16), default="pending")
    match_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    matched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    parser_warnings: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # 候选是否已过期（段落被编辑后置 true，提示需重匹配；Gate A 不自动重匹配）
    candidates_stale: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "script_project_id", "order_index", name="uq_script_segment_project_order"
        ),
        CheckConstraint("order_index >= 0", name="order_index_nonneg"),
        CheckConstraint("current_generation >= 1", name="current_generation_min1"),
    )


class ScriptShotCandidate(Base):
    __tablename__ = "script_shot_candidate"

    id: Mapped[int] = mapped_column(primary_key=True)
    script_segment_id: Mapped[int] = mapped_column(
        ForeignKey("script_segment.id", ondelete="CASCADE"), index=True
    )
    generation: Mapped[int] = mapped_column(Integer)
    shot_id: Mapped[int] = mapped_column(ForeignKey("shot.id", ondelete="CASCADE"))

    rank: Mapped[int] = mapped_column(Integer, default=0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    semantic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    lexical_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    tag_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    product_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_bonus: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_penalty: Mapped[float | None] = mapped_column(Float, nullable=True)

    matched_reasons: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    unmatched_requirements: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    risk_warnings: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "script_segment_id", "generation", "shot_id",
            name="uq_script_candidate_seg_gen_shot",
        ),
        CheckConstraint("generation >= 1", name="candidate_generation_min1"),
        CheckConstraint("rank >= 0", name="candidate_rank_nonneg"),
        Index("ix_script_candidate_seg_gen", "script_segment_id", "generation"),
    )
