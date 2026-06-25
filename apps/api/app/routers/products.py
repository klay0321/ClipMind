"""产品库路由（PR-03B）：产品/别名/参考图/素材产品/主产品/镜头产品候选。"""

from __future__ import annotations

import os

from clipmind_shared.models import Asset, Product, ProductImage, Shot
from clipmind_shared.models.enums import ProductStatus
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.schemas.product import (
    AliasIn,
    AssetProductOut,
    AssetProductsIn,
    CandidateOut,
    PrimaryProductIn,
    ProductAliasOut,
    ProductImageOut,
    ProductIn,
    ProductOut,
    ProductUpdateIn,
)
from app.services import files, product_service
from app.services.product_service import ProductError

router = APIRouter(tags=["products"])

_MEDIA = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


async def _product_or_404(db: AsyncSession, product_id: int) -> Product:
    p = await product_service.get_product(db, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    return p


def _bad(exc: ProductError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


# ---------------- 产品 ----------------


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    q: str | None = None,
    status_filter: ProductStatus | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[ProductOut]:
    rows = await product_service.list_products(db, q=q, status=status_filter)
    return [ProductOut.model_validate(p) for p in rows]


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(body: ProductIn, db: AsyncSession = Depends(get_db)) -> ProductOut:
    try:
        p = await product_service.create_product(db, body.model_dump())
    except ProductError as exc:
        raise _bad(exc) from exc
    return ProductOut.model_validate(p)


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)) -> ProductOut:
    return ProductOut.model_validate(await _product_or_404(db, product_id))


@router.put("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int, body: ProductUpdateIn, db: AsyncSession = Depends(get_db)
) -> ProductOut:
    p = await _product_or_404(db, product_id)
    p = await product_service.update_product(db, p, body.model_dump(exclude_unset=True))
    return ProductOut.model_validate(p)


@router.post("/products/{product_id}/archive", response_model=ProductOut)
async def archive_product(product_id: int, db: AsyncSession = Depends(get_db)) -> ProductOut:
    p = await _product_or_404(db, product_id)
    return ProductOut.model_validate(await product_service.archive_product(db, p))


# ---------------- 别名 ----------------


@router.get("/products/{product_id}/aliases", response_model=list[ProductAliasOut])
async def list_aliases(
    product_id: int, db: AsyncSession = Depends(get_db)
) -> list[ProductAliasOut]:
    await _product_or_404(db, product_id)
    rows = await product_service.list_aliases(db, product_id)
    return [ProductAliasOut.model_validate(a) for a in rows]


@router.post(
    "/products/{product_id}/aliases",
    response_model=ProductAliasOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_alias(
    product_id: int, body: AliasIn, db: AsyncSession = Depends(get_db)
) -> ProductAliasOut:
    await _product_or_404(db, product_id)
    try:
        a = await product_service.add_alias(db, product_id, body.alias)
    except ProductError as exc:
        raise _bad(exc) from exc
    return ProductAliasOut.model_validate(a)


@router.delete("/products/{product_id}/aliases/{alias_id}", status_code=204)
async def delete_alias(
    product_id: int, alias_id: int, db: AsyncSession = Depends(get_db)
):
    if not await product_service.delete_alias(db, product_id, alias_id):
        raise HTTPException(status_code=404, detail="别名不存在")


# ---------------- 参考图 ----------------


@router.get("/products/{product_id}/images", response_model=list[ProductImageOut])
async def list_images(
    product_id: int, db: AsyncSession = Depends(get_db)
) -> list[ProductImageOut]:
    await _product_or_404(db, product_id)
    rows = await product_service.list_images(db, product_id)
    return [ProductImageOut.model_validate(i) for i in rows]


@router.post(
    "/products/{product_id}/images",
    response_model=ProductImageOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_image(
    product_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
) -> ProductImageOut:
    await _product_or_404(db, product_id)
    try:
        img = await product_service.add_image(
            db, product_id, filename=file.filename or "", stream=file
        )
    except ProductError as exc:
        raise _bad(exc) from exc
    return ProductImageOut.model_validate(img)


@router.get("/products/{product_id}/images/{image_id}/file")
async def get_image_file(
    product_id: int, image_id: int, db: AsyncSession = Depends(get_db)
) -> FileResponse:
    img = await db.get(ProductImage, image_id)
    if img is None or img.product_id != product_id:
        raise HTTPException(status_code=404, detail="参考图不存在")
    ext = os.path.splitext(img.image_path)[1].lstrip(".").lower()
    return files.serve_derived(img.image_path, media_type=_MEDIA.get(ext, "image/jpeg"))


@router.delete("/products/{product_id}/images/{image_id}", status_code=204)
async def delete_image(
    product_id: int, image_id: int, db: AsyncSession = Depends(get_db)
):
    if not await product_service.delete_image(db, product_id, image_id):
        raise HTTPException(status_code=404, detail="参考图不存在")


# ---------------- 素材↔产品 ----------------


async def _asset_or_404(db: AsyncSession, asset_id: int) -> Asset:
    a = await db.get(Asset, asset_id)
    if a is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    return a


@router.get("/assets/{asset_id}/products", response_model=list[AssetProductOut])
async def list_asset_products(
    asset_id: int, db: AsyncSession = Depends(get_db)
) -> list[AssetProductOut]:
    await _asset_or_404(db, asset_id)
    rows = await product_service.list_asset_products(db, asset_id)
    return [AssetProductOut.model_validate(r) for r in rows]


@router.put("/assets/{asset_id}/products", response_model=list[AssetProductOut])
async def set_asset_products(
    asset_id: int, body: AssetProductsIn, db: AsyncSession = Depends(get_db)
) -> list[AssetProductOut]:
    asset = await _asset_or_404(db, asset_id)
    reviewer = (body.reviewer_label or "").strip() or get_settings().review_default_reviewer
    try:
        rows = await product_service.set_asset_products(
            db, asset, body.product_ids, reviewer_label=reviewer[:255]
        )
    except ProductError as exc:
        raise _bad(exc) from exc
    return [AssetProductOut.model_validate(r) for r in rows]


@router.put("/assets/{asset_id}/primary-product", response_model=ProductOut | None)
async def set_primary_product(
    asset_id: int, body: PrimaryProductIn, db: AsyncSession = Depends(get_db)
) -> ProductOut | None:
    asset = await _asset_or_404(db, asset_id)
    try:
        asset = await product_service.set_primary_product(db, asset, body.product_id)
    except ProductError as exc:
        raise _bad(exc) from exc
    if asset.primary_product_id is None:
        return None
    p = await product_service.get_product(db, asset.primary_product_id)
    return ProductOut.model_validate(p) if p else None


# ---------------- 镜头产品候选 ----------------


@router.get("/shots/{shot_id}/product-candidates", response_model=list[CandidateOut])
async def shot_product_candidates(
    shot_id: int, db: AsyncSession = Depends(get_db)
) -> list[CandidateOut]:
    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    cands = await product_service.candidates_for_shot(db, shot)
    return [CandidateOut(**c.__dict__) for c in cands]
