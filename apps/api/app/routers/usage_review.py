"""PR-D 统一使用记录中心路由（注册前缀 /api，见 main.py）。

展示统一、事实分离：summary/items 是只读投影；bulk 逐条走原领域
Service（原状态机 + 原事件审计），绝不直写底层状态字段。
正式使用次数只来自 confirmed FinalVideoUsage；历史证据仅表示
"可能曾使用，次数和成片未知"。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.usage_review import (
    ITEM_TYPES,
    REVIEW_GROUPS,
    SOURCE_STRENGTHS,
    BulkReviewOut,
    BulkReviewRequest,
    ReviewItemDetailOut,
    ReviewListResponse,
    ReviewSummaryOut,
)
from app.services import usage_review_service as svc
from app.services.usage_review_service import ReviewFilters

router = APIRouter(prefix="/usage-review", tags=["usage-review"])


@router.get("/summary", response_model=ReviewSummaryOut)
async def get_summary(db: AsyncSession = Depends(get_db)) -> ReviewSummaryOut:
    """两组计数并列（正式五态 / 历史四态）；绝不返回相加的"总使用次数"。"""
    return await svc.get_summary(db)


@router.get("/items", response_model=ReviewListResponse)
async def list_items(
    item_type: str | None = Query(None),
    review_group: str | None = Query(None),
    source_strength: str | None = Query(None),
    product_family_id: int | None = Query(None),
    product_variant_id: int | None = Query(None),
    asset_id: int | None = Query(None),
    final_video_id: int | None = Query(None),
    source_directory_id: int | None = Query(None),
    created_from: datetime | None = Query(None),
    created_to: datetime | None = Query(None),
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("-created_at"),
    db: AsyncSession = Depends(get_db),
) -> ReviewListResponse:
    if item_type is not None and item_type not in ITEM_TYPES:
        raise HTTPException(status_code=422, detail=f"不支持的 item_type: {item_type}")
    if review_group is not None and review_group not in REVIEW_GROUPS:
        raise HTTPException(status_code=422, detail=f"不支持的 review_group: {review_group}")
    if source_strength is not None and source_strength not in SOURCE_STRENGTHS:
        raise HTTPException(
            status_code=422, detail=f"不支持的 source_strength: {source_strength}"
        )
    filters = ReviewFilters(
        item_type=item_type,
        review_group=review_group,
        source_strength=source_strength,
        product_family_id=product_family_id,
        product_variant_id=product_variant_id,
        asset_id=asset_id,
        final_video_id=final_video_id,
        source_directory_id=source_directory_id,
        created_from=created_from,
        created_to=created_to,
        q=(q or "").strip() or None,
    )
    return await svc.list_items(db, filters, page=page, page_size=page_size, sort=sort)


@router.get("/items/{item_type}/{item_id}", response_model=ReviewItemDetailOut)
async def get_item_detail(
    item_type: str, item_id: int, db: AsyncSession = Depends(get_db)
) -> ReviewItemDetailOut:
    """详情：统一头 + 原始领域数据 + 各自事件时间线（不拼单一事件对象）。"""
    return await svc.get_item_detail(db, item_type, item_id)


@router.post("/bulk", response_model=BulkReviewOut)
async def bulk_review(
    req: BulkReviewRequest, db: AsyncSession = Depends(get_db)
) -> BulkReviewOut:
    """typed bulk：显式 items（≤500）、单一类型批次（混合 422）、
    逐条走原状态机与事件审计；409→skipped、404→failed，明细逐条返回。"""
    return await svc.bulk_review(db, req)
