"""PR-06A：素材集合（静态镜头集合）业务逻辑。

集合必须归属一个 Project；成员只含 Shot。改名/重排用 ``lock_version`` 乐观锁。归档项目下不允许
新建/修改集合或成员（service 层统一保护）。删除集合只级联删除 ``collection_shot``，绝不删除 Shot。
"""

from __future__ import annotations

from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Collection, CollectionShot, Shot
from clipmind_shared.models.enums import ShotStatus
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.collection import CollectionCreateRequest, CollectionUpdateRequest
from app.services import project_service

_REORDER_OFFSET = 1_000_000


async def get_collection_or_404(db: AsyncSession, collection_id: int) -> Collection:
    coll = await db.get(Collection, collection_id)
    if coll is None:
        raise HTTPException(status_code=404, detail="集合不存在")
    return coll


async def _ensure_parent_mutable(db: AsyncSession, coll: Collection) -> None:
    """集合的可变性由其归属项目决定：归档项目下集合只读。"""
    proj = await project_service.get_project_or_404(db, coll.project_id)
    project_service.ensure_project_mutable(proj)


async def _shot_count(db: AsyncSession, collection_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count(CollectionShot.id)).where(
                CollectionShot.collection_id == collection_id
            )
        )
        or 0
    )


# ============================ CRUD ============================


async def create_collection(
    db: AsyncSession, project_id: int, req: CollectionCreateRequest
) -> Collection:
    proj = await project_service.get_project_or_404(db, project_id)
    project_service.ensure_project_mutable(proj)
    coll = Collection(
        project_id=project_id, name=req.name, description=req.description, lock_version=1
    )
    db.add(coll)
    await db.commit()
    await db.refresh(coll)
    return coll


async def list_collections(
    db: AsyncSession, project_id: int, *, page: int, page_size: int
) -> tuple[list[Collection], int, dict[int, int]]:
    await project_service.get_project_or_404(db, project_id)
    total = int(
        await db.scalar(
            select(func.count(Collection.id)).where(Collection.project_id == project_id)
        )
        or 0
    )
    rows = (
        await db.scalars(
            select(Collection)
            .where(Collection.project_id == project_id)
            .order_by(Collection.created_at.desc(), Collection.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    counts: dict[int, int] = {}
    ids = [c.id for c in rows]
    if ids:
        cnt_rows = (
            await db.execute(
                select(CollectionShot.collection_id, func.count(CollectionShot.id))
                .where(CollectionShot.collection_id.in_(ids))
                .group_by(CollectionShot.collection_id)
            )
        ).all()
        counts = {cid: c for cid, c in cnt_rows}
    return list(rows), total, counts


async def update_collection(
    db: AsyncSession, collection_id: int, req: CollectionUpdateRequest
) -> Collection:
    coll = await get_collection_or_404(db, collection_id)
    await _ensure_parent_mutable(db, coll)

    provided = req.model_fields_set - {"lock_version"}
    if not provided:
        raise HTTPException(status_code=422, detail="无可更新字段")

    values: dict[str, Any] = {}
    if "name" in provided:
        values["name"] = req.name
    if "description" in provided:
        values["description"] = req.description
    values["lock_version"] = req.lock_version + 1
    values["updated_at"] = utcnow()

    result = await db.execute(
        update(Collection)
        .where(Collection.id == collection_id, Collection.lock_version == req.lock_version)
        .values(**values)
    )
    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="集合已被更新（lock_version 不匹配），请刷新后重试"
        )
    await db.commit()
    await db.refresh(coll)
    return coll


async def delete_collection(db: AsyncSession, collection_id: int) -> None:
    coll = await get_collection_or_404(db, collection_id)
    await _ensure_parent_mutable(db, coll)
    # 删除集合：级联删除 collection_shot（仅关联行），绝不删除 Shot
    await db.delete(coll)
    await db.commit()


# ============================ 成员（镜头）============================


async def list_collection_shots(
    db: AsyncSession, collection_id: int, *, page: int, page_size: int
) -> tuple[list[Shot], int]:
    await get_collection_or_404(db, collection_id)
    base = (
        select(Shot)
        .join(CollectionShot, CollectionShot.shot_id == Shot.id)
        .where(CollectionShot.collection_id == collection_id, Shot.status == ShotStatus.READY)
    )
    total = int(
        (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    )
    rows = (
        await db.scalars(
            base.order_by(CollectionShot.order_index, Shot.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), total


async def add_collection_shots(
    db: AsyncSession, collection_id: int, ids: list[int]
) -> dict[str, list]:
    coll = await get_collection_or_404(db, collection_id)
    await _ensure_parent_mutable(db, coll)

    req_ids = list(dict.fromkeys(ids))
    existing_shots = set(await db.scalars(select(Shot.id).where(Shot.id.in_(req_ids))))
    member_ids = set(
        await db.scalars(
            select(CollectionShot.shot_id).where(
                CollectionShot.collection_id == collection_id,
                CollectionShot.shot_id.in_(req_ids),
            )
        )
    )

    completed: list[int] = []
    skipped: list[int] = []
    failed: list[dict] = []
    to_add: list[int] = []
    for sid in req_ids:
        if sid not in existing_shots:
            failed.append({"id": sid, "error": "镜头不存在"})
        elif sid in member_ids:
            skipped.append(sid)
        else:
            to_add.append(sid)

    next_order = 0
    if to_add:
        max_order = await db.scalar(
            select(func.max(CollectionShot.order_index)).where(
                CollectionShot.collection_id == collection_id
            )
        )
        next_order = (max_order + 1) if max_order is not None else 0
    for sid in to_add:
        db.add(
            CollectionShot(collection_id=collection_id, shot_id=sid, order_index=next_order)
        )
        next_order += 1
        completed.append(sid)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="集合成员并发冲突，请刷新后重试"
        ) from None
    return {"completed": completed, "skipped": skipped, "failed": failed}


async def remove_collection_shot(
    db: AsyncSession, collection_id: int, shot_id: int
) -> None:
    coll = await get_collection_or_404(db, collection_id)
    await _ensure_parent_mutable(db, coll)
    result = await db.execute(
        delete(CollectionShot).where(
            CollectionShot.collection_id == collection_id, CollectionShot.shot_id == shot_id
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="集合镜头关联不存在")
    await db.commit()


async def reorder_collection_shots(
    db: AsyncSession, collection_id: int, requested_ids: list[int], lock_version: int
) -> Collection:
    coll = await get_collection_or_404(db, collection_id)
    await _ensure_parent_mutable(db, coll)

    members = (
        await db.scalars(
            select(CollectionShot).where(CollectionShot.collection_id == collection_id)
        )
    ).all()
    by_shot = {m.shot_id: m for m in members}

    if len(requested_ids) != len(set(requested_ids)):
        raise HTTPException(status_code=422, detail="重排列表含重复 id")
    if set(requested_ids) != set(by_shot):
        raise HTTPException(status_code=422, detail="重排列表必须恰好覆盖该集合的全部镜头")

    # 乐观锁：集合 lock_version 条件 UPDATE
    result = await db.execute(
        update(Collection)
        .where(Collection.id == collection_id, Collection.lock_version == lock_version)
        .values(lock_version=lock_version + 1, updated_at=utcnow())
    )
    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="集合已被更新（lock_version 不匹配），请刷新后重试"
        )

    for m in members:
        m.order_index = m.order_index + _REORDER_OFFSET
    await db.flush()
    for idx, sid in enumerate(requested_ids):
        by_shot[sid].order_index = idx
    await db.commit()
    await db.refresh(coll)
    return coll
