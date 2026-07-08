"""PR-A2 Gate A 路由：产品参考图库（上传/管理/安全文件服务，挂载前缀 /api）。

上传经 multipart；文件经既有安全媒体服务提供，绝不返回服务器绝对路径。
明示：**自动产品识别尚未启用**——参考图用于建立产品资料与后续识别基线。
"""

from __future__ import annotations

from clipmind_shared.models import ProductReferenceAsset
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.product_attributes import (
    ReferenceAssetOut,
    ReferenceAssetUpdateIn,
    ReferenceBatchAngleIn,
    ReferenceBatchIdsIn,
    ReferenceUploadError,
    ReferenceUploadResult,
)
from app.services import files
from app.services import reference_service as svc
from app.services.catalog_service import CatalogConflict, CatalogError

router = APIRouter(tags=["product-reference-assets"])


def _err(exc: CatalogError) -> HTTPException:
    code = 409 if isinstance(exc, CatalogConflict) else 422
    return HTTPException(status_code=code, detail=str(exc))


def _out(asset: ProductReferenceAsset) -> ReferenceAssetOut:
    data = ReferenceAssetOut.model_validate(asset)
    data.has_thumbnail = bool(asset.thumbnail_path)
    return data


async def _fetch(db: AsyncSession, ref_id: int) -> ProductReferenceAsset:
    obj = await svc.get_reference(db, ref_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="参考图不存在")
    return obj


# ============================ 列表 / 详情 ============================


@router.get("/product-reference-assets", response_model=list[ReferenceAssetOut])
async def list_references(
    target_level: str,
    target_id: int,
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
) -> list[ReferenceAssetOut]:
    try:
        rows = await svc.list_references(
            db, target_level, target_id, include_archived=include_archived
        )
    except CatalogError as exc:
        raise _err(exc) from exc
    return [_out(r) for r in rows]


@router.get("/product-reference-assets/{ref_id}", response_model=ReferenceAssetOut)
async def get_reference(ref_id: int, db: AsyncSession = Depends(get_db)) -> ReferenceAssetOut:
    return _out(await _fetch(db, ref_id))


# ============================ 上传（单/批，multipart）============================


@router.post("/product-reference-assets", response_model=ReferenceUploadResult, status_code=201)
async def upload_references(
    target_level: str = Form(...),
    target_id: int = Form(...),
    angle: str | None = Form(None),
    state: str | None = Form(None),
    description: str | None = Form(None),
    is_primary: bool = Form(False),
    files_: list[UploadFile] = File(..., alias="files"),
    db: AsyncSession = Depends(get_db),
) -> ReferenceUploadResult:
    created: list[ReferenceAssetOut] = []
    errors: list[ReferenceUploadError] = []
    first = True
    for uf in files_:
        try:
            asset = await svc.upload_reference(
                db, target_type=target_level, target_id=target_id,
                filename=uf.filename or "upload", stream=uf,
                angle=angle, state=state, description=description,
                is_primary=(is_primary and first),  # 主图仅作用于首张，避免多主图
            )
            created.append(_out(asset))
            first = False
        except CatalogError as exc:
            # 单张失败不影响其它已成功图片（§七）
            errors.append(ReferenceUploadError(filename=uf.filename or "upload", detail=str(exc)))
        finally:
            await uf.close()
    return ReferenceUploadResult(created=created, errors=errors)


# ============================ 更新 / 生命周期 ============================


@router.patch("/product-reference-assets/{ref_id}", response_model=ReferenceAssetOut)
async def update_reference(
    ref_id: int, body: ReferenceAssetUpdateIn, db: AsyncSession = Depends(get_db)
) -> ReferenceAssetOut:
    obj = await _fetch(db, ref_id)
    try:
        obj = await svc.update_reference(db, obj, body.model_dump(exclude_unset=True))
    except CatalogError as exc:
        raise _err(exc) from exc
    return _out(obj)


