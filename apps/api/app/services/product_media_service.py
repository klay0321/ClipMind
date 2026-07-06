"""PM：产品素材正式关系服务（docs/PRODUCT_MEDIA.md）。

冻结语义：
- 人工确认 = 正式事实；候选（视觉/文件名/文本）绝不自动写入；
- primary 至多一个（设主自动把旧主降为 related——运营"换主"体验）；
- merged/archived Family 拒绝新增（DRAFT/PAUSED/ACTIVE 允许——未上架产品
  也可整理素材）；variant 必须属于该 family（绝不自动推断）；
- origin=visual_suggestion_confirmed 仅接受 local provider（fake 禁止，422）；
- Shot 有效产品 = 自身 links 若非空，否则继承 asset links（查询期合成）；
- 历史（retired）Shot 的关系保留可查，允许人工修正（响应标记 generation）；
- 批量：显式 ID 列表（≤200），逐条独立处理，返回 completed/skipped/failed
  明细，绝不虚报整批成功。
"""

from __future__ import annotations

from dataclasses import dataclass

from clipmind_shared.constants import PRODUCT_LINK_ORIGINS, PRODUCT_LINK_ROLES
from clipmind_shared.models import (
    Asset,
    ProductFamily,
    ProductMediaLink,
    ProductVariant,
    Shot,
)
from clipmind_shared.models.enums import CatalogStatus
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings

BULK_MAX = 200
# 新增关系被禁止的 Family 生命周期状态
_BLOCKED_FAMILY_STATUS = (CatalogStatus.MERGED, CatalogStatus.ARCHIVED)


@dataclass
class LinkTarget:
    asset: Asset | None = None
    shot: Shot | None = None

    @property
    def kind(self) -> str:
        return "asset" if self.asset is not None else "shot"


async def _load_target(
    db: AsyncSession, *, target_type: str, target_id: int
) -> LinkTarget:
    if target_type == "asset":
        asset = (
            await db.execute(select(Asset).where(Asset.id == target_id))
        ).scalar_one_or_none()
        if asset is None:
            raise HTTPException(status_code=404, detail=f"素材 {target_id} 不存在")
        return LinkTarget(asset=asset)
    if target_type == "shot":
        shot = (
            await db.execute(select(Shot).where(Shot.id == target_id))
        ).scalar_one_or_none()
        if shot is None:
            raise HTTPException(status_code=404, detail=f"镜头 {target_id} 不存在")
        return LinkTarget(shot=shot)
    raise HTTPException(status_code=422, detail=f"未知目标类型: {target_type}")


async def _validate_family(db: AsyncSession, family_id: int) -> ProductFamily:
    fam = (
        await db.execute(select(ProductFamily).where(ProductFamily.id == family_id))
    ).scalar_one_or_none()
    if fam is None:
        raise HTTPException(status_code=404, detail=f"产品 {family_id} 不存在")
    if fam.status in _BLOCKED_FAMILY_STATUS or fam.merged_into_id is not None:
        raise HTTPException(
            status_code=409,
            detail=f"产品处于 {fam.status.value}，不能新增素材关系",
        )
    return fam


async def _validate_variant(
    db: AsyncSession, *, variant_id: int, family_id: int
) -> ProductVariant:
    var = (
        await db.execute(select(ProductVariant).where(ProductVariant.id == variant_id))
    ).scalar_one_or_none()
    if var is None:
        raise HTTPException(status_code=404, detail=f"型号 {variant_id} 不存在")
    if var.family_id != family_id:
        raise HTTPException(
            status_code=422, detail="variant 不属于该产品族（绝不自动推断层级）"
        )
    return var


def _validate_role_origin(role: str, origin: str, settings: Settings) -> None:
    if role not in PRODUCT_LINK_ROLES:
        raise HTTPException(status_code=422, detail=f"未知关系类型: {role}")
    if origin not in PRODUCT_LINK_ORIGINS:
        raise HTTPException(status_code=422, detail=f"未知关系来源: {origin}")
    if origin == "visual_suggestion_confirmed":
        # fake provider 的候选结果禁止落正式关系（冻结安全边界）
        if (settings.visual_embedding_provider or "").lower() != "local":
            raise HTTPException(
                status_code=422,
                detail="视觉候选确认需要 local 视觉 provider（fake 结果不得写入正式关系）",
            )


