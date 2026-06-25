"""PR-03B 人工审核路由：有效结果 / 当前审核状态 / 审计事件 / 5 个明确审核动作。

不使用宽泛 PUT /shots/{id}；每个动作走显式状态机；非法转换/版本冲突 → 409，Schema 错误 → 422。
"""

from __future__ import annotations

from clipmind_shared.models import Asset, Shot
from clipmind_shared.models.enums import ReviewAction
from clipmind_shared.models.enums import ReviewStatus as RS
from clipmind_shared.review import InvalidReviewTransition
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.schemas.common import Page
from app.schemas.review import (
    AssetSummaryOut,
    EffectiveResultOut,
    ReviewActionIn,
    ReviewEventOut,
    ReviewStateOut,
)
from app.schemas.shot import ShotOut, to_shot_out
from app.services import asset_summary, review_service, shot_filter
from app.services.review_service import (
    ReviewConflict,
    ReviewPayload,
    ReviewSchemaError,
)

router = APIRouter(tags=["review"])


async def _shot_or_404(db: AsyncSession, shot_id: int) -> Shot:
    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    return shot


@router.get("/shots/{shot_id}/effective-result", response_model=EffectiveResultOut)
async def get_effective(
    shot_id: int, db: AsyncSession = Depends(get_db)
) -> EffectiveResultOut:
    shot = await _shot_or_404(db, shot_id)
    view = await review_service.compute_effective(db, shot)
    return EffectiveResultOut(**view.__dict__)


@router.get("/shots/{shot_id}/review", response_model=ReviewStateOut)
async def get_review(shot_id: int, db: AsyncSession = Depends(get_db)) -> ReviewStateOut:
    shot = await _shot_or_404(db, shot_id)
    row = await review_service.get_review_state(db, shot.id, shot.generation)
    if row is None:
        # 合成默认（未审核，lock_version=0，供首次审核使用）
        return ReviewStateOut(
            shot_id=shot.id, shot_generation=shot.generation,
            review_status=RS.UNREVIEWED, lock_version=0,
        )
    return ReviewStateOut.model_validate(row)


@router.get("/shots/{shot_id}/review-events", response_model=list[ReviewEventOut])
async def get_review_events(
    shot_id: int, db: AsyncSession = Depends(get_db)
) -> list[ReviewEventOut]:
    await _shot_or_404(db, shot_id)
    events = await review_service.list_review_events(db, shot_id)
    return [ReviewEventOut.model_validate(e) for e in events]


async def _do_action(
    shot_id: int, action: ReviewAction, body: ReviewActionIn, db: AsyncSession
) -> ReviewStateOut:
    shot = await _shot_or_404(db, shot_id)
    if action == ReviewAction.MODIFY and body.confirmed_result is None:
        raise HTTPException(status_code=422, detail="modify 必须提供 confirmed_result")
    reviewer = (body.reviewer_label or "").strip() or get_settings().review_default_reviewer
    payload = ReviewPayload(
        action=action,
        lock_version=body.lock_version,
        reviewer_label=reviewer[:255],
        comment=body.comment,
        confirmed_result=body.confirmed_result,
        confirmed_product_id=body.confirmed_product_id,
        source_ai_analysis_id=body.source_ai_analysis_id,
        source_input_fingerprint=body.source_input_fingerprint,
    )
    try:
        state = await review_service.apply_review(db, shot, payload)
    except InvalidReviewTransition as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewConflict as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewSchemaError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=f"结构化结果非法: {exc}") from exc
    return ReviewStateOut.model_validate(state)


@router.post("/shots/{shot_id}/review/confirm", response_model=ReviewStateOut)
async def review_confirm(
    shot_id: int, body: ReviewActionIn, db: AsyncSession = Depends(get_db)
) -> ReviewStateOut:
    return await _do_action(shot_id, ReviewAction.CONFIRM, body, db)


@router.post("/shots/{shot_id}/review/modify", response_model=ReviewStateOut)
async def review_modify(
    shot_id: int, body: ReviewActionIn, db: AsyncSession = Depends(get_db)
) -> ReviewStateOut:
    return await _do_action(shot_id, ReviewAction.MODIFY, body, db)


@router.post("/shots/{shot_id}/review/reject", response_model=ReviewStateOut)
async def review_reject(
    shot_id: int, body: ReviewActionIn, db: AsyncSession = Depends(get_db)
) -> ReviewStateOut:
    return await _do_action(shot_id, ReviewAction.REJECT, body, db)


@router.post("/shots/{shot_id}/review/unable", response_model=ReviewStateOut)
async def review_unable(
    shot_id: int, body: ReviewActionIn, db: AsyncSession = Depends(get_db)
) -> ReviewStateOut:
    return await _do_action(shot_id, ReviewAction.UNABLE, body, db)


@router.post("/shots/{shot_id}/review/reopen", response_model=ReviewStateOut)
async def review_reopen(
    shot_id: int, body: ReviewActionIn, db: AsyncSession = Depends(get_db)
) -> ReviewStateOut:
    return await _do_action(shot_id, ReviewAction.REOPEN, body, db)


# ---------------- 素材审核汇总 + 镜头后端筛选 ----------------


@router.get("/assets/{asset_id}/review-summary", response_model=AssetSummaryOut)
async def review_summary(
    asset_id: int, db: AsyncSession = Depends(get_db)
) -> AssetSummaryOut:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    s = await asset_summary.compute_summary(db, asset)
    return AssetSummaryOut(**s.__dict__)


@router.get("/shot-search", response_model=Page[ShotOut])
async def shot_search(
    asset_id: int | None = None,
    review_status: RS | None = None,
    has_ai_result: bool | None = None,
    stale: bool | None = None,
    product_id: int | None = None,
    scene: str | None = None,
    action: str | None = None,
    shot_type: str | None = None,
    marketing_use: str | None = None,
    quality: str | None = None,
    risk: str | None = None,
    include_excluded: bool = False,
    sort: str = "sequence",
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Page[ShotOut]:
    rows, total = await shot_filter.filter_shots(
        db, asset_id=asset_id, review_status=review_status, has_ai_result=has_ai_result,
        stale=stale, product_id=product_id, scene=scene, action=action,
        shot_type=shot_type, marketing_use=marketing_use, quality=quality, risk=risk,
        include_excluded=include_excluded, sort=sort, page=page, page_size=page_size,
    )
    names: dict[int, str] = {}
    aids = {r.asset_id for r in rows}
    if aids:
        for aid, fname in (
            await db.execute(select(Asset.id, Asset.filename).where(Asset.id.in_(aids)))
        ).all():
            names[aid] = fname
    return Page[ShotOut](
        items=[to_shot_out(r, names.get(r.asset_id, "")) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
