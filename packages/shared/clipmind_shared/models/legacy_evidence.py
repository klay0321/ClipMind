"""PR-C Gate B 历史"已使用"路径证据数据模型（以 PostgreSQL 为事实来源）。

四表：
- ``legacy_usage_rule``：可配置路径规则（受控 match_target/operator 白名单,
  **不支持任意正则** —— 无 ReDoS 面）。系统不预置任何公司真实规则,
  真实规则一律经 UI/API 创建。
- ``legacy_usage_import_run``：一次预演/导入运行（进度与错误以 DB 行为事实来源;
  rule_snapshot 只存脱敏业务配置,绝不存绝对路径与媒体内容）。
- ``legacy_usage_evidence``：**弱使用证据,绑定 Asset**（不绑 Shot、不造假成片）。
  接受只代表"该 Asset 很可能曾被使用过,次数/来源 Shot/成片均未知";
  与 final_video_usage 零关联,**绝不影响 confirmed 使用次数**。
  ``evidence_key`` 唯一 ⇒ 重复导入幂等（同规则+同 Asset+同匹配事实一条,
  重复观察只更新 last_observed_at / observation_count,不覆盖人工审核状态）。
- ``legacy_usage_evidence_event``：append-only 审核审计（与状态变化同事务;
  无普通 update/delete;actor_label 为非可信显示名）。

保留语义：规则删除/归档、位置转 historical、素材再移动均**不删除**既有证据 ——
证据属于 Asset 身份,不属于当前路径身份。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, utcnow

RULE_NAME_MAX = 200
RULE_PATTERN_MAX = 256
MATCHED_COMPONENT_MAX = 256
NOTE_MAX = 2000
ACTOR_LABEL_MAX = 120


class LegacyUsageRule(Base):
    __tablename__ = "legacy_usage_rule"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(RULE_NAME_MAX))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 为空 = 适用全部 SourceDirectory；非空 = 只在指定来源应用
    source_directory_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_directory.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # 受控白名单 LEGACY_MATCH_TARGETS / LEGACY_MATCH_OPERATORS（String，免迁移扩展）
    match_target: Mapped[str] = mapped_column(String(32))
    match_operator: Mapped[str] = mapped_column(String(16))
    pattern: Mapped[str] = mapped_column(String(RULE_PATTERN_MAX))
    # NFKC + 分隔符统一 +（大小写无关时）casefold 后的匹配用形态（存储时冻结）
    normalized_pattern: Mapped[str] = mapped_column(String(RULE_PATTERN_MAX))
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)

    # 参与匹配的位置状态范围（历史标记常发生在已移走的位置上，默认全开）
    include_present_locations: Mapped[bool] = mapped_column(Boolean, default=True)
    include_missing_locations: Mapped[bool] = mapped_column(Boolean, default=True)
    include_historical_locations: Mapped[bool] = mapped_column(Boolean, default=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)

    # 语义版本：影响匹配语义的字段（target/operator/pattern/case/来源/位置范围）
    # 任一变化 +1；展示字段（name/description/priority）与 enable/disable/
    # archive/restore 不加版本
    version: Mapped[int] = mapped_column(Integer, default=1)
    # 当前语义指纹 sha256(rule_id + 规范化语义字段, 排序稳定 JSON)；
    # 不含 version/updated_at/描述/展示状态 —— 语义等价 ⇒ 同 hash（改回即幂等）
    snapshot_hash: Mapped[str] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("length(pattern) >= 1", name="rule_pattern_nonempty"),
        Index("ix_legacy_rule_enabled", "enabled"),
    )


class LegacyUsageImportRun(Base):
    __tablename__ = "legacy_usage_import_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 为空 = 全部来源；非空 = 限定来源
    source_directory_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_directory.id", ondelete="SET NULL"), nullable=True
    )
    # 受控 LEGACY_IMPORT_RUN_STATUSES：pending/running/completed/
    # completed_with_errors/failed/cancelled
    status: Mapped[str] = mapped_column(String(32), default="pending")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)

    # 当次参与规则的脱敏快照（业务配置列表；无绝对路径、无媒体内容）
    rule_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # 参与匹配的位置状态范围快照，如 ["present","historical"]
    location_scope: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    scanned_location_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_location_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_asset_count: Mapped[int] = mapped_column(Integer, default=0)
    created_evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    existing_evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    # 截断的错误摘要（绝不含绝对路径）
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_legacy_import_run_status", "status"),
    )


class LegacyUsageEvidence(Base):
    __tablename__ = "legacy_usage_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 证据属于 Asset 身份（CASCADE：Asset 行消亡则证据无宿主；Asset 本身无删除 API）
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), index=True
    )
    # 命中时位置的可空历史引用（位置转 historical/删除不影响证据本体）
    asset_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_location.id", ondelete="SET NULL"), nullable=True
    )
    # 规则删除/归档后证据保留（SET NULL + rule_snapshot 冻结生成时配置）
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("legacy_usage_rule.id", ondelete="SET NULL"), nullable=True, index=True
    )
    import_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("legacy_usage_import_run.id", ondelete="SET NULL"), nullable=True
    )

    # sha256(snapshot_hash|asset_id|match_target|normalized_component) —— 幂等锚。
    # snapshot_hash 覆盖规则语义 ⇒ 同规则同语义幂等；语义变更（新版本）产生
    # 独立证据；语义改回等价则回到原证据（观察数累计）
    evidence_key: Mapped[str] = mapped_column(String(64))
    # 证据来源规则的语义版本（UI 展示；快照冻结，不随规则后续修改变化）
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    # 受控 LEGACY_EVIDENCE_TYPES：directory_marker / filename_marker
    evidence_type: Mapped[str] = mapped_column(String(32))
    matched_target: Mapped[str] = mapped_column(String(32))
    # 必要且长度受限的匹配片段（归一化后；只存相对路径成分，绝不存绝对路径）
    matched_component: Mapped[str] = mapped_column(String(MATCHED_COMPONENT_MAX))
    # 生成时规则脱敏快照
    rule_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # 受控 LEGACY_REVIEW_STATUSES：pending / accepted / rejected / conflict
    review_status: Mapped[str] = mapped_column(String(16), default="pending")
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_label: Mapped[str | None] = mapped_column(String(ACTOR_LABEL_MAX), nullable=True)

    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    observation_count: Mapped[int] = mapped_column(Integer, default=1)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("evidence_key", name="uq_legacy_evidence_key"),
        CheckConstraint("observation_count >= 1", name="evidence_observation_min1"),
        Index("ix_legacy_evidence_review", "review_status"),
        Index("ix_legacy_evidence_asset_review", "asset_id", "review_status"),
    )


class LegacyUsageEvidenceEvent(Base):
    """证据审核审计事件（append-only；与状态变化同事务；无更新/删除接口）。"""

    __tablename__ = "legacy_usage_evidence_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("legacy_usage_evidence.id", ondelete="CASCADE"), index=True
    )
    # 受控 LEGACY_EVIDENCE_EVENT_ACTIONS
    action: Mapped[str] = mapped_column(String(32))
    before_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    after_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor_label: Mapped[str | None] = mapped_column(String(ACTOR_LABEL_MAX), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_legacy_evidence_event_created", "created_at"),
    )