async def _demote_existing_primary(
    db: AsyncSession, *, asset_id: int | None, shot_id: int | None,
    exclude_link_id: int | None = None,
) -> None:
    """设主自动换主：把同目标现有 primary 降为 related。"""
    stmt = select(ProductMediaLink).where(ProductMediaLink.role == "primary")
    stmt = (
        stmt.where(ProductMediaLink.asset_id == asset_id)
        if asset_id is not None
        else stmt.where(ProductMediaLink.shot_id == shot_id)
    )
    if exclude_link_id is not None:
        stmt = stmt.where(ProductMediaLink.id != exclude_link_id)
    for link in (await db.execute(stmt)).scalars():
        link.role = "related"


async def create_link(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: int,
    family_id: int,
    variant_id: int | None,
    role: str,
    origin: str,
    note: str | None,
    settings: Settings,
    commit: bool = True,
) -> ProductMediaLink:
    _validate_role_origin(role, origin, settings)
    target = await _load_target(db, target_type=target_type, target_id=target_id)
    await _validate_family(db, family_id)
    if variant_id is not None:
        await _validate_variant(db, variant_id=variant_id, family_id=family_id)

    asset_id = target.asset.id if target.asset else None
    shot_id = target.shot.id if target.shot else None
    dup = (
        await db.execute(
            select(ProductMediaLink).where(
                ProductMediaLink.family_id == family_id,
                (
                    ProductMediaLink.asset_id == asset_id
                    if asset_id is not None
                    else ProductMediaLink.shot_id == shot_id
                ),
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(
            status_code=409, detail=f"该目标与产品已存在关系（link {dup.id}）"
        )
    if role == "primary":
        await _demote_existing_primary(db, asset_id=asset_id, shot_id=shot_id)
    from clipmind_shared.db.base import utcnow as _utcnow

    _now = _utcnow()  # created==updated 精确同刻：undo 以此判定"未被修改"
    link = ProductMediaLink(
        asset_id=asset_id,
        shot_id=shot_id,
        family_id=family_id,
        variant_id=variant_id,
        role=role,
        origin=origin,
        actor_label=settings.review_default_reviewer,
        note=note,
        created_at=_now,
        updated_at=_now,
    )
    db.add(link)
    if commit:
        await db.commit()
        await db.refresh(link)
    else:
        await db.flush()
    return link


async def update_link(
    db: AsyncSession,
    link_id: int,
    *,
    role: str | None,
    variant_id: int | None,
    clear_variant: bool,
    note: str | None,
    settings: Settings,
) -> ProductMediaLink:
    link = (
        await db.execute(
            select(ProductMediaLink).where(ProductMediaLink.id == link_id)
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="关系不存在")
    if role is not None:
        if role not in PRODUCT_LINK_ROLES:
            raise HTTPException(status_code=422, detail=f"未知关系类型: {role}")
        if role == "primary":
            await _demote_existing_primary(
                db, asset_id=link.asset_id, shot_id=link.shot_id,
                exclude_link_id=link.id,
            )
        link.role = role
    if clear_variant:
        link.variant_id = None
    elif variant_id is not None:
        await _validate_variant(db, variant_id=variant_id, family_id=link.family_id)
        link.variant_id = variant_id
    if note is not None:
        link.note = note
    link.actor_label = settings.review_default_reviewer
    await db.commit()
    await db.refresh(link)
    return link


async def delete_link(db: AsyncSession, link_id: int) -> None:
    link = (
        await db.execute(
            select(ProductMediaLink).where(ProductMediaLink.id == link_id)
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="关系不存在")
    await db.delete(link)
    await db.commit()


async def bulk_create(
    db: AsyncSession,
    *,
    items: list[dict],
    family_id: int,
    variant_id: int | None,
    role: str,
    origin: str,
    settings: Settings,
) -> dict:
    """批量绑定（显式目标列表；≤BULK_MAX；逐条独立，明细返回）。"""
    if not items:
        raise HTTPException(status_code=422, detail="必须显式选择素材（不允许空选择）")
    if len(items) > BULK_MAX:
        raise HTTPException(
            status_code=422, detail=f"批量上限 {BULK_MAX} 条（当前 {len(items)}）"
        )
    completed: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    for item in items:
        ttype = item.get("target_type")
        tid = item.get("target_id")
        try:
            # savepoint：单条失败只回滚自身，绝不吞掉已成功条目（防虚报）
            async with db.begin_nested():
                link = await create_link(
                    db,
                    target_type=str(ttype),
                    target_id=int(tid),
                    family_id=family_id,
                    variant_id=variant_id,
                    role=role,
                    origin=origin,
                    note=None,
                    settings=settings,
                    commit=False,
                )
            completed.append({"target_type": ttype, "target_id": tid, "link_id": link.id})
        except HTTPException as exc:
            entry = {"target_type": ttype, "target_id": tid, "error": exc.detail}
            (skipped if exc.status_code == 409 else failed).append(entry)
        except Exception as exc:  # noqa: BLE001 —— 单条失败不拖垮整批，也绝不虚报
            failed.append({
                "target_type": ttype, "target_id": tid,
                "error": f"{type(exc).__name__}",
            })
    await db.commit()
    return {"completed": completed, "skipped": skipped, "failed": failed}


async def bulk_delete(db: AsyncSession, *, link_ids: list[int]) -> dict:
    if not link_ids:
        raise HTTPException(status_code=422, detail="必须显式选择关系")
    if len(link_ids) > BULK_MAX:
        raise HTTPException(status_code=422, detail=f"批量上限 {BULK_MAX} 条")
    completed, failed = [], []
    for lid in link_ids:
        link = (
            await db.execute(
                select(ProductMediaLink).where(ProductMediaLink.id == lid)
            )
        ).scalar_one_or_none()
        if link is None:
            failed.append({"link_id": lid, "error": "不存在"})
            continue
        await db.delete(link)
        completed.append({"link_id": lid})
    await db.commit()
    return {"completed": completed, "skipped": [], "failed": failed}


# ---------------------------- 查询侧 ----------------------------


async def asset_links(db: AsyncSession, asset_id: int) -> list[ProductMediaLink]:
    return list(
        (
            await db.execute(
                select(ProductMediaLink)
                .where(ProductMediaLink.asset_id == asset_id)
                .order_by(
                    ProductMediaLink.role.desc(),  # primary 在前（p > r 反序）
                    ProductMediaLink.id,
                )
            )
        ).scalars()
    )


async def shot_links_view(db: AsyncSession, shot_id: int) -> dict:
    """Shot 产品视图：自身关系 + 继承关系 + 有效关系（冻结继承语义）。"""
    shot = (
        await db.execute(select(Shot).where(Shot.id == shot_id))
    ).scalar_one_or_none()
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    own = list(
        (
            await db.execute(
                select(ProductMediaLink)
                .where(ProductMediaLink.shot_id == shot_id)
                .order_by(ProductMediaLink.role.desc(), ProductMediaLink.id)
            )
        ).scalars()
    )
    inherited = await asset_links(db, shot.asset_id)
    return {
        "shot": shot,
        "own": own,
        "inherited": inherited,
        "effective": own if own else inherited,
        "effective_source": "shot_override" if own else "asset_inherited",
    }


async def unassigned_assets(
    db: AsyncSession, *, media_kind: str, page: int, page_size: int
) -> tuple[list[Asset], int]:
    """未绑定任何产品的素材（按类型）。"""
    base = (
        select(Asset)
        .where(
            Asset.media_kind == media_kind,
            ~select(ProductMediaLink.id)
            .where(ProductMediaLink.asset_id == Asset.id)
            .exists(),
        )
        .order_by(Asset.id.desc())
    )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0
    rows = (
        await db.execute(base.offset((page - 1) * page_size).limit(page_size))
    ).scalars()
    return list(rows), int(total)


async def unassigned_shots(
    db: AsyncSession, *, page: int, page_size: int
) -> tuple[list[Shot], int]:
    """未绑定产品的当前代次镜头（自身无 link 且所属 asset 也无 link——
    继承语义下 asset 已绑即视为已标注）。"""
    base = (
        select(Shot)
        .where(
            Shot.retired_at.is_(None),
            ~select(ProductMediaLink.id)
            .where(ProductMediaLink.shot_id == Shot.id)
            .exists(),
            ~select(ProductMediaLink.id)
            .where(ProductMediaLink.asset_id == Shot.asset_id)
            .exists(),
        )
        .order_by(Shot.id.desc())
    )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0
    rows = (
        await db.execute(base.offset((page - 1) * page_size).limit(page_size))
    ).scalars()
    return list(rows), int(total)


# ---------------------------- 工作台聚合 ----------------------------


async def family_summaries(db: AsyncSession) -> list[dict]:
    """产品列表聚合（非 merged/archived 全部 family，含 DRAFT——运营可提前整理）。"""
    from clipmind_shared.models import (
        FinalVideoUsage,
        ProductReferenceAsset,
    )
    from clipmind_shared.models import (
        ProductVariant as PV,
    )
    from clipmind_shared.models.enums import FinalVideoUsageStatus

    fams = (
        await db.execute(
            select(ProductFamily)
            .where(
                ProductFamily.status.notin_(
                    [CatalogStatus.MERGED, CatalogStatus.ARCHIVED]
                ),
                ProductFamily.merged_into_id.is_(None),
            )
            .order_by(ProductFamily.id)
        )
    ).scalars()
    out = []
    for f in fams:
        variant_count = (
            await db.execute(
                select(func.count()).select_from(PV).where(PV.family_id == f.id)
            )
        ).scalar() or 0
        ref_count = (
            await db.execute(
                select(func.count()).select_from(ProductReferenceAsset).where(
                    ProductReferenceAsset.family_id == f.id,
                    ProductReferenceAsset.archived_at.is_(None),
                )
            )
        ).scalar() or 0
        image_count = (
            await db.execute(
                select(func.count())
                .select_from(ProductMediaLink)
                .join(Asset, Asset.id == ProductMediaLink.asset_id)
                .where(
                    ProductMediaLink.family_id == f.id,
                    Asset.media_kind == "image",
                )
            )
        ).scalar() or 0
        video_count = (
            await db.execute(
                select(func.count())
                .select_from(ProductMediaLink)
                .join(Asset, Asset.id == ProductMediaLink.asset_id)
                .where(
                    ProductMediaLink.family_id == f.id,
                    Asset.media_kind == "video",
                )
            )
        ).scalar() or 0
        shot_link_count = (
            await db.execute(
                select(func.count()).select_from(ProductMediaLink).where(
                    ProductMediaLink.family_id == f.id,
                    ProductMediaLink.shot_id.isnot(None),
                )
            )
        ).scalar() or 0
        # 正式使用次数：confirmed usage 的 source_shot 有效产品 = 本 family
        usage_count = (
            await db.execute(
                select(func.count(func.distinct(FinalVideoUsage.id)))
                .select_from(FinalVideoUsage)
                .join(Shot, Shot.id == FinalVideoUsage.source_shot_id)
                .where(
                    FinalVideoUsage.status == FinalVideoUsageStatus.CONFIRMED,
                    _effective_family_exists(f.id),
                )
            )
        ).scalar() or 0
        fv_count = (
            await db.execute(
                select(func.count(func.distinct(FinalVideoUsage.final_video_id)))
                .select_from(FinalVideoUsage)
                .join(Shot, Shot.id == FinalVideoUsage.source_shot_id)
                .where(
                    FinalVideoUsage.status == FinalVideoUsageStatus.CONFIRMED,
                    _effective_family_exists(f.id),
                )
            )
        ).scalar() or 0
        effective_shot_count = (
            await db.execute(
                select(func.count()).select_from(Shot).where(
                    Shot.retired_at.is_(None), _effective_family_exists(f.id)
                )
            )
        ).scalar() or 0
        # 覆盖状态派生（通用规则；顺序即优先级，绝不按产品名硬编码）
        gaps: list[str] = []
        if ref_count == 0:
            gaps.append("缺参考图")
        if int(video_count) == 0:
            gaps.append("缺视频")
        if int(effective_shot_count) == 0:
            gaps.append("缺可用 Shot")
        if int(fv_count) == 0:
            gaps.append("没有最终成片")
        coverage_status = "资料较完整" if not gaps else " / ".join(gaps[:3])
        out.append({
            "family": f,
            "variant_count": int(variant_count),
            "reference_count": int(ref_count),
            "image_count": int(image_count),
            "video_count": int(video_count),
            "shot_link_count": int(shot_link_count),
            "effective_shot_count": int(effective_shot_count),
            "final_video_count": int(fv_count),
            "confirmed_usage_count": int(usage_count),
            "coverage_status": coverage_status,
            "coverage_gaps": gaps,
        })
    return out


def _effective_family_exists(family_id: int):
    """Shot 有效产品 = family 的 SQL 条件（自身 link 优先，否则继承 asset link）。

    有效：EXISTS(shot 自身该 family link)
         OR ( NOT EXISTS(shot 任何自身 link) AND EXISTS(asset 该 family link) )
    """
    own_this = (
        select(ProductMediaLink.id)
        .where(
            ProductMediaLink.shot_id == Shot.id,
            ProductMediaLink.family_id == family_id,
        )
        .exists()
    )
    own_any = (
        select(ProductMediaLink.id)
        .where(ProductMediaLink.shot_id == Shot.id)
        .exists()
    )
    asset_this = (
        select(ProductMediaLink.id)
        .where(
            ProductMediaLink.asset_id == Shot.asset_id,
            ProductMediaLink.family_id == family_id,
        )
        .exists()
    )
    return own_this | (~own_any & asset_this)


async def family_media_items(
    db: AsyncSession, *, family_id: int, kind: str, include_historical: bool,
    page: int, page_size: int,
) -> dict:
    """产品素材详情分页（kind: image|video|shot|final_video）。"""
    await _family_or_404(db, family_id)
    if kind in ("image", "video"):
        base = (
            select(Asset, ProductMediaLink)
            .join(ProductMediaLink, ProductMediaLink.asset_id == Asset.id)
            .where(
                ProductMediaLink.family_id == family_id,
                Asset.media_kind == kind,
            )
            .order_by(ProductMediaLink.role.desc(), Asset.id.desc())
        )
        total = (
            await db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0
        rows = (
            await db.execute(base.offset((page - 1) * page_size).limit(page_size))
        ).all()
        return {"kind": kind, "total": int(total),
                "items": [{"asset": a, "link": lk} for a, lk in rows]}
    if kind == "shot":
        cond = _effective_family_exists(family_id)
        base = select(Shot).where(cond)
        if not include_historical:
            base = base.where(Shot.retired_at.is_(None))
        base = base.order_by(Shot.retired_at.isnot(None), Shot.id.desc())
        total = (
            await db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0
        shots = list(
            (
                await db.execute(
                    base.offset((page - 1) * page_size).limit(page_size)
                )
            ).scalars()
        )
        own_ids = {
            sid
            for (sid,) in (
                await db.execute(
                    select(ProductMediaLink.shot_id).where(
                        ProductMediaLink.shot_id.in_([s.id for s in shots] or [0]),
                        ProductMediaLink.family_id == family_id,
                    )
                )
            ).all()
        }
        return {"kind": kind, "total": int(total),
                "items": [{"shot": s, "source": "shot_override" if s.id in own_ids
                           else "asset_inherited"} for s in shots]}
    if kind == "final_video":
        from clipmind_shared.models import FinalVideo, FinalVideoUsage
        from clipmind_shared.models.enums import FinalVideoUsageStatus

        base = (
            select(FinalVideo)
            .distinct()
            .join(FinalVideoUsage, FinalVideoUsage.final_video_id == FinalVideo.id)
            .join(Shot, Shot.id == FinalVideoUsage.source_shot_id)
            .where(
                FinalVideoUsage.status == FinalVideoUsageStatus.CONFIRMED,
                _effective_family_exists(family_id),
            )
            .order_by(FinalVideo.id.desc())
        )
        total = (
            await db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0
        fvs = list(
            (await db.execute(base.offset((page - 1) * page_size).limit(page_size)))
            .scalars()
        )
        return {"kind": kind, "total": int(total), "items": [{"final_video": v} for v in fvs]}
    raise HTTPException(status_code=422, detail=f"未知素材类型: {kind}")


async def _family_or_404(db: AsyncSession, family_id: int) -> ProductFamily:
    fam = (
        await db.execute(select(ProductFamily).where(ProductFamily.id == family_id))
    ).scalar_one_or_none()
    if fam is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    return fam


# ---------------------------- OPS：操作审计 + 撤销 ----------------------------


async def record_operation(
    db: AsyncSession, *, kind: str, family_id: int | None, role: str | None,
    origin: str | None, actor_label: str | None, requested: int,
    completed: list, skipped: list, failed: list,
    created_link_ids: list[int] | None, detail: dict | None = None,
    commit: bool = True,
):
    """append-only 操作事件（撤销依据与运营审计；不复制素材事实）。"""
    from clipmind_shared.models import ProductMediaOperation

    op = ProductMediaOperation(
        kind=kind, family_id=family_id, role=role, origin=origin,
        actor_label=actor_label, requested_count=requested,
        completed_count=len(completed), skipped_count=len(skipped),
        failed_count=len(failed), created_link_ids=created_link_ids,
        detail=detail,
    )
    db.add(op)
    if commit:
        await db.commit()
        await db.refresh(op)
    else:
        await db.flush()
    return op


async def list_operations(db: AsyncSession, *, page: int, page_size: int) -> dict:
    from clipmind_shared.models import ProductMediaOperation

    base = select(ProductMediaOperation).order_by(ProductMediaOperation.id.desc())
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0
    rows = list(
        (await db.execute(base.offset((page - 1) * page_size).limit(page_size)))
        .scalars()
    )
    return {"total": int(total), "items": rows}


async def undo_operation(db: AsyncSession, operation_id: int, *, settings) -> dict:
    """撤销一次绑定操作：只删该批创建、此后未被修改且仍存在的关系。

    - 被后续 PATCH 过（updated_at != created_at）或已被删除的 → 记入不可撤销明细；
    - 不删媒体、不回滚产品目录；undo 自身落一行 kind=undo 事件（append-only）。
    """
    from clipmind_shared.models import ProductMediaOperation

    op = (
        await db.execute(
            select(ProductMediaOperation).where(ProductMediaOperation.id == operation_id)
        )
    ).scalar_one_or_none()
    if op is None:
        raise HTTPException(status_code=404, detail="操作不存在")
    if op.kind not in ("single_link", "bulk_link"):
        raise HTTPException(status_code=422, detail=f"{op.kind} 操作不支持撤销")
    if op.undone_at is not None:
        raise HTTPException(status_code=409, detail="该操作已被撤销")
    link_ids = list(op.created_link_ids or [])
    removed: list[int] = []
    kept: list[dict] = []
    for lid in link_ids:
        link = (
            await db.execute(
                select(ProductMediaLink).where(ProductMediaLink.id == lid)
            )
        ).scalar_one_or_none()
        if link is None:
            kept.append({"link_id": lid, "reason": "已被删除"})
            continue
        if link.updated_at != link.created_at:
            kept.append({"link_id": lid, "reason": "创建后已被修改（role/variant 变更）"})
            continue
        await db.delete(link)
        removed.append(lid)
    undo_op = await record_operation(
        db, kind="undo", family_id=op.family_id, role=op.role, origin=op.origin,
        actor_label=settings.review_default_reviewer, requested=len(link_ids),
        completed=removed, skipped=kept, failed=[],
        created_link_ids=None,
        detail={"undo_of": op.id, "removed_link_ids": removed, "kept": kept},
        commit=False,
    )
    op.undone_at = utcnow_op()
    op.undone_by_operation_id = None  # flush 后补
    op.undone_detail = {"removed": removed, "kept": kept}
    await db.flush()
    op.undone_by_operation_id = undo_op.id
    await db.commit()
    return {"undo_operation_id": undo_op.id, "removed_link_ids": removed,
            "kept": kept, "removed_count": len(removed), "kept_count": len(kept)}


def utcnow_op():
    from clipmind_shared.db.base import utcnow

    return utcnow()


# ---------------------------- OPS：分组未标注队列 ----------------------------


async def unassigned_grouped(
    db: AsyncSession, *, kind: str, group_by: str, limit_per_group: int = 6,
    max_items: int = 500,
) -> dict:
    """未标注素材分组视图（directory | suggested_family | none）。

    仅 image/video（shot 无目录语义，用 suggested_family 需按 asset 归并——
    v1 shot 按所属 asset 目录分组）。每组返回代表项 + 全量 target 列表
    （≤200/组，供整组显式选择——绝不隐式全库）。
    """
    from app.services.product_media_suggestions import suggest_for_assets_batch

    if kind in ("image", "video"):
        assets, _total = await unassigned_assets(
            db, media_kind=kind, page=1, page_size=max_items
        )
        targets = [{"target_type": "asset", "target_id": a.id, "asset": a}
                   for a in assets]
    elif kind == "shot":
        shots, _total = await unassigned_shots(db, page=1, page_size=max_items)
        asset_ids = {s.asset_id for s in shots}
        amap = {
            a.id: a
            for a in (
                await db.execute(select(Asset).where(Asset.id.in_(asset_ids or {0})))
            ).scalars()
        }
        targets = [{"target_type": "shot", "target_id": s.id, "asset": amap.get(s.asset_id),
                    "shot": s} for s in shots]
    else:
        raise HTTPException(status_code=422, detail=f"未知素材类型: {kind}")

    sugg_map: dict[int, list[dict]] = {}
    if group_by == "suggested_family" or True:  # 候选注入总是需要（组卡展示）
        uniq_assets = {t["asset"].id: t["asset"] for t in targets if t["asset"]}
        sugg_map = await suggest_for_assets_batch(db, list(uniq_assets.values()))

    groups: dict[str, dict] = {}
    for t in targets:
        asset = t["asset"]
        suggestions = sugg_map.get(asset.id, []) if asset else []
        if group_by == "suggested_family":
            if suggestions:
                top = suggestions[0]
                gkey = f"family:{top['family_id']}"
                glabel = top["family_name"]
                gmeta = {"family_id": top["family_id"],
                         "family_code": top["family_code"],
                         "suggestion_type": top["suggestion_type"]}
            else:
                gkey, glabel, gmeta = "none", "无候选", {}
        elif group_by == "directory":
            rel = (asset.relative_path if asset else "").replace("\\", "/")
            d = rel.rsplit("/", 1)[0] if "/" in rel else "（根目录）"
            gkey, glabel, gmeta = f"dir:{d}", d, {}
        else:
            gkey, glabel, gmeta = "all", "全部", {}
        g = groups.setdefault(gkey, {
            "key": gkey, "label": glabel, "meta": gmeta, "count": 0,
            "targets": [], "preview": [], "suggested": [],
        })
        g["count"] += 1
        if len(g["targets"]) < 200:
            g["targets"].append({"target_type": t["target_type"],
                                 "target_id": t["target_id"]})
        if len(g["preview"]) < limit_per_group:
            entry = {"target_type": t["target_type"], "target_id": t["target_id"],
                     "suggestions": suggestions[:2]}
            if asset:
                entry["asset_id"] = asset.id
                entry["filename"] = asset.filename
            if "shot" in t:
                entry["shot_id"] = t["shot"].id
                entry["sequence_no"] = t["shot"].sequence_no
            g["preview"].append(entry)
        if suggestions and not g["suggested"]:
            g["suggested"] = suggestions[:1]
    ordered = sorted(groups.values(), key=lambda g: (-g["count"], g["label"]))
    return {"kind": kind, "group_by": group_by, "total_items": len(targets),
            "truncated": len(targets) >= max_items, "groups": ordered}


async def product_names_for_assets(
    db: AsyncSession, asset_ids: list[int]
) -> dict[int, list[str]]:
    """AAP：素材列表行内产品名（真实 product_media_link，替代硬编码占位）。"""
    if not asset_ids:
        return {}
    rows = await db.execute(
        select(ProductMediaLink.asset_id, ProductFamily.name_zh)
        .join(ProductFamily, ProductFamily.id == ProductMediaLink.family_id)
        .where(ProductMediaLink.asset_id.in_(asset_ids))
        .order_by(ProductMediaLink.asset_id, ProductMediaLink.id)
    )
    out: dict[int, list[str]] = {}
    for asset_id, name in rows:
        names = out.setdefault(int(asset_id), [])
        if name not in names:
            names.append(name)
    return out
