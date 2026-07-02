"""PR-B 使用引用（Usage）顶级路由（注册前缀 /api，见 main.py）。

Usage 查询 / 元信息 PATCH / confirm / reject / revoke / restore-proposal +
Occurrence 列表/新增/修改/删除 + append-only 事件查询 + 批量镜头使用计数。

状态语义（唯一计数口径）：只有 confirmed 计入正式使用次数；
proposed/suspected/rejected/revoked 一律不计数。事件与状态变更同事务。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.final_video import (
    OccurrenceCreateRequest,
    OccurrenceListResponse,
    OccurrenceOut,
    OccurrenceUpdateRequest,
    ShotUsageCountsResponse,
    UsageActionRequest,
    UsageEventListResponse,
    UsageEventOut,
    UsageOut,
    UsageUpdateRequest,
)
from app.services import final_video_service

router = APIRouter(prefix="/final-video-usages", tags=["final-video-usages"])
occurrence_router = APIRouter(
    prefix="/final-video-usage-occurrences", tags=["final-video-usages"]
)
summary_router = APIRouter(tags=["final-video-usages"])


async def _usage_out(db: AsyncSession, usage) -> UsageOut:
    return (await final_video_service._to_usage_outs(db, [usage]))[0]


@router.get("/{usage_id}", response_model=UsageOut)
async def get_usage(usage_id: int, db: AsyncSession = Depends(get_db)) -> UsageOut:
    usage = await final_video_service.get_usage_or_404(db, usage_id)
    return await _usage_out(db, usage)


@router.patch("/{usage_id}", response_model=UsageOut)
async def update_usage(
    usage_id: int, req: UsageUpdateRequest, db: AsyncSession = Depends(get_db)
) -> UsageOut:
    usage = await final_video_service.update_usage(db, usage_id, req)
    return await _usage_out(db, usage)


@router.post("/{usage_id}/confirm", response_model=UsageOut)
async def confirm_usage(
    usage_id: int,
    req: UsageActionRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> UsageOut:
    usage = await final_video_service.confirm_usage(
        db,
        usage_id,
        actor_label=req.actor_label if req else None,
        note=req.note if req else None,
    )
    return await _usage_out(db, usage)


@router.post("/{usage_id}/reject", response_model=UsageOut)
async def reject_usage(
    usage_id: int,
    req: UsageActionRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> UsageOut:
    usage = await final_video_service.reject_usage(
        db,
        usage_id,
        actor_label=req.actor_label if req else None,
        note=req.note if req else None,
    )
    return await _usage_out(db, usage)


@router.post("/{usage_id}/revoke", response_model=UsageOut)
async def revoke_usage(
    usage_id: int,
    req: UsageActionRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> UsageOut:
    usage = await final_video_service.revoke_usage(
        db,
        usage_id,
        actor_label=req.actor_label if req else None,
        note=req.note if req else None,
    )
    return await _usage_out(db, usage)


@router.post("/{usage_id}/restore-proposal", response_model=UsageOut)
async def restore_usage_proposal(
    usage_id: int,
    req: UsageActionRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> UsageOut:
    usage = await final_video_service.restore_usage_proposal(
        db,
        usage_id,
        actor_label=req.actor_label if req else None,
        note=req.note if req else None,
    )
    return await _usage_out(db, usage)


# ============================ Occurrence ============================


@router.get("/{usage_id}/occurrences", response_model=OccurrenceListResponse)
async def list_occurrences(
    usage_id: int, db: AsyncSession = Depends(get_db)
) -> OccurrenceListResponse:
    rows = await final_video_service.list_occurrences(db, usage_id)
    return OccurrenceListResponse(items=[OccurrenceOut.model_validate(o) for o in rows])


@router.post(
    "/{usage_id}/occurrences",
    response_model=OccurrenceOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_occurrence(
    usage_id: int, req: OccurrenceCreateRequest, db: AsyncSession = Depends(get_db)
) -> OccurrenceOut:
    occ = await final_video_service.create_occurrence(db, usage_id, req)
    return OccurrenceOut.model_validate(occ)


@occurrence_router.patch("/{occurrence_id}", response_model=OccurrenceOut)
async def update_occurrence(
    occurrence_id: int,
    req: OccurrenceUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> OccurrenceOut:
    occ = await final_video_service.update_occurrence(db, occurrence_id, req)
    return OccurrenceOut.model_validate(occ)


@occurrence_router.delete("/{occurrence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_occurrence(
    occurrence_id: int, db: AsyncSession = Depends(get_db)
):
    await final_video_service.delete_occurrence(db, occurrence_id)


# ============================ 事件 / 批量计数 ============================


@router.get("/{usage_id}/events", response_model=UsageEventListResponse)
async def list_usage_events(
    usage_id: int, db: AsyncSession = Depends(get_db)
) -> UsageEventListResponse:
    rows = await final_video_service.list_usage_events(db, usage_id)
    return UsageEventListResponse(items=[UsageEventOut.model_validate(e) for e in rows])


@summary_router.get("/shot-usage-summaries", response_model=ShotUsageCountsResponse)
async def get_shot_usage_counts(
    shot_ids: str = Query(..., description="逗号分隔的 shot id 列表（≤200 个）"),
    db: AsyncSession = Depends(get_db),
) -> ShotUsageCountsResponse:
    """批量镜头使用计数（卡片徽标；只读派生值）。"""
    try:
        ids = [int(x) for x in shot_ids.split(",") if x.strip()]
    except ValueError:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="shot_ids 必须是逗号分隔的整数") from None
    ids = ids[:200]
    items = await final_video_service.get_shot_usage_counts(db, ids)
    return ShotUsageCountsResponse(items=items)
