"""PR-A1 通用产品目录路由（Category / Family / Variant / SKU / Alias + tree/search/resolve）。

与既有 `/api/products`（扁平业务产品）**并存**，互不影响。挂载前缀 `/api`。
"""

from __future__ import annotations

from clipmind_shared.models.enums import CatalogStatus
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.product_catalog import (
    CatalogAliasIn,
    CatalogAliasOut,
    CatalogAliasUpdateIn,
    CatalogNode,
    CategoryIn,
    CategoryListResponse,
    CategoryOut,
    CategoryUpdateIn,
    FamilyIn,
    FamilyListResponse,
    FamilyOut,
    FamilyUpdateIn,
    MergeIn,
    SkuIn,
    SkuListResponse,
    SkuOut,
    SkuUpdateIn,
    StatusIn,
    TreeNode,
    VariantIn,
    VariantListResponse,
    VariantOut,
    VariantUpdateIn,
)
from app.services import catalog_service as svc
from app.services.catalog_service import CatalogConflict, CatalogError

router = APIRouter(tags=["product-catalog"])


def _err(exc: CatalogError) -> HTTPException:
    code = 409 if isinstance(exc, CatalogConflict) else 422
    return HTTPException(status_code=code, detail=str(exc))


async def _fetch(db: AsyncSession, level: str, obj_id: int):
    obj = await db.get(svc.LEVELS[level], obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{level} 不存在")
    return obj


# ============================ Category ============================


@router.get("/product-categories", response_model=CategoryListResponse)
async def list_categories(
    q: str | None = None,
    status_filter: CatalogStatus | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> CategoryListResponse:
    rows, total = await svc.list_level(
        db, "category", q=q, status=status_filter,
        include_archived=include_archived, limit=limit, offset=offset,
    )
    return CategoryListResponse(items=[CategoryOut.model_validate(r) for r in rows], total=total)


@router.post("/product-categories", response_model=CategoryOut, status_code=201)
async def create_category(body: CategoryIn, db: AsyncSession = Depends(get_db)) -> CategoryOut:
    try:
        row = await svc.create_category(db, body.model_dump())
    except CatalogError as exc:
        raise _err(exc) from exc
    return CategoryOut.model_validate(row)


@router.get("/product-categories/{cid}", response_model=CategoryOut)
async def get_category(cid: int, db: AsyncSession = Depends(get_db)) -> CategoryOut:
    return CategoryOut.model_validate(await _fetch(db, "category", cid))


@router.patch("/product-categories/{cid}", response_model=CategoryOut)
async def update_category(
    cid: int, body: CategoryUpdateIn, db: AsyncSession = Depends(get_db)
) -> CategoryOut:
    obj = await _fetch(db, "category", cid)
    try:
        obj = await svc.update_node(db, "category", obj, body.model_dump(exclude_unset=True))
    except CatalogError as exc:
        raise _err(exc) from exc
    return CategoryOut.model_validate(obj)


@router.post("/product-categories/{cid}/archive", response_model=CategoryOut)
async def archive_category(cid: int, db: AsyncSession = Depends(get_db)) -> CategoryOut:
    obj = await _fetch(db, "category", cid)
    try:
        return CategoryOut.model_validate(await svc.archive(db, "category", obj))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post("/product-categories/{cid}/restore", response_model=CategoryOut)
async def restore_category(cid: int, db: AsyncSession = Depends(get_db)) -> CategoryOut:
    obj = await _fetch(db, "category", cid)
    try:
        return CategoryOut.model_validate(await svc.restore(db, "category", obj))
    except CatalogError as exc:
        raise _err(exc) from exc


# ============================ Family ============================


@router.get("/product-families", response_model=FamilyListResponse)
async def list_families(
    q: str | None = None,
    status_filter: CatalogStatus | None = None,
    category_id: int | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> FamilyListResponse:
    rows, total = await svc.list_level(
        db, "family", q=q, status=status_filter, category_id=category_id,
        include_archived=include_archived, limit=limit, offset=offset,
    )
    return FamilyListResponse(items=[FamilyOut.model_validate(r) for r in rows], total=total)


@router.post("/product-families", response_model=FamilyOut, status_code=201)
async def create_family(body: FamilyIn, db: AsyncSession = Depends(get_db)) -> FamilyOut:
    try:
        row = await svc.create_family(db, body.model_dump())
    except CatalogError as exc:
        raise _err(exc) from exc
    return FamilyOut.model_validate(row)


@router.get("/product-families/{fid}", response_model=FamilyOut)
async def get_family(fid: int, db: AsyncSession = Depends(get_db)) -> FamilyOut:
    return FamilyOut.model_validate(await _fetch(db, "family", fid))


@router.patch("/product-families/{fid}", response_model=FamilyOut)
async def update_family(
    fid: int, body: FamilyUpdateIn, db: AsyncSession = Depends(get_db)
) -> FamilyOut:
    obj = await _fetch(db, "family", fid)
    try:
        obj = await svc.update_node(db, "family", obj, body.model_dump(exclude_unset=True))
    except CatalogError as exc:
        raise _err(exc) from exc
    return FamilyOut.model_validate(obj)


@router.post("/product-families/{fid}/archive", response_model=FamilyOut)
async def archive_family(fid: int, db: AsyncSession = Depends(get_db)) -> FamilyOut:
    obj = await _fetch(db, "family", fid)
    try:
        return FamilyOut.model_validate(await svc.archive(db, "family", obj))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post("/product-families/{fid}/restore", response_model=FamilyOut)
async def restore_family(fid: int, db: AsyncSession = Depends(get_db)) -> FamilyOut:
    obj = await _fetch(db, "family", fid)
    try:
        return FamilyOut.model_validate(await svc.restore(db, "family", obj))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post("/product-families/{fid}/merge", response_model=FamilyOut)
async def merge_family(
    fid: int, body: MergeIn, db: AsyncSession = Depends(get_db)
) -> FamilyOut:
    obj = await _fetch(db, "family", fid)
    try:
        return FamilyOut.model_validate(await svc.merge(db, "family", obj, body.target_id))
    except CatalogError as exc:
        raise _err(exc) from exc


# ============================ Variant ============================


@router.get("/product-variants", response_model=VariantListResponse)
async def list_variants(
    q: str | None = None,
    status_filter: CatalogStatus | None = None,
    family_id: int | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> VariantListResponse:
    rows, total = await svc.list_level(
        db, "variant", q=q, status=status_filter, family_id=family_id,
        include_archived=include_archived, limit=limit, offset=offset,
    )
    return VariantListResponse(items=[VariantOut.model_validate(r) for r in rows], total=total)


@router.post("/product-variants", response_model=VariantOut, status_code=201)
async def create_variant(body: VariantIn, db: AsyncSession = Depends(get_db)) -> VariantOut:
    try:
        row = await svc.create_variant(db, body.model_dump())
    except CatalogError as exc:
        raise _err(exc) from exc
    return VariantOut.model_validate(row)


@router.get("/product-variants/{vid}", response_model=VariantOut)
async def get_variant(vid: int, db: AsyncSession = Depends(get_db)) -> VariantOut:
    return VariantOut.model_validate(await _fetch(db, "variant", vid))


@router.patch("/product-variants/{vid}", response_model=VariantOut)
async def update_variant(
    vid: int, body: VariantUpdateIn, db: AsyncSession = Depends(get_db)
) -> VariantOut:
    obj = await _fetch(db, "variant", vid)
    try:
        obj = await svc.update_node(db, "variant", obj, body.model_dump(exclude_unset=True))
    except CatalogError as exc:
        raise _err(exc) from exc
    return VariantOut.model_validate(obj)


@router.post("/product-variants/{vid}/archive", response_model=VariantOut)
async def archive_variant(vid: int, db: AsyncSession = Depends(get_db)) -> VariantOut:
    obj = await _fetch(db, "variant", vid)
    try:
        return VariantOut.model_validate(await svc.archive(db, "variant", obj))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post("/product-variants/{vid}/restore", response_model=VariantOut)
async def restore_variant(vid: int, db: AsyncSession = Depends(get_db)) -> VariantOut:
    obj = await _fetch(db, "variant", vid)
    try:
        return VariantOut.model_validate(await svc.restore(db, "variant", obj))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post("/product-variants/{vid}/merge", response_model=VariantOut)
async def merge_variant(
    vid: int, body: MergeIn, db: AsyncSession = Depends(get_db)
) -> VariantOut:
    obj = await _fetch(db, "variant", vid)
    try:
        return VariantOut.model_validate(await svc.merge(db, "variant", obj, body.target_id))
    except CatalogError as exc:
        raise _err(exc) from exc


# ============================ SKU ============================


@router.get("/product-skus", response_model=SkuListResponse)
async def list_skus(
    q: str | None = None,
    status_filter: CatalogStatus | None = None,
    family_id: int | None = None,
    variant_id: int | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> SkuListResponse:
    rows, total = await svc.list_level(
        db, "sku", q=q, status=status_filter, family_id=family_id, variant_id=variant_id,
        include_archived=include_archived, limit=limit, offset=offset,
    )
    return SkuListResponse(items=[SkuOut.model_validate(r) for r in rows], total=total)


@router.post("/product-skus", response_model=SkuOut, status_code=201)
async def create_sku(body: SkuIn, db: AsyncSession = Depends(get_db)) -> SkuOut:
    try:
        row = await svc.create_sku(db, body.model_dump())
    except CatalogError as exc:
        raise _err(exc) from exc
    return SkuOut.model_validate(row)


@router.get("/product-skus/{sid}", response_model=SkuOut)
async def get_sku(sid: int, db: AsyncSession = Depends(get_db)) -> SkuOut:
    return SkuOut.model_validate(await _fetch(db, "sku", sid))


@router.patch("/product-skus/{sid}", response_model=SkuOut)
async def update_sku(
    sid: int, body: SkuUpdateIn, db: AsyncSession = Depends(get_db)
) -> SkuOut:
    obj = await _fetch(db, "sku", sid)
    try:
        obj = await svc.update_node(db, "sku", obj, body.model_dump(exclude_unset=True))
    except CatalogError as exc:
        raise _err(exc) from exc
    return SkuOut.model_validate(obj)


@router.post("/product-skus/{sid}/archive", response_model=SkuOut)
async def archive_sku(sid: int, db: AsyncSession = Depends(get_db)) -> SkuOut:
    obj = await _fetch(db, "sku", sid)
    try:
        return SkuOut.model_validate(await svc.archive(db, "sku", obj))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post("/product-skus/{sid}/restore", response_model=SkuOut)
async def restore_sku(sid: int, db: AsyncSession = Depends(get_db)) -> SkuOut:
    obj = await _fetch(db, "sku", sid)
    try:
        return SkuOut.model_validate(await svc.restore(db, "sku", obj))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post("/product-skus/{sid}/merge", response_model=SkuOut)
async def merge_sku(sid: int, body: MergeIn, db: AsyncSession = Depends(get_db)) -> SkuOut:
    obj = await _fetch(db, "sku", sid)
    try:
        return SkuOut.model_validate(await svc.merge(db, "sku", obj, body.target_id))
    except CatalogError as exc:
        raise _err(exc) from exc


# ============================ Status（通用） ============================


@router.post("/product-families/{fid}/status", response_model=FamilyOut)
async def set_family_status(
    fid: int, body: StatusIn, db: AsyncSession = Depends(get_db)
) -> FamilyOut:
    obj = await _fetch(db, "family", fid)
    try:
        return FamilyOut.model_validate(await svc.set_status(db, "family", obj, body.status))
    except CatalogError as exc:
        raise _err(exc) from exc


# ============================ Alias ============================


@router.get("/product-aliases", response_model=list[CatalogAliasOut])
async def list_catalog_aliases(
    target_level: str | None = None,
    target_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[CatalogAliasOut]:
    rows = await svc.list_aliases(db, target_level, target_id)
    return [CatalogAliasOut.model_validate(r) for r in rows]


@router.post("/product-aliases", response_model=CatalogAliasOut, status_code=201)
async def create_catalog_alias(
    body: CatalogAliasIn, db: AsyncSession = Depends(get_db)
) -> CatalogAliasOut:
    try:
        row = await svc.add_alias(db, body.model_dump())
    except CatalogError as exc:
        raise _err(exc) from exc
    return CatalogAliasOut.model_validate(row)


@router.patch("/product-aliases/{aid}", response_model=CatalogAliasOut)
async def update_catalog_alias(
    aid: int, body: CatalogAliasUpdateIn, db: AsyncSession = Depends(get_db)
) -> CatalogAliasOut:
    try:
        row = await svc.update_alias(db, aid, body.model_dump(exclude_unset=True))
    except CatalogError as exc:
        raise _err(exc) from exc
    return CatalogAliasOut.model_validate(row)


@router.delete("/product-aliases/{aid}", status_code=204)
async def delete_catalog_alias(aid: int, db: AsyncSession = Depends(get_db)):
    if not await svc.delete_alias(db, aid):
        raise HTTPException(status_code=404, detail="别名不存在")


# ============================ Catalog（tree/search/resolve） ============================


@router.get("/product-catalog/tree", response_model=list[TreeNode])
async def catalog_tree(
    include_archived: bool = False, db: AsyncSession = Depends(get_db)
) -> list[TreeNode]:
    tree = await svc.get_tree(db, include_archived=include_archived)
    return [TreeNode.model_validate(n) for n in tree]


@router.get("/product-catalog/search", response_model=list[CatalogNode])
async def catalog_search(
    q: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)
) -> list[CatalogNode]:
    return [CatalogNode.model_validate(n) for n in await svc.search_catalog(db, q)]


@router.get("/product-catalog/resolve", response_model=CatalogNode | None)
async def catalog_resolve(
    value: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)
) -> CatalogNode | None:
    node = await svc.resolve(db, value)
    return CatalogNode.model_validate(node) if node else None
