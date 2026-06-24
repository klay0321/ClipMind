"""Shot 服务：镜头列表/详情、素材镜头统计与最近分析运行。"""

from __future__ import annotations

from collections.abc import Sequence

from clipmind_shared.models import Asset, MediaProcessingRun, Shot
from clipmind_shared.models.enums import ShotStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def list_shots(
    db: AsyncSession,
    *,
    asset_id: int | None = None,
    status: ShotStatus | None = ShotStatus.READY,
    page: int = 1,
    page_size: int = 24,
) -> tuple[Sequence[Shot], int]:
    filters = []
    if asset_id is not None:
        filters.append(Shot.asset_id == asset_id)
    if status is not None:
        filters.append(Shot.status == status)

    count_stmt = select(func.count()).select_from(Shot)
    list_stmt = select(Shot).order_by(Shot.asset_id.desc(), Shot.sequence_no.asc())
    for f in filters:
        count_stmt = count_stmt.where(f)
        list_stmt = list_stmt.where(f)

    total = (await db.execute(count_stmt)).scalar_one()
    offset = (page - 1) * page_size
    list_stmt = list_stmt.offset(offset).limit(page_size)
    items = (await db.execute(list_stmt)).scalars().all()
    return items, total


async def get_shot(db: AsyncSession, shot_id: int) -> Shot | None:
    return await db.get(Shot, shot_id)


async def count_ready_shots(db: AsyncSession, asset_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(Shot)
        .where(Shot.asset_id == asset_id, Shot.status == ShotStatus.READY)
    )
    return (await db.execute(stmt)).scalar_one()


async def ready_counts_for_assets(
    db: AsyncSession, asset_ids: Sequence[int]
) -> dict[int, int]:
    if not asset_ids:
        return {}
    stmt = (
        select(Shot.asset_id, func.count())
        .where(Shot.asset_id.in_(list(asset_ids)), Shot.status == ShotStatus.READY)
        .group_by(Shot.asset_id)
    )
    return {aid: cnt for aid, cnt in (await db.execute(stmt)).all()}


async def latest_run_status_for_assets(
    db: AsyncSession, asset_ids: Sequence[int]
) -> dict[int, str]:
    """每个素材最近一次分析运行的状态（DISTINCT ON）。"""
    if not asset_ids:
        return {}
    stmt = (
        select(MediaProcessingRun.asset_id, MediaProcessingRun.status)
        .where(MediaProcessingRun.asset_id.in_(list(asset_ids)))
        .order_by(MediaProcessingRun.asset_id, MediaProcessingRun.id.desc())
        .distinct(MediaProcessingRun.asset_id)
    )
    return {aid: st.value for aid, st in (await db.execute(stmt)).all()}


async def get_asset(db: AsyncSession, asset_id: int) -> Asset | None:
    return await db.get(Asset, asset_id)
