"""PR-A2 Gate A：产品参考图库服务（ProductReferenceAsset）。

安全上传流程（§七，复用既有安全媒体基础设施）：
  临时 .part → 流式校验(魔数/大小) + sha256 实算 → 重复检测 → 宽高探测 + 像素炸弹防护
  → os.replace 原子落盘 → best-effort 缩略图 → DB 提交；任一步失败**不留库记录、清理未引用文件**。

- DB 只存 data_dir 下受控 POSIX 相对路径（image_path/thumbnail_path），绝不存绝对路径。
- 服务端生成 uuid 文件名，绝不采信前端路径；safe_join_within_root 防穿越。
- 归档/删除只操作 data_dir 派生文件，**绝不触及只读源**；删除采用「先删库记录、再尽力删文件」。
- 主图唯一：每个目标至多一张活动主图（DB partial-unique + service 同事务清旧）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import ProductReferenceAsset
from clipmind_shared.models.enums import (
    REFERENCE_ANGLES,
    REFERENCE_ASSET_STATES,
    REFERENCE_HIDDEN_STATES,
    REFERENCE_QUALITY_STATUSES,
)
from clipmind_shared.security import safe_join_within_root
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services import images, revision_service
from app.services.catalog_service import LEVELS, CatalogConflict, CatalogError

logger = logging.getLogger(__name__)

_TARGET_TYPES = ("family", "variant", "sku")
_TARGET_COL = {
    "family": ProductReferenceAsset.family_id,
    "variant": ProductReferenceAsset.variant_id,
    "sku": ProductReferenceAsset.sku_id,
}


def _data_root() -> str:
    return os.path.realpath(get_settings().data_dir)


def _ref_dir(target_type: str, target_id: int) -> str:
    return safe_join_within_root(
        _data_root(), "product_reference_assets", target_type, str(int(target_id))
    )


def _rel(target_type: str, target_id: int, *parts: str) -> str:
    return "/".join(("product_reference_assets", target_type, str(int(target_id)), *parts))


async def _resolve_target(db: AsyncSession, target_type: str, target_id: int):
    if target_type not in _TARGET_TYPES:
        raise CatalogError("参考图只能绑定 family / variant / sku")
    obj = await db.get(LEVELS[target_type], int(target_id))
    if obj is None:
        raise CatalogError(f"{target_type} 不存在: {target_id}")
    return obj


def _target_of(asset: ProductReferenceAsset) -> tuple[str, int]:
    if asset.family_id is not None:
        return "family", asset.family_id
    if asset.variant_id is not None:
        return "variant", asset.variant_id
    return "sku", asset.sku_id


def _valid_angle(v: str | None) -> str:
    v = (v or "other").strip().lower()
    if v not in REFERENCE_ANGLES:
        raise CatalogError(f"未知参考图角度: {v}")
    return v


def _valid_state(v: str | None) -> str:
    v = (v or "draft").strip().lower()
    if v not in REFERENCE_ASSET_STATES:
        raise CatalogError(f"未知参考图状态: {v}")
    return v


def _valid_quality(v: str | None) -> str:
    v = (v or "unchecked").strip().lower()
    if v not in REFERENCE_QUALITY_STATUSES:
        raise CatalogError(f"未知质量状态: {v}")
    return v


def _abs(rel: str | None) -> str | None:
    if not rel:
        return None
    return safe_join_within_root(_data_root(), rel)


# --------------------------------------------------------------------------- #
# 上传
# --------------------------------------------------------------------------- #


async def upload_reference(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: int,
    filename: str,
    stream,  # noqa: ANN001  FastAPI UploadFile（async read）
    angle: str | None = None,
    state: str | None = None,
    description: str | None = None,
    is_primary: bool = False,
) -> ProductReferenceAsset:
    settings = get_settings()
    ext = images.ext_of(filename)
    if ext is None:
        raise CatalogError("仅支持 jpg / jpeg / png / webp 图片")
    await _resolve_target(db, target_type, target_id)
    angle = _valid_angle(angle)
    state = _valid_state(state)

    col = _TARGET_COL[target_type]
    active_cnt = await db.scalar(
        select(func.count()).select_from(ProductReferenceAsset).where(
            col == target_id, ProductReferenceAsset.archived_at.is_(None)
        )
    )
    if int(active_cnt or 0) >= settings.reference_asset_max_count:
        raise CatalogError(f"参考图数量已达上限 {settings.reference_asset_max_count}")

    ref_dir = _ref_dir(target_type, target_id)
    os.makedirs(ref_dir, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    dest = safe_join_within_root(ref_dir, name)
    tmp = dest + ".part"
    max_bytes = settings.reference_asset_max_mb * 1024 * 1024

    sha = hashlib.sha256()
    written = 0
    head = b""
    dims: tuple[int, int] | None = None
    digest = ""
    try:
        with open(tmp, "wb") as f:
            while True:
                chunk = await stream.read(1024 * 256)
                if not chunk:
                    break
                if not head:
                    head = chunk[:16]
                sha.update(chunk)
                written += len(chunk)
                if written > max_bytes:
                    raise CatalogError(f"图片超过 {settings.reference_asset_max_mb}MB 上限")
                f.write(chunk)
        if written == 0 or not images.looks_like_image(ext, head):
            raise CatalogError("文件内容不是有效图片")
        digest = sha.hexdigest()
        # 同目标重复检测（活动资产内完全相同内容）
        dup = await db.scalar(
            select(ProductReferenceAsset.id).where(
                col == target_id,
                ProductReferenceAsset.sha256 == digest,
                ProductReferenceAsset.archived_at.is_(None),
            ).limit(1)
        )
        if dup is not None:
            raise CatalogConflict("同一目标下已存在完全相同的图片（重复）")
        dims = await images.probe_dimensions(tmp)
        if dims and dims[0] * dims[1] > settings.reference_asset_max_pixels:
            raise CatalogError("图片像素数超过上限（可能为异常大图）")
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

    # 文件已落盘；缩略图 best-effort（失败不阻断，thumbnail_path 置空前端回退原图）
    thumb_rel: str | None = None
    thumb_name = f"{uuid.uuid4().hex}.webp"
    thumb_abs = safe_join_within_root(ref_dir, "thumb", thumb_name)
    if await images.make_thumbnail(dest, thumb_abs, settings.reference_thumbnail_max_dim):
        thumb_rel = _rel(target_type, target_id, "thumb", thumb_name)

    row = ProductReferenceAsset(
        image_path=_rel(target_type, target_id, name),
        thumbnail_path=thumb_rel,
        original_filename=(filename or None),
        content_type=images.CONTENT_TYPE.get(ext),
        media_type=ext,
        file_size=written,
        width=(dims[0] if dims else None),
        height=(dims[1] if dims else None),
        sha256=digest,
        angle=angle,
        state=state,
        quality_status="unchecked",
        source_type="upload",
        is_primary=False,
        sort_order=0,
    )
    setattr(row, f"{target_type}_id", int(target_id))
    if is_primary:
        await _clear_primary(db, target_type, target_id)
        row.is_primary = True
    db.add(row)
    try:
        await db.flush()
        await revision_service.record(
            db, entity_type="reference_asset", entity_id=row.id, action="create",
            after=revision_service.snapshot("reference_asset", row),
            summary=f"上传参考图（{target_type} #{target_id}，角度 {angle}）",
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _best_effort_remove(dest)
        _best_effort_remove(_abs(thumb_rel))
        raise CatalogConflict("参考图写入冲突") from exc
    await db.refresh(row)
    # VIS-AUTO：新参考图入队视觉嵌入（best-effort；sweep 兜底漏发）
    try:
        from app.tasks_client import enqueue_visual_index_target

        enqueue_visual_index_target("reference", row.id)
    except Exception:  # noqa: BLE001 - 入队失败不影响上传结果
        logger.warning("参考图视觉索引入队失败（ref=%s）", row.id)
    return row


async def _clear_primary(db: AsyncSession, target_type: str, target_id: int) -> None:
    """清除该目标当前活动主图标记（同事务，保证主图唯一）。"""
    col_name = f"{target_type}_id"
    await db.execute(
        update(ProductReferenceAsset)
        .where(
            getattr(ProductReferenceAsset, col_name) == target_id,
            ProductReferenceAsset.is_primary.is_(True),
            ProductReferenceAsset.archived_at.is_(None),
        )
        .values(is_primary=False)
    )


def _best_effort_remove(abs_path: str | None) -> None:
    if abs_path and os.path.isfile(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            logger.warning("删除未引用参考图文件失败: %s", abs_path)


# --------------------------------------------------------------------------- #
# 读取 / 更新 / 生命周期 / 删除
# --------------------------------------------------------------------------- #


async def list_references(
    db: AsyncSession, target_type: str, target_id: int, *, include_archived: bool = False
) -> list[ProductReferenceAsset]:
    if target_type not in _TARGET_TYPES:
        raise CatalogError("参考图只能绑定 family / variant / sku")
    col = _TARGET_COL[target_type]
    stmt = select(ProductReferenceAsset).where(col == target_id)
    if not include_archived:
        stmt = stmt.where(ProductReferenceAsset.state.notin_(REFERENCE_HIDDEN_STATES))
    stmt = stmt.order_by(
        ProductReferenceAsset.is_primary.desc(),
        ProductReferenceAsset.sort_order.asc(),
        ProductReferenceAsset.id.asc(),
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_reference(db: AsyncSession, ref_id: int) -> ProductReferenceAsset | None:
    return await db.get(ProductReferenceAsset, ref_id)


async def update_reference(
    db: AsyncSession, asset: ProductReferenceAsset, data: dict
) -> ProductReferenceAsset:
    before = revision_service.snapshot("reference_asset", asset)
    if "angle" in data and data["angle"] is not None:
        asset.angle = _valid_angle(data["angle"])
    if "quality_status" in data and data["quality_status"] is not None:
        asset.quality_status = _valid_quality(data["quality_status"])
    if "state" in data and data["state"] is not None:
        asset.state = _valid_state(data["state"])
        asset.archived_at = utcnow() if asset.state == "archived" else None
    if "description" in data:
        asset.description = (data["description"] or None)
    if "sort_order" in data and data["sort_order"] is not None:
        asset.sort_order = int(data["sort_order"])
    await revision_service.record(
        db, entity_type="reference_asset", entity_id=asset.id, action="update",
        before=before, after=revision_service.snapshot("reference_asset", asset),
        summary="更新参考图元数据",
    )
    return await _commit(db, asset)


async def set_primary(db: AsyncSession, asset: ProductReferenceAsset) -> ProductReferenceAsset:
    """将该图设为其目标的主图（清除同目标其它活动主图，保证唯一）。"""
    if asset.archived_at is not None or asset.state in REFERENCE_HIDDEN_STATES:
        raise CatalogError("已归档/拒绝的参考图不能设为主图")
    before = revision_service.snapshot("reference_asset", asset)
    ttype, tid = _target_of(asset)
    await _clear_primary(db, ttype, tid)
    asset.is_primary = True
    await revision_service.record(
        db, entity_type="reference_asset", entity_id=asset.id, action="set_primary",
        before=before, after=revision_service.snapshot("reference_asset", asset),
        summary=f"设为 {ttype} #{tid} 主参考图",
    )
    return await _commit(db, asset)


async def archive_reference(
    db: AsyncSession, asset: ProductReferenceAsset
) -> ProductReferenceAsset:
    before = revision_service.snapshot("reference_asset", asset)
    asset.state = "archived"
    asset.archived_at = utcnow()
    asset.is_primary = False  # 归档不再作主图
    await revision_service.record(
        db, entity_type="reference_asset", entity_id=asset.id, action="archive",
        before=before, after=revision_service.snapshot("reference_asset", asset),
        summary="归档参考图",
    )
    return await _commit(db, asset)


async def restore_reference(
    db: AsyncSession, asset: ProductReferenceAsset
) -> ProductReferenceAsset:
    if asset.archived_at is None and asset.state != "rejected":
        raise CatalogError("仅归档/拒绝的参考图可恢复")
    before = revision_service.snapshot("reference_asset", asset)
    asset.state = "active"
    asset.archived_at = None
    await revision_service.record(
        db, entity_type="reference_asset", entity_id=asset.id, action="restore",
        before=before, after=revision_service.snapshot("reference_asset", asset),
        summary="恢复参考图",
    )
    return await _commit(db, asset)


async def delete_reference(db: AsyncSession, asset: ProductReferenceAsset) -> None:
    """物理删除：先删库记录，再尽力删 data_dir 派生文件（绝不碰源）。"""
    img_abs = _abs(asset.image_path)
    thumb_abs = _abs(asset.thumbnail_path)
    before = revision_service.snapshot("reference_asset", asset)
    rid = asset.id
    await db.delete(asset)
    await revision_service.record(
        db, entity_type="reference_asset", entity_id=rid, action="delete",
        before=before, summary="物理删除参考图记录",
    )
    await db.commit()
    _best_effort_remove(img_abs)
    _best_effort_remove(thumb_abs)


async def _commit(db: AsyncSession, asset: ProductReferenceAsset) -> ProductReferenceAsset:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CatalogConflict("参考图更新冲突（如主图唯一约束）") from exc
    await db.refresh(asset)
    return asset
