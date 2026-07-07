"""PR-03B 人工审核路由：有效结果 / 当前审核状态 / 审计事件 / 5 个明确审核动作。

不使用宽泛 PUT /shots/{id}；每个动作走显式状态机；非法转换/版本冲突 → 409，Schema 错误 → 422。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from clipmind_shared.models import Asset, Shot
from clipmind_shared.models.enums import ReviewAction
from clipmind_shared.models.enums import ReviewStatus as RS
from clipmind_shared.review import InvalidReviewTransition
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
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
from app.services import asset_summary, image_review_service, review_service, shot_filter
from app.services.review_service import (
    ReviewConflict,
    ReviewPayload,
    ReviewSchemaError,
)
from app.tasks_client import (
    enqueue_rebuild_asset_level_doc,
    enqueue_rebuild_shot_search_doc,
)

logger = logging.getLogger(__name__)

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
    # 审核已提交 → 入队检索文档重建（确认/修改→人工文档；驳回/无法→排除；重开→回退 AI）。
    # 入队失败不影响审核结果（sweeper/backfill 兜底）。
    try:
        enqueue_rebuild_shot_search_doc(shot_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("入队检索文档重建失败（将由 sweeper/backfill 兜底）: %s", exc)
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


# ===================== IMG-REVIEW：图片素材 AI 理解审核 =====================


class ImageAnalysisViewOut(BaseModel):
    """图片 AI 理解 + 审核状态 + 有效结果（前端一次取全）。"""

    asset_id: int
    ai_status: str | None = None
    ai_result: dict[str, Any] | None = None
    ai_analysis_id: int | None = None
    input_fingerprint: str | None = None
    analyzed_at: datetime | None = None
    review_status: str = "unreviewed"
    confirmed_result: dict[str, Any] | None = None
    reviewer_label: str | None = None
    review_comment: str | None = None
    reviewed_at: datetime | None = None
    lock_version: int = 0
    effective_source: str = "none"  # human | ai | rejected | none
    effective_result: dict[str, Any] | None = None


@router.get("/assets/{asset_id}/image-analysis", response_model=ImageAnalysisViewOut)
async def get_asset_image_analysis_view(
    asset_id: int, response: Response, db: AsyncSession = Depends(get_db)
) -> ImageAnalysisViewOut:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    if asset.media_kind != "image":
        raise HTTPException(status_code=422, detail="仅图片素材有图片理解结果")
    response.headers["Cache-Control"] = "no-store"
    ai = await image_review_service.get_image_analysis(db, asset_id)
    review = await image_review_service.get_image_review_state(db, asset_id)
    source, effective = image_review_service.compute_effective(ai, review)
    return ImageAnalysisViewOut(
        asset_id=asset_id,
        ai_status=(ai.status.value if ai else None),
        ai_result=(dict(ai.parsed_result) if ai and ai.parsed_result else None),
        ai_analysis_id=(ai.id if ai else None),
        input_fingerprint=(ai.input_fingerprint if ai else None),
        analyzed_at=(ai.updated_at if ai else None),
        review_status=(review.review_status.value if review else "unreviewed"),
        confirmed_result=(review.confirmed_result if review else None),
        reviewer_label=(review.reviewer_label if review else None),
        review_comment=(review.review_comment if review else None),
        reviewed_at=(review.reviewed_at if review else None),
        lock_version=(review.lock_version if review else 0),
        effective_source=source,
        effective_result=effective,
    )


@router.post("/assets/{asset_id}/image-review", response_model=ImageAnalysisViewOut)
async def review_asset_image(
    asset_id: int,
    action: str,
    body: ReviewActionIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ImageAnalysisViewOut:
    """图片审核动作（confirm/modify/reject/unable/reopen；乐观锁并发保护）。"""
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    if asset.media_kind != "image":
        raise HTTPException(status_code=422, detail="仅图片素材可做图片审核")
    try:
        act = ReviewAction(action)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"未知审核动作: {action}") from exc
    if act == ReviewAction.MODIFY and not body.confirmed_result:
        raise HTTPException(status_code=422, detail="modify 必须提供 confirmed_result")
    reviewer = (body.reviewer_label or "").strip() or get_settings().review_default_reviewer
    payload = ReviewPayload(
        action=act,
        lock_version=body.lock_version,
        reviewer_label=reviewer[:255],
        comment=body.comment,
        confirmed_result=body.confirmed_result,
        source_ai_analysis_id=body.source_ai_analysis_id,
        source_input_fingerprint=body.source_input_fingerprint,
    )
    try:
        await image_review_service.apply_image_review(db, asset, payload)
    except InvalidReviewTransition as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewConflict as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewSchemaError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=f"结构化结果非法: {exc}") from exc
    # 审核已提交 → 重建素材级检索文档（human 优先 / rejected 不可搜立即生效）。
    # 入队失败不影响审核结果（扫描 sweep 兜底）。
    try:
        enqueue_rebuild_asset_level_doc(asset_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("入队素材文档重建失败（sweep 兜底）: %s", exc)
    return await get_asset_image_analysis_view(asset_id, response, db)
