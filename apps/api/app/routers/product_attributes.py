"""PR-A2 Gate A 路由：动态属性定义 / 属性值 / profile 聚合（挂载前缀 /api）。"""

from __future__ import annotations

from clipmind_shared.models import ProductAttributeDefinition, ProductAttributeValue
from clipmind_shared.models.enums import CatalogStatus
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.product_attributes import (
    AttributeDefinitionIn,
    AttributeDefinitionListResponse,
    AttributeDefinitionOut,
    AttributeDefinitionUpdate,
    AttributeStatusIn,
    AttributeValueOut,
    AttributeValueSetIn,
    ProfileOut,
)
from app.services import attribute_service as svc
from app.services.catalog_service import CatalogConflict, CatalogError

router = APIRouter(tags=["product-attributes"])


def _err(exc: CatalogError) -> HTTPException:
    code = 409 if isinstance(exc, CatalogConflict) else 422
    return HTTPException(status_code=code, detail=str(exc))


async def _fetch_def(db: AsyncSession, def_id: int) -> ProductAttributeDefinition:
    obj = await db.get(ProductAttributeDefinition, def_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="属性定义不存在")
    return obj


# ============================ 属性定义 ============================


@router.get("/product-attribute-definitions", response_model=AttributeDefinitionListResponse)
async def list_definitions(
    category_id: int | None = None,
    include_global: bool = True,
    status_filter: CatalogStatus | None = None,
    searchable: bool | None = None,
    identity_relevant: bool | None = None,
    include_archived: bool = False,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> AttributeDefinitionListResponse:
    rows, total = await svc.list_definitions(
        db, category_id=category_id, include_global=include_global, status=status_filter,
        searchable=searchable, identity_relevant=identity_relevant,
        include_archived=include_archived, q=q, limit=limit, offset=offset,
    )
    return AttributeDefinitionListResponse(
        items=[AttributeDefinitionOut.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/product-attribute-definitions", response_model=AttributeDefinitionOut, status_code=201
)
async def create_definition(
    body: AttributeDefinitionIn, db: AsyncSession = Depends(get_db)
) -> AttributeDefinitionOut:
    try:
        row = await svc.create_definition(db, body.model_dump())
    except CatalogError as exc:
        raise _err(exc) from exc
    return AttributeDefinitionOut.model_validate(row)


@router.get("/product-attribute-definitions/{def_id}", response_model=AttributeDefinitionOut)
async def get_definition(def_id: int, db: AsyncSession = Depends(get_db)) -> AttributeDefinitionOut:
    return AttributeDefinitionOut.model_validate(await _fetch_def(db, def_id))


@router.patch(
    "/product-attribute-definitions/{def_id}", response_model=AttributeDefinitionOut
)
async def update_definition(
    def_id: int, body: AttributeDefinitionUpdate, db: AsyncSession = Depends(get_db)
) -> AttributeDefinitionOut:
    obj = await _fetch_def(db, def_id)
    try:
        obj = await svc.update_definition(db, obj, body.model_dump(exclude_unset=True))
    except CatalogError as exc:
        raise _err(exc) from exc
    return AttributeDefinitionOut.model_validate(obj)


@router.post(
    "/product-attribute-definitions/{def_id}/status", response_model=AttributeDefinitionOut
)
async def set_definition_status(
    def_id: int, body: AttributeStatusIn, db: AsyncSession = Depends(get_db)
) -> AttributeDefinitionOut:
    obj = await _fetch_def(db, def_id)
    try:
        return AttributeDefinitionOut.model_validate(
            await svc.set_definition_status(db, obj, body.status)
        )
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post(
    "/product-attribute-definitions/{def_id}/archive", response_model=AttributeDefinitionOut
)
async def archive_definition(
    def_id: int, db: AsyncSession = Depends(get_db)
) -> AttributeDefinitionOut:
    obj = await _fetch_def(db, def_id)
    try:
        return AttributeDefinitionOut.model_validate(
            await svc.set_definition_status(db, obj, CatalogStatus.ARCHIVED)
        )
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post(
    "/product-attribute-definitions/{def_id}/restore", response_model=AttributeDefinitionOut
)
async def restore_definition(
    def_id: int, db: AsyncSession = Depends(get_db)
) -> AttributeDefinitionOut:
    obj = await _fetch_def(db, def_id)
    try:
        return AttributeDefinitionOut.model_validate(
            await svc.set_definition_status(db, obj, CatalogStatus.ACTIVE)
        )
    except CatalogError as exc:
        raise _err(exc) from exc


# ============================ 属性值 ============================


@router.get("/product-attribute-values", response_model=list[AttributeValueOut])
async def list_values(
    target_level: str = Query(..., pattern="^(family|variant|sku)$"),
    target_id: int = Query(...),
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
) -> list[AttributeValueOut]:
    try:
        rows = await svc.list_values(
            db, target_level, target_id, include_archived=include_archived
        )
    except CatalogError as exc:
        raise _err(exc) from exc
    return [AttributeValueOut.model_validate(r) for r in rows]


@router.put("/product-attribute-values", response_model=AttributeValueOut)
async def set_value(
    body: AttributeValueSetIn, db: AsyncSession = Depends(get_db)
) -> AttributeValueOut:
    try:
        row = await svc.set_value(
            db, definition_id=body.definition_id, target_type=body.target_level,
            target_id=body.target_id, value=body.value,
        )
    except CatalogError as exc:
        raise _err(exc) from exc
    return AttributeValueOut.model_validate(row)


@router.delete("/product-attribute-values/{value_id}", status_code=204)
async def delete_value(value_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.get(ProductAttributeValue, value_id)
    if row is None:
        raise HTTPException(status_code=404, detail="属性值不存在")
    await svc.delete_value(db, row)


# ============================ profile 聚合 ============================


@router.get("/product-catalog/{level}/{node_id}/profile", response_model=ProfileOut)
async def get_profile(
    level: str, node_id: int, db: AsyncSession = Depends(get_db)
) -> ProfileOut:
    if level not in ("category", "family", "variant", "sku"):
        raise HTTPException(status_code=422, detail="未知层级")
    try:
        return ProfileOut.model_validate(await svc.get_profile(db, level, node_id))
    except CatalogError as exc:
        raise _err(exc) from exc
