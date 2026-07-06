"""Asset 服务：分页列表（搜索/筛选）+ 详情。"""

from __future__ import annotations

from collections.abc import Sequence

from clipmind_shared.models import Asset
from clipmind_shared.models.enums import AssetStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def list_assets(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    status: AssetStatus | None = None,
    source_directory_id: int | None = None,
    media_kind: str | None = None,
) -> tuple[Sequence[Asset], int]:
    filters = []
    if q:
        filters.append(Asset.filename.ilike(f"%{q}%"))
    if status is not None:
        filters.append(Asset.status == status)
    if source_directory_id is not None:
        filters.append(Asset.source_directory_id == source_directory_id)
    if media_kind is not None:
        filters.append(Asset.media_kind == media_kind)

    count_stmt = select(func.count()).select_from(Asset)
    list_stmt = select(Asset).order_by(Asset.id.desc())
    for f in filters:
        count_stmt = count_stmt.where(f)
        list_stmt = list_stmt.where(f)

    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    list_stmt = list_stmt.offset(offset).limit(page_size)
    items = (await db.execute(list_stmt)).scalars().all()
    return items, total


async def get_asset(db: AsyncSession, asset_id: int) -> Asset | None:
    return await db.get(Asset, asset_id)
