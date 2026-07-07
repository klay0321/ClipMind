"""VIS-AUTO：视觉嵌入持久化与自动产品候选（docs/VISUAL_RECOGNITION.md）。

- ``visual_media_embedding``：素材海报 / 镜头关键帧 / 产品参考图的视觉向量
  （SigLIP 768 维，L2 归一，cosine）。内容或模型变化通过 (source_sha256,
  provider, model_id) 自然失效；HNSW 索引同时服务以图搜图（后续 PR）。
- ``visual_product_candidate``：自动生成的产品归属候选。候选 ≠ 确认——
  确认仍走 product_media_link(origin=visual_suggestion_confirmed) 人工通道；
  pending 行是派生数据可随时重算置换，dismissed/confirmed 是人工事实必须保留。
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, utcnow

VISUAL_EMBEDDING_DIM = 768  # SigLIP base；fake provider 对齐同维度


class VisualMediaEmbedding(Base):
    """一个视觉目标（asset 海报 / shot 关键帧 / reference 原图）的一份向量。"""

    __tablename__ = "visual_media_embedding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(16))  # asset | shot | reference
    target_id: Mapped[int] = mapped_column(Integer)

    # 算向量所用图片（data 卷相对路径）与其内容指纹（重算防抖）
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    provider: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(128))
    dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(VISUAL_EMBEDDING_DIM), nullable=True
    )

    status: Mapped[str] = mapped_column(String(16), default="completed")  # completed | failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 候选计算水位：本行最近一次候选决策时间与所依据的参考集摘要。
    # 参考图增删/换模型 → 全局 ref_revision 变化 → sweep 发现落后并重算。
    candidates_computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    candidates_ref_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "target_type", "target_id", "provider", "model_id",
            name="uq_vme_target_provider_model",
        ),
        Index("ix_vme_target", "target_type", "target_id"),
        Index("ix_vme_status", "status"),
        Index("ix_vme_ref_revision", "candidates_ref_revision"),
    )


class VisualProductCandidate(Base):
    """自动视觉候选：素材/镜头 × 产品 的相似度提名（人工确认前不构成事实）。"""

    __tablename__ = "visual_product_candidate"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(16))  # asset | shot
    target_id: Mapped[int] = mapped_column(Integer)
    family_id: Mapped[int] = mapped_column(
        ForeignKey("product_family.id", ondelete="CASCADE")
    )

    score: Mapped[float] = mapped_column(Float)
    margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str] = mapped_column(String(16))  # candidate | ambiguous
    best_reference_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_reference_asset.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(128))
    thresholds: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 判定阈值快照

    # pending（待人工）| dismissed（人工拒绝，重算不复活）|
    # confirmed（已确认，回填 link）| stale（目标内容变化后的历史行）
    status: Mapped[str] = mapped_column(String(16), default="pending")
    source_embedding_id: Mapped[int | None] = mapped_column(
        ForeignKey("visual_media_embedding.id", ondelete="CASCADE"), nullable=True
    )
    confirmed_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_media_link.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        # 同一目标对同一产品至多一条待处理候选；dismissed/confirmed 不占位
        Index(
            "uq_vpc_pending_target_family",
            "target_type", "target_id", "family_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_vpc_target", "target_type", "target_id"),
        Index("ix_vpc_family_status", "family_id", "status"),
        Index("ix_vpc_status", "status"),
    )