@router.post("/product-reference-assets/{ref_id}/primary", response_model=ReferenceAssetOut)
async def set_primary(ref_id: int, db: AsyncSession = Depends(get_db)) -> ReferenceAssetOut:
    obj = await _fetch(db, ref_id)
    try:
        return _out(await svc.set_primary(db, obj))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post("/product-reference-assets/{ref_id}/archive", response_model=ReferenceAssetOut)
async def archive_reference(ref_id: int, db: AsyncSession = Depends(get_db)) -> ReferenceAssetOut:
    obj = await _fetch(db, ref_id)
    try:
        return _out(await svc.archive_reference(db, obj))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post("/product-reference-assets/{ref_id}/restore", response_model=ReferenceAssetOut)
async def restore_reference(ref_id: int, db: AsyncSession = Depends(get_db)) -> ReferenceAssetOut:
    obj = await _fetch(db, ref_id)
    try:
        return _out(await svc.restore_reference(db, obj))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.delete("/product-reference-assets/{ref_id}", status_code=204)
async def delete_reference(ref_id: int, db: AsyncSession = Depends(get_db)):
    obj = await _fetch(db, ref_id)
    await svc.delete_reference(db, obj)


# ============================ 批量 ============================


@router.post("/product-reference-assets/batch-angle", response_model=list[ReferenceAssetOut])
async def batch_set_angle(
    body: ReferenceBatchAngleIn, db: AsyncSession = Depends(get_db)
) -> list[ReferenceAssetOut]:
    out: list[ReferenceAssetOut] = []
    for rid in body.ids:
        obj = await svc.get_reference(db, rid)
        if obj is None:
            continue
        try:
            out.append(_out(await svc.update_reference(db, obj, {"angle": body.angle})))
        except CatalogError as exc:
            raise _err(exc) from exc
    return out


@router.post("/product-reference-assets/batch-archive", response_model=list[ReferenceAssetOut])
async def batch_archive(
    body: ReferenceBatchIdsIn, db: AsyncSession = Depends(get_db)
) -> list[ReferenceAssetOut]:
    out: list[ReferenceAssetOut] = []
    for rid in body.ids:
        obj = await svc.get_reference(db, rid)
        if obj is None:
            continue
        out.append(_out(await svc.archive_reference(db, obj)))
    return out


# ============================ 安全文件服务 ============================


@router.get("/product-reference-assets/{ref_id}/file")
async def serve_file(ref_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    obj = await _fetch(db, ref_id)
    return files.serve_derived(
        obj.image_path, media_type=(obj.content_type or "application/octet-stream")
    )


@router.get("/product-reference-assets/{ref_id}/thumbnail")
async def serve_thumbnail(ref_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    obj = await _fetch(db, ref_id)
    # 缩略缺失（best-effort 失败）时回退原图
    rel = obj.thumbnail_path or obj.image_path
    mt = "image/webp" if obj.thumbnail_path else (obj.content_type or "application/octet-stream")
    return files.serve_derived(rel, media_type=mt)


# ============================ EVAL：素材提升为参考图 ============================


@router.get("/product-reference-assets/promotion/suggestions")
async def promotion_suggestions(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """参考图不足的产品 + 可提升的已确认绑定图片建议清单（只读，不自动执行）。"""
    return await svc.promotion_suggestions(db)


@router.post(
    "/product-reference-assets/promotion/promote",
    response_model=ReferenceAssetOut,
    status_code=201,
)
async def promote_from_asset(
    target_level: str = Form(...),
    target_id: int = Form(...),
    asset_id: int = Form(...),
    angle: str | None = Form(None),
    state: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> ReferenceAssetOut:
    """把一张已确认绑定的图片素材复制为参考图（源只读；逐张人工采纳）。"""
    try:
        row = await svc.promote_from_asset(
            db, target_type=target_level, target_id=target_id,
            asset_id=asset_id, angle=angle, state=state,
        )
    except CatalogError as exc:
        raise _err(exc) from exc
    return _out(row)
