"""PR-04 检索文档模型（语义检索的事实来源投影）。

一条 ShotSearchDocument 对应一个 (shot_id, shot_generation) 的"当前有效"检索文档：
- 文档内容来自**有效结果**（confirmed/modified 未 stale → 人工；否则 → 最新成功 AI；
  rejected/unable → 保留记录但 is_searchable=false）；
- ``embedding`` 为 ``vector(384)``（multilingual-e5-small，L2 归一，cosine 检索）；
- 嵌入身份（provider/model/revision/dimension/version）+ 文档哈希 + 模板版本共同决定幂等：
  任一变化都重嵌，绝不混用不同模型/维度的向量；
- 重拆镜头 → 旧 shot 级联删除 → 旧文档随之清理（与 ai_shot_analysis/shot_tag 一致）。

pgvector 的 SQLAlchemy ``Vector`` 类型以文本形式绑定/解析，无需连接级 register_vector；
但 ``vector``/``pg_trgm`` 扩展须在建表/建索引前存在（迁移 0007 与测试 conftest 负责创建）。
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import SearchDocumentStatus, SearchEmbeddingStatus

# 向量维度固定（multilingual-e5-small）。换模型/维度需独立迁移 + 全量重嵌。
EMBEDDING_DIM = 384

# HNSW 默认参数（cosine）。小到中等规模够用；调参需基准与文档，勿盲目调大。
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64


class ShotSearchDocument(Base):
    __tablename__ = "shot_search_document"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 唯一约束 (shot_id, shot_generation) 即覆盖 shot_id 前缀查找，不再单建 shot_id 索引
    shot_id: Mapped[int] = mapped_column(ForeignKey("shot.id", ondelete="CASCADE"))
    shot_generation: Mapped[int] = mapped_column(Integer)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"))

    # 有效结果来源与溯源
    effective_source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # human | ai
    review_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_ai_analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_shot_analysis.id", ondelete="SET NULL"), nullable=True
    )
    source_review_state_id: Mapped[int | None] = mapped_column(
        ForeignKey("shot_review_state.id", ondelete="SET NULL"), nullable=True
    )
    # 人工来源时记录建档所依据审核行的 lock_version；审核内容/产品/状态/stale 任一变化都会
    # 使 lock_version 自增（review_service.apply_review），sweeper 据此检测漏发钩子的内容漂移。
    source_review_lock_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 文档内容
    search_document: Mapped[str | None] = mapped_column(Text, nullable=True)         # 自然语言（供嵌入/展示）
    normalized_document: Mapped[str | None] = mapped_column(Text, nullable=True)     # 归一化（供 pg_trgm）
    search_document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 向量与嵌入身份
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_model_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalization_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 状态机（文档层与嵌入层正交）
    document_status: Mapped[SearchDocumentStatus] = mapped_column(
        pg_enum(SearchDocumentStatus, "search_document_status"),
        default=SearchDocumentStatus.PENDING,
    )
    embedding_status: Mapped[SearchEmbeddingStatus] = mapped_column(
        pg_enum(SearchEmbeddingStatus, "search_embedding_status"),
        default=SearchEmbeddingStatus.PENDING,
    )
    # 便捷去规范化：= (document_status == indexed)，由索引器维护；非向量召回的唯一门控
    is_searchable: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        # 同一 (shot, generation) 至多一条检索文档
        UniqueConstraint("shot_id", "shot_generation", name="uq_search_doc_shot_gen"),
        Index("ix_ssd_asset_id", "asset_id"),
        Index("ix_ssd_document_status", "document_status"),
        Index("ix_ssd_embedding_status", "embedding_status"),
        Index("ix_ssd_is_searchable", "is_searchable"),
        Index("ix_ssd_doc_hash", "search_document_hash"),
        Index("ix_ssd_embedding_version", "embedding_version"),
        Index("ix_ssd_source_ai", "source_ai_analysis_id"),
        Index("ix_ssd_source_review", "source_review_state_id"),
        # 词法召回：归一化文档 trigram（pg_trgm）
        Index(
            "ix_ssd_norm_trgm",
            "normalized_document",
            postgresql_using="gin",
            postgresql_ops={"normalized_document": "gin_trgm_ops"},
        ),
        # 向量召回：HNSW + cosine
        Index(
            "ix_ssd_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": HNSW_M, "ef_construction": HNSW_EF_CONSTRUCTION},
        ),
    )


class AssetSearchDocument(Base):
    """P2a 素材级检索文档：整条视频/图片进入统一搜索。

    与 ShotSearchDocument 同构（同一嵌入身份/幂等/状态机语义），差异：
    - 目标是 Asset（asset_id 唯一），无代次维度；
    - media_kind='image' 时文档来自 asset_image_analysis 的解析结果；
      media_kind='video' 时文档为该素材当前代次 ready 镜头有效文档的聚合
      （聚合模板版本独立于镜头模板版本记录）；
    - 无审核轴引用（图片打标暂不进人工审核；视频聚合的审核语义在镜头层）。
    """

    __tablename__ = "asset_search_document"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), unique=True
    )
    # 冗余媒体类型（与 asset.media_kind 一致，检索过滤免 join 判定）
    media_kind: Mapped[str] = mapped_column(String(8))

    # 来源溯源：图片 → asset_image_analysis；视频聚合 → 无单一来源（保持 NULL）
    effective_source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ai | aggregate
    source_image_analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_image_analysis.id", ondelete="SET NULL"), nullable=True
    )
    # 视频聚合幂等：参与聚合的 (shot_id, doc hash) 集合指纹，镜头文档变化即重建
    aggregate_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    search_document: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_document: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_model_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalization_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    document_status: Mapped[SearchDocumentStatus] = mapped_column(
        pg_enum(SearchDocumentStatus, "search_document_status"),
        default=SearchDocumentStatus.PENDING,
    )
    embedding_status: Mapped[SearchEmbeddingStatus] = mapped_column(
        pg_enum(SearchEmbeddingStatus, "search_embedding_status"),
        default=SearchEmbeddingStatus.PENDING,
    )
    is_searchable: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        Index("ix_asd_media_kind", "media_kind"),
        Index("ix_asd_document_status", "document_status"),
        Index("ix_asd_embedding_status", "embedding_status"),
        Index("ix_asd_is_searchable", "is_searchable"),
        Index(
            "ix_asd_norm_trgm",
            "normalized_document",
            postgresql_using="gin",
            postgresql_ops={"normalized_document": "gin_trgm_ops"},
        ),
        Index(
            "ix_asd_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": HNSW_M, "ef_construction": HNSW_EF_CONSTRUCTION},
        ),
    )
