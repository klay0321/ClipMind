"""PM：产品素材工作台 API（/api/product-media/*；人工确认 = 正式事实）。

零 AI 依赖：全部端点在视觉 provider 关闭时完整可用；候选端点只返回
确定性建议（文件名/目录/别名/已有 AI 文本），绝不自动写关系。
"""

from __future__ import annotations

from clipmind_shared.models import ProductFamily, ProductMediaLink, ProductVariant
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas.product_media import (
    BulkDeleteIn,
    BulkLinkIn,
    BulkResultOut,
    FamilySummaryOut,
    LinkCreateIn,
    LinkOut,
    LinkUpdateIn,
    ShotLinksViewOut,
    SuggestionOut,
)
from app.services import product_media_service as svc
from app.services.product_media_suggestions import suggest_for_target

router = APIRouter(prefix="/product-media", tags=["product-media"])


async def _link_out(db: AsyncSession, link: ProductMediaLink) -> LinkOut:
    fam = (
        await db.execute(
            select(ProductFamily).where(ProductFamily.id == link.family_id)
        )
    ).scalar_one_or_none()
    var = None
    if link.variant_id is not None:
        var = (
            await db.execute(
                select(ProductVariant).where(ProductVariant.id == link.variant_id)
            )
        ).scalar_one_or_none()
    return LinkOut(
        id=link.id,
        asset_id=link.asset_id,
        shot_id=link.shot_id,
        family_id=link.family_id,
        family_name=fam.name_zh if fam else None,
        family_code=fam.code if fam else None,
        variant_id=link.variant_id,
        variant_name=(var.name_zh if var and hasattr(var, "name_zh") else None),
        role=link.role,
        origin=link.origin,
        actor_label=link.actor_label,
        note=link.note,
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


@router.post("/links", response_model=LinkOut, status_code=201)
async def create_link(
    body: LinkCreateIn,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LinkOut:
    link = await svc.create_link(
        db,
        target_type=body.target_type,
        target_id=body.target_id,
        family_id=body.family_id,
        variant_id=body.variant_id,
        role=body.role,
        origin=body.origin,
        note=body.note,
        settings=settings,
    )
    await svc.record_operation(
        db, kind="single_link", family_id=body.family_id, role=body.role,
        origin=body.origin, actor_label=settings.review_default_reviewer,
        requested=1, completed=[link.id], skipped=[], failed=[],
        created_link_ids=[link.id],
    )
    return await _link_out(db, link)


@router.patch("/links/{link_id}", response_model=LinkOut)
async def update_link(
    link_id: int,
    body: LinkUpdateIn,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LinkOut:
    link = await svc.update_link(
        db, link_id,
        role=body.role, variant_id=body.variant_id,
        clear_variant=body.clear_variant, note=body.note, settings=settings,
    )
    return await _link_out(db, link)


@router.delete("/links/{link_id}", status_code=204, response_class=Response)
async def delete_link(link_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    await svc.delete_link(db, link_id)
    return Response(status_code=204)


@router.post("/links/bulk", response_model=BulkResultOut)
async def bulk_create(
    body: BulkLinkIn,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BulkResultOut:
    result = await svc.bulk_create(
        db,
        items=body.items,
        family_id=body.family_id,
        variant_id=body.variant_id,
        role=body.role,
        origin=body.origin,
        settings=settings,
    )
    op = await svc.record_operation(
        db, kind="bulk_link", family_id=body.family_id, role=body.role,
        origin=body.origin, actor_label=settings.review_default_reviewer,
        requested=len(body.items), completed=result["completed"],
        skipped=result["skipped"], failed=result["failed"],
        created_link_ids=[c["link_id"] for c in result["completed"]],
    )
    return BulkResultOut(**result, operation_id=op.id)


@router.post("/links/bulk-delete", response_model=BulkResultOut)
async def bulk_delete(
    body: BulkDeleteIn, db: AsyncSession = Depends(get_db)
) -> BulkResultOut:
    result = await svc.bulk_delete(db, link_ids=body.link_ids)
    return BulkResultOut(**result)


@router.get("/summary", response_model=list[FamilySummaryOut])
async def summary(db: AsyncSession = Depends(get_db)) -> list[FamilySummaryOut]:
    from clipmind_shared.models import ProductOnboardingReview

    rows = await svc.family_summaries(db)
    ob_map = {
        fid: status
        for fid, status in (
            await db.execute(
                select(
                    ProductOnboardingReview.family_id,
                    ProductOnboardingReview.status,
                ).where(
                    ProductOnboardingReview.family_id.in_(
                        [r["family"].id for r in rows] or [0]
                    )
                )
            )
        ).all()
    }
    return [
        FamilySummaryOut(
            family_id=r["family"].id,
            code=r["family"].code,
            name_zh=r["family"].name_zh,
            status=r["family"].status.value,
            onboarding_status=ob_map.get(r["family"].id),
            variant_count=r["variant_count"],
            reference_count=r["reference_count"],
            image_count=r["image_count"],
            video_count=r["video_count"],
            shot_link_count=r["shot_link_count"],
            effective_shot_count=r["effective_shot_count"],
            final_video_count=r["final_video_count"],
            confirmed_usage_count=r["confirmed_usage_count"],
            coverage_status=r["coverage_status"],
            coverage_gaps=r["coverage_gaps"],
        )
        for r in rows
    ]


@router.get("/families/{family_id}/items")
async def family_items(
    family_id: int,
    kind: str = Query("image"),
    include_historical: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    data = await svc.family_media_items(
        db, family_id=family_id, kind=kind,
        include_historical=include_historical, page=page, page_size=page_size,
    )
    items = []
    for it in data["items"]:
        if "asset" in it:
            a, link = it["asset"], it["link"]
            items.append({
                "type": data["kind"],
                "asset_id": a.id,
                "filename": a.filename,
                "media_kind": a.media_kind,
                "duration": a.duration,
                "status": a.status.value,
                "link": (await _link_out(db, link)).model_dump(mode="json"),
            })
        elif "shot" in it:
            s = it["shot"]
            items.append({
                "type": "shot",
                "shot_id": s.id,
                "asset_id": s.asset_id,
                "generation": s.generation,
                "is_historical": s.retired_at is not None,
                "sequence_no": s.sequence_no,
                "duration": s.duration,
                "source": it["source"],
            })
        else:
            v = it["final_video"]
            items.append({
                "type": "final_video",
                "final_video_id": v.id,
                "title": v.title,
                "status": v.status.value if hasattr(v.status, "value") else str(v.status),
            })
    return {"kind": data["kind"], "total": data["total"], "page": page,
            "page_size": page_size, "items": items}


@router.get("/unassigned")
async def unassigned(
    kind: str = Query("image"),  # image | video | shot
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if kind in ("image", "video"):
        assets, total = await svc.unassigned_assets(
            db, media_kind=kind, page=page, page_size=page_size
        )
        return {
            "kind": kind, "total": total, "page": page, "page_size": page_size,
            "items": [
                {"type": kind, "asset_id": a.id, "filename": a.filename,
                 "media_kind": a.media_kind, "duration": a.duration,
                 "status": a.status.value}
                for a in assets
            ],
        }
    if kind == "shot":
        shots, total = await svc.unassigned_shots(db, page=page, page_size=page_size)
        return {
            "kind": kind, "total": total, "page": page, "page_size": page_size,
            "items": [
                {"type": "shot", "shot_id": s.id, "asset_id": s.asset_id,
                 "generation": s.generation, "sequence_no": s.sequence_no,
                 "duration": s.duration}
                for s in shots
            ],
        }
    from fastapi import HTTPException

    raise HTTPException(status_code=422, detail=f"未知素材类型: {kind}")


@router.get("/unassigned/counts")
async def unassigned_counts(db: AsyncSession = Depends(get_db)) -> dict:
    return await svc.unassigned_counts(db)


@router.get("/unassigned/groups")
async def unassigned_groups(
    kind: str = Query("image"),
    group_by: str = Query("suggested_family"),  # suggested_family | directory | none
    db: AsyncSession = Depends(get_db),
) -> dict:
    if group_by not in ("suggested_family", "directory", "none"):
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail=f"未知分组方式: {group_by}")
    return await svc.unassigned_grouped(db, kind=kind, group_by=group_by)


@router.get("/operations")
async def operations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    data = await svc.list_operations(db, page=page, page_size=page_size)
    return {
        "total": data["total"], "page": page, "page_size": page_size,
        "items": [
            {
                "id": o.id, "kind": o.kind, "family_id": o.family_id,
                "role": o.role, "origin": o.origin, "actor_label": o.actor_label,
                "requested_count": o.requested_count,
                "completed_count": o.completed_count,
                "skipped_count": o.skipped_count, "failed_count": o.failed_count,
                "undone_at": o.undone_at.isoformat() if o.undone_at else None,
                "undoable": (
                    o.kind in ("single_link", "bulk_link")
                    and o.undone_at is None and bool(o.created_link_ids)
                ),
                "created_at": o.created_at.isoformat(),
                "detail": o.detail,
            }
            for o in data["items"]
        ],
    }


@router.post("/operations/{operation_id}/undo")
async def undo(
    operation_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    return await svc.undo_operation(db, operation_id, settings=settings)


@router.get("/assets/{asset_id}/links", response_model=list[LinkOut])
async def asset_links(
    asset_id: int, db: AsyncSession = Depends(get_db)
) -> list[LinkOut]:
    links = await svc.asset_links(db, asset_id)
    return [await _link_out(db, link) for link in links]


@router.get("/shots/{shot_id}/links", response_model=ShotLinksViewOut)
async def shot_links(
    shot_id: int, db: AsyncSession = Depends(get_db)
) -> ShotLinksViewOut:
    view = await svc.shot_links_view(db, shot_id)
    shot = view["shot"]
    return ShotLinksViewOut(
        shot_id=shot.id,
        generation=shot.generation,
        is_historical=shot.retired_at is not None,
        effective_source=view["effective_source"],
        own=[await _link_out(db, x) for x in view["own"]],
        inherited=[await _link_out(db, x) for x in view["inherited"]],
        effective=[await _link_out(db, x) for x in view["effective"]],
    )


@router.get("/suggestions", response_model=list[SuggestionOut])
async def suggestions(
    target_type: str = Query(...),
    target_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
) -> list[SuggestionOut]:
    return [
        SuggestionOut(**s)
        for s in await suggest_for_target(
            db, target_type=target_type, target_id=target_id
        )
    ]


@router.post("/visual-candidates/{candidate_id}/dismiss")
async def dismiss_visual_candidate(
    candidate_id: int, db: AsyncSession = Depends(get_db)
) -> dict:
    """人工拒绝一条视觉候选：dismissed 是人工事实，重算不会复活该组合。"""
    from clipmind_shared.models import VisualProductCandidate
    from fastapi import HTTPException

    row = await db.get(VisualProductCandidate, candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="视觉候选不存在")
    if row.status != "pending":
        raise HTTPException(
            status_code=409, detail=f"候选已处理（status={row.status}）"
        )
    row.status = "dismissed"
    await db.commit()
    return {"id": row.id, "status": row.status}
