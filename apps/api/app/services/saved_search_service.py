"""PR-06B 保存搜索业务逻辑：CRUD + re-run（按当前真实搜索服务重新计算）。

- 保存完整搜索请求（去分页，query_serde 校验）；re-run 用当前 search_service，不复制算法。
- 改名/改 query 用 lock_version 乐观锁（条件 UPDATE + rowcount 判定），冲突 409。
- 所属 Project 归档时允许查看/运行，禁止修改/删除（409）。
"""

from __future__ import annotations

from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Project, SavedSearch
from clipmind_shared.models.enums import ProjectStatus, SearchKind
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.saved_search import SavedSearchCreate, SavedSearchUpdate
from app.services import query_serde


async def _ensure_owner_mutable(db: AsyncSession, project_id: int | None) -> None:
    if project_id is None:
        return
    proj = await db.get(Project, project_id)
    if proj is not None and proj.status == ProjectStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="所属项目已归档，禁止修改保存搜索")


async def get_or_404(db: AsyncSession, saved_id: int) -> SavedSearch:
    obj = await db.get(SavedSearch, saved_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="保存搜索不存在")
    return obj


async def create(db: AsyncSession, req: SavedSearchCreate) -> SavedSearch:
    query = query_serde.serialize_query(req.search_kind, req.query)
    if req.project_id is not None:
        proj = await db.get(Project, req.project_id)
        if proj is None:
            raise HTTPException(status_code=404, detail="项目不存在")
    obj = SavedSearch(
        project_id=req.project_id,
        name=req.name,
        search_kind=req.search_kind,
        query=query,
        lock_version=1,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def list_saved(
    db: AsyncSession, *, page: int, page_size: int,
    project_id: int | None, search_kind: SearchKind | None,
) -> tuple[list[SavedSearch], int]:
    base = select(SavedSearch)
    count = select(func.count(SavedSearch.id))
    if project_id is not None:
        base = base.where(SavedSearch.project_id == project_id)
        count = count.where(SavedSearch.project_id == project_id)
    if search_kind is not None:
        base = base.where(SavedSearch.search_kind == search_kind)
        count = count.where(SavedSearch.search_kind == search_kind)
    total = int(await db.scalar(count) or 0)
    rows = (
        await db.scalars(
            base.order_by(SavedSearch.created_at.desc(), SavedSearch.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    return list(rows), total


async def update(db: AsyncSession, saved_id: int, req: SavedSearchUpdate) -> SavedSearch:
    obj = await get_or_404(db, saved_id)
    await _ensure_owner_mutable(db, obj.project_id)
    provided = req.model_fields_set - {"lock_version"}
    if not provided:
        raise HTTPException(status_code=422, detail="无可更新字段")
    values: dict[str, Any] = {"lock_version": req.lock_version + 1, "updated_at": utcnow()}
    if "name" in provided:
        values["name"] = req.name
    if "query" in provided and req.query is not None:
        values["query"] = query_serde.serialize_query(obj.search_kind, req.query)

    result = await db.execute(
        sa_update(SavedSearch)
        .where(SavedSearch.id == saved_id, SavedSearch.lock_version == req.lock_version)
        .values(**values)
    )
    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="保存搜索已被更新（lock_version 不匹配），请刷新"
        )
    await db.commit()
    await db.refresh(obj)
    return obj


async def delete(db: AsyncSession, saved_id: int) -> None:
    obj = await get_or_404(db, saved_id)
    await _ensure_owner_mutable(db, obj.project_id)
    await db.delete(obj)
    await db.commit()


async def run(
    db: AsyncSession, saved_id: int, *, page: int, page_size: int,
    settings, parser, embedding_provider,
):
    """按当前真实搜索服务重新运行保存的查询。"""
    from app.services import search_service  # 延迟导入避免循环

    obj = await get_or_404(db, saved_id)
    if obj.search_kind == SearchKind.SHOT_SEARCH:
        request = query_serde.build_shot_search_request(obj.query, page=page, page_size=page_size)
        return await search_service.run_shot_search(
            db, request, parser=parser, embedding_provider=embedding_provider, settings=settings
        )
    request = query_serde.build_description_match_request(obj.query, limit=page_size)
    return await search_service.run_description_match(
        db, request, parser=parser, embedding_provider=embedding_provider, settings=settings
    )
