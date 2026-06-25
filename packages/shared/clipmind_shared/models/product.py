"""PR-03B 产品库模型。

设计要点：
- 素材与产品**多对多**（``asset_product``）：一个素材可含多个产品；``asset.primary_product_id``
  仅表示"默认/主产品"，不代表所有镜头都只含该产品。
- 产品参考图存 ``/app/data/products/{product_id}/images/``，库内只存受控相对路径。
- ``normalized_name`` 供候选匹配（大小写/空格/标点/全角半角/连字符标准化后比对）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, pg_enum, utcnow
from clipmind_shared.models.enums import ProductStatus, TagSource


class Product(Base):
    __tablename__ = "product"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    selling_points: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ProductStatus] = mapped_column(
        pg_enum(ProductStatus, "product_status"), default=ProductStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProductAlias(Base):
    __tablename__ = "product_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(255))
    normalized_alias: Mapped[str] = mapped_column(String(255), index=True)

    __table_args__ = (
        UniqueConstraint("product_id", "normalized_alias", name="uq_product_alias_norm"),
    )


class ProductImage(Base):
    __tablename__ = "product_image"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), index=True
    )
    # 相对 data_dir 的受控路径：products/{product_id}/images/{name}
    image_path: Mapped[str] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssetProduct(Base):
    """素材↔产品多对多关联（人工确认或 AI 候选）。"""

    __tablename__ = "asset_product"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[TagSource] = mapped_column(pg_enum(TagSource, "tag_source"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 候选匹配信息（仅 AI 候选时有意义；人工确认后 active=True）
    match_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("asset_id", "product_id", "source", name="uq_asset_product_src"),
    )
