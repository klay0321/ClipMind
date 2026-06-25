"""产品库服务（PR-03B Gate B）。

- 无物理删除产品；archive 后历史审核关系仍可读。
- 素材↔产品多对多（asset_product）；primary_product 是人工动作，必在 asset_product 关系内。
- 参考图写 /app/data/products/{id}/images/，库内只存受控相对路径；safe_join + .part 清理 +
  扩展名/MIME/大小/数量限制 + 真实图片内容校验；绝不写源/上传区，绝不暴露绝对路径。
- 候选匹配只读不写，不自动绑定 confirmed_product_id。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIShotAnalysis,
    Asset,
    AssetProduct,
    Product,
    ProductAlias,
    ProductImage,
    Shot,
)
from clipmind_shared.models.enums import ProductStatus, TagSource
from clipmind_shared.review import ProductLike, match_products, normalize_name
from clipmind_shared.security import safe_join_within_root
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)

# 允许的参考图类型（扩展名 -> 魔数前缀）
_IMAGE_MAGIC = {
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "webp": (b"RIFF",),  # RIFF....WEBP
}


class ProductError(Exception):
    """产品库业务错误（校验/约束）。"""


# ---------------- 产品 CRUD ----------------


async def list_products(
    db: AsyncSession, *, q: str | None = None, status: ProductStatus | None = None
) -> list[Product]:
    stmt = select(Product)
    if q:
        stmt = stmt.where(Product.normalized_name.like(f"%{normalize_name(q)}%"))
    if status is not None:
        stmt = stmt.where(Product.status == status)
    stmt = stmt.order_by(Product.id.asc())
    return list((await db.execute(stmt)).scalars().all())


async def create_product(db: AsyncSession, data: dict[str, Any]) -> Product:
    name = (data.get("name") or "").strip()
    if not name:
        raise ProductError("产品名不能为空")
    p = Product(
        brand=(data.get("brand") or None),
        name=name,
        normalized_name=normalize_name(name),
        model=(data.get("model") or None),
        sku=(data.get("sku") or None),
        selling_points=data.get("selling_points") or None,
        status=ProductStatus.ACTIVE,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def get_product(db: AsyncSession, product_id: int) -> Product | None:
    return await db.get(Product, product_id)


async def update_product(db: AsyncSession, product: Product, data: dict[str, Any]) -> Product:
    if "name" in data and data["name"]:
        product.name = data["name"].strip()
        product.normalized_name = normalize_name(product.name)
    for f in ("brand", "model", "sku"):
        if f in data:
            setattr(product, f, data[f] or None)
    if "selling_points" in data:
        product.selling_points = data["selling_points"] or None
    await db.commit()
    await db.refresh(product)
    return product


async def archive_product(db: AsyncSession, product: Product) -> Product:
    product.status = ProductStatus.ARCHIVED
    await db.commit()
    await db.refresh(product)
    return product


# ---------------- 别名 ----------------


async def list_aliases(db: AsyncSession, product_id: int) -> list[ProductAlias]:
    stmt = select(ProductAlias).where(ProductAlias.product_id == product_id).order_by(
        ProductAlias.id.asc()
    )
    return list((await db.execute(stmt)).scalars().all())


async def add_alias(db: AsyncSession, product_id: int, alias: str) -> ProductAlias:
    alias = (alias or "").strip()
    if not alias:
        raise ProductError("别名不能为空")
    row = ProductAlias(
        product_id=product_id, alias=alias, normalized_alias=normalize_name(alias)
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ProductError("该产品下已存在同名别名") from exc
    await db.refresh(row)
    return row


async def delete_alias(db: AsyncSession, product_id: int, alias_id: int) -> bool:
    row = await db.get(ProductAlias, alias_id)
    if row is None or row.product_id != product_id:
        return False
    await db.delete(row)
    await db.commit()
    return True


# ---------------- 参考图 ----------------


def _images_dir(product_id: int) -> str:
    settings = get_settings()
    data_root = os.path.realpath(settings.data_dir)
    return safe_join_within_root(data_root, "products", str(int(product_id)), "images")


def _ext_ok(filename: str) -> str | None:
    ext = os.path.splitext(filename or "")[1].lstrip(".").lower()
    return ext if ext in _IMAGE_MAGIC else None


def _looks_like_image(ext: str, head: bytes) -> bool:
    if ext == "webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return any(head.startswith(m) for m in _IMAGE_MAGIC[ext])


async def list_images(db: AsyncSession, product_id: int) -> list[ProductImage]:
    stmt = select(ProductImage).where(ProductImage.product_id == product_id).order_by(
        ProductImage.id.asc()
    )
    return list((await db.execute(stmt)).scalars().all())


async def add_image(
    db: AsyncSession, product_id: int, *, filename: str, stream
) -> ProductImage:  # noqa: ANN001
    settings = get_settings()
    ext = _ext_ok(filename)
    if ext is None:
        raise ProductError("仅支持 jpg/png/webp 图片")
    existing = await list_images(db, product_id)
    if len(existing) >= settings.product_image_max_count:
        raise ProductError(f"参考图数量已达上限 {settings.product_image_max_count}")

    img_dir = _images_dir(product_id)
    os.makedirs(img_dir, exist_ok=True)
    # 服务端生成文件名（uuid，避免穿越/冲突）
    name = f"{uuid.uuid4().hex}.{ext}"
    dest = safe_join_within_root(img_dir, name)
    tmp = dest + ".part"
    max_bytes = settings.product_image_max_mb * 1024 * 1024
    written = 0
    head = b""
    try:
        with open(tmp, "wb") as f:
            while True:
                chunk = await stream.read(1024 * 256)
                if not chunk:
                    break
                if not head:
                    head = chunk[:16]
                written += len(chunk)
                if written > max_bytes:
                    raise ProductError(f"图片超过 {settings.product_image_max_mb}MB 上限")
                f.write(chunk)
        if not _looks_like_image(ext, head):
            raise ProductError("文件内容不是有效图片")
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

    rel = f"products/{int(product_id)}/images/{name}"
    row = ProductImage(product_id=product_id, image_path=rel)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_image(db: AsyncSession, product_id: int, image_id: int) -> bool:
    row = await db.get(ProductImage, image_id)
    if row is None or row.product_id != product_id:
        return False
    # 先删库记录再尽力删文件（孤儿文件可后续清理任务回收）
    rel = row.image_path
    await db.delete(row)
    await db.commit()
    try:
        settings = get_settings()
        data_root = os.path.realpath(settings.data_dir)
        abs_path = safe_join_within_root(data_root, *rel.split("/"))
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except OSError:
        logger.warning("删除参考图文件失败（库记录已删，孤儿文件可后续清理）: %s", rel)
    return True


# ---------------- 素材↔产品 ----------------


async def list_asset_products(db: AsyncSession, asset_id: int) -> list[AssetProduct]:
    stmt = select(AssetProduct).where(AssetProduct.asset_id == asset_id).order_by(
        AssetProduct.id.asc()
    )
    return list((await db.execute(stmt)).scalars().all())


async def set_asset_products(
    db: AsyncSession, asset: Asset, product_ids: list[int], *, reviewer_label: str
) -> list[AssetProduct]:
    """人工设置素材的产品集合（human source）。整集覆盖人工关系，保留 AI 候选关系。"""
    # 删除旧的 human 关系
    existing = await list_asset_products(db, asset.id)
    for ap in existing:
        if ap.source == TagSource.HUMAN:
            await db.delete(ap)
    await db.flush()
    for pid in dict.fromkeys(product_ids):  # 去重保序
        if await db.get(Product, pid) is None:
            raise ProductError(f"产品不存在: {pid}")
        db.add(
            AssetProduct(
                asset_id=asset.id, product_id=pid, source=TagSource.HUMAN,
                confirmed_by=reviewer_label, confirmed_at=utcnow(), active=True,
            )
        )
    await db.commit()
    return await list_asset_products(db, asset.id)


async def set_primary_product(
    db: AsyncSession, asset: Asset, product_id: int | None
) -> Asset:
    """设置主产品（人工动作）。主产品必须在 asset_product 人工关系内。"""
    if product_id is not None:
        rels = await list_asset_products(db, asset.id)
        if not any(
            ap.product_id == product_id and ap.source == TagSource.HUMAN for ap in rels
        ):
            raise ProductError("主产品必须先在素材的人工产品关系中")
    asset.primary_product_id = product_id
    await db.commit()
    await db.refresh(asset)
    return asset


# ---------------- 候选匹配 ----------------


async def _product_likes(db: AsyncSession) -> list[ProductLike]:
    products = await list_products(db, status=ProductStatus.ACTIVE)
    likes: list[ProductLike] = []
    for p in products:
        aliases = await list_aliases(db, p.id)
        likes.append(
            ProductLike(
                id=p.id, name=p.name, brand=p.brand, model=p.model, sku=p.sku,
                normalized_name=p.normalized_name,
                normalized_aliases=[a.normalized_alias for a in aliases],
            )
        )
    return likes


async def candidates_for_shot(db: AsyncSession, shot: Shot) -> list:
    """从镜头当前 AI 结果的产品名做候选匹配（只读，不绑定）。"""
    ai = (
        await db.execute(select(AIShotAnalysis).where(AIShotAnalysis.shot_id == shot.id))
    ).scalars().first()
    if ai is None or not ai.parsed_result:
        return []
    product = ai.parsed_result.get("product") or {}
    query = product.get("name") if isinstance(product, dict) else None
    if not query:
        return []
    return match_products(query, await _product_likes(db))
