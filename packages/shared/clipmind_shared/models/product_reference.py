"""PR-A2 Gate A：产品参考图库（ProductReferenceAsset）。

设计（见 .local/pr-a2a/reference-media-audit.md，脱敏审计决策，verdict=new_reference_asset）：
- **新建独立表**，不改造旧 `product_image`（后者硬 FK 专属旧扁平 `product`）。
- 绑定 Family / Variant / SKU **单目标**（单表多目标 + CHECK 恰好一个非空），沿用
  `ProductCatalogAlias` 已验证范式；旧 `product_image` 与旧 `/api/products` 零改动。
- DB 只存 `data_dir` 下**受控 POSIX 相对路径**（`image_path`/`thumbnail_path`），
  绝不存本机绝对路径 / NAS 管理员路径（复用 storage.relpath + safe_join 校验）。
- 稳定身份 = 自增 `id`（PK，永不变，API/前端一律用 id 引用，不用路径）；
  `sha256` 为内容身份（**本阶段实算，用于同目标重复检测**）；
  `perceptual_hash` 为占位（**本阶段不计算、不接视觉模型**）。
- 原图 + 缩略图两套文件；缩略 best-effort（`thumbnail_path` 可空，前端回退原图）。
- `angle`/`state`/`quality_status`/`media_type` 均 String 列 + service 白名单（免迁移扩展）；
  `quality_status` 由**人工标记**，不伪造 AI 检测。软归档（`archived_at`）优先物理删除。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from clipmind_shared.db.base import Base, utcnow


class ProductReferenceAsset(Base):
    """产品参考图资产（绑定 Family / Variant / SKU 单目标）。

    人工上传/引入的多角度产品参考图，用于建立产品资料与后续识别基线。
    **本阶段不做自动产品识别、不接视觉模型**；`sha256` 实算供重复检测，
    `perceptual_hash` 仅占位。删除逻辑只操作 `data_dir` 派生文件，绝不触及只读源。
    """

    __tablename__ = "product_reference_asset"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_family.id", ondelete="CASCADE"), nullable=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variant.id", ondelete="CASCADE"), nullable=True
    )
    sku_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_sku.id", ondelete="CASCADE"), nullable=True
    )
    # data_dir 下受控 POSIX 相对路径（原图非空；缩略可空，best-effort）
    image_path: Mapped[str] = mapped_column(String(2048))
    thumbnail_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    media_type: Mapped[str] = mapped_column(String(16))  # 白名单 REFERENCE_MEDIA_TYPES
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 实算：重复检测
    perceptual_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 占位
    angle: Mapped[str] = mapped_column(String(32), default="other")  # 白名单 REFERENCE_ANGLES
    state: Mapped[str] = mapped_column(String(16), default="draft")  # 白名单 REFERENCE_ASSET_STATES
    quality_status: Mapped[str] = mapped_column(String(16), default="unchecked")  # 人工标记
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 如 upload
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN family_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN variant_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN sku_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="exactly_one_target",
        ),
        Index("ix_ref_asset_family_id", "family_id"),
        Index("ix_ref_asset_variant_id", "variant_id"),
        Index("ix_ref_asset_sku_id", "sku_id"),
        Index("ix_ref_asset_state", "state"),
        Index("ix_ref_asset_sha256", "sha256"),  # 同目标重复检测查询
        # 每个目标至多一张活动主图（归档/拒绝的不计）
        Index(
            "uq_ref_asset_family_primary",
            "family_id",
            unique=True,
            postgresql_where=text("family_id IS NOT NULL AND is_primary AND archived_at IS NULL"),
        ),
        Index(
            "uq_ref_asset_variant_primary",
            "variant_id",
            unique=True,
            postgresql_where=text("variant_id IS NOT NULL AND is_primary AND archived_at IS NULL"),
        ),
        Index(
            "uq_ref_asset_sku_primary",
            "sku_id",
            unique=True,
            postgresql_where=text("sku_id IS NOT NULL AND is_primary AND archived_at IS NULL"),
        ),
    )
