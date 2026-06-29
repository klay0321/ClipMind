"""PR-06B 动态集合业务逻辑：CRUD + 实时 re-run（不落地 CollectionShot）。

- 必须归属 Project；保存查询条件（query_serde 校验，去分页），打开时调当前搜索服务实时计算成员。
- 改名/改 query 用 lock_version 乐观锁；归档项目下只读（创建/修改/删除 409，运行/查看允许）。
- 删除动态集合不删除任何 Shot；不把搜索结果写库。
"""

from __future__ import annotations

from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import DynamicCollection, Project
from clipmind_shared.models.enums import ProjectStatus, SearchKind
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.dynamic_collection import (
    DynamicCollectionCreate,
    DynamicCollectionUpdate,
)
from app.services import query_serde


async def _get_project_mutable(db: AsyncSession, project_id: int) -> Project:
    proj = await db.get(Project, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if proj.status == ProjectStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="项目已归档，禁止修改（仅可查看/运行）")
    return proj


async def get_or_404(db: AsyncSession, dyn_id: int) -> DynamicCollection:
    obj = await db.get(DynamicCollection, dyn_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="动态集合不存在")
    return obj


async def create(
    db: AsyncSession, project_id: int, req: DynamicCollectionCreate
) -> DynamicCollection:
    await _get_project_mutable(db, project_id)
    query = query_serde.serialize_query(req.search_kind, req.query)
    obj = DynamicCollection(
        project_id=project_id,
        name=req.name,
        description=req.description,
        search_kind=req.search_kind,
        query=query,
        lock_version=1,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def list_for_project(
    db: AsyncSession, project_id: int, *, page: int, page_size: int
) -> tuple[list[DynamicCollection], int]:
    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    count = select(func.count(DynamicCollection.id)).where(
        DynamicCollection.project_id == project_id
    )
    total = int(await db.scalar(count) or 0)
    rows = (
        await db.scalars(
            select(DynamicCollection)
            .where(DynamicCollection.project_id == project_id)
            .order_by(DynamicCollection.created_at.desc(), DynamicCollection.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    return list(rows), total


async def update(
    db: AsyncSession, dyn_id: int, req: DynamicCollectionUpdate
) -> DynamicCollection:
    obj = await get_or_404(db, dyn_id)
    await _get_project_mutable(db, obj.project_id)
    provided = req.model_fields_set - {"lock_version"}
    if not provided:
        raise HTTPException(status_code=422, detail="无可更新字段")

    new_kind = req.search_kind if "search_kind" in provided and req.search_kind else obj.search_kind
    values: dict[str, Any] = {"lock_version": req.lock_version + 1, "updated_at": utcnow()}
    if "name" in provided:
        values["name"] = req.name
    if "description" in provided:
        values["description"] = req.description
    if "search_kind" in provided and req.search_kind is not None:
        values["search_kind"] = req.search_kind
    if "query" in provided and req.query is not None:
        values["query"] = query_serde.serialize_query(new_kind, req.query)

    result = await db.execute(
        sa_update(DynamicCollection)
        .where(
            DynamicCollection.id == dyn_id,
            DynamicCollection.lock_version == req.lock_version,
        )
        .values(**values)
    )
    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="动态集合已被更新（lock_version 不匹配），请刷新"
        )
    await db.commit()
    await db.refresh(obj)
    return obj


async def delete(db: AsyncSession, dyn_id: int) -> None:
    obj = await get_or_404(db, dyn_id)
    await _get_project_mutable(db, obj.project_id)
    await db.delete(obj)
    await db.commit()


async def run_shots(
    db: AsyncSession, dyn_id: int, *, page: int, page_size: int,
    settings, parser, embedding_provider,
):
    """实时调当前搜索服务计算成员（后端分页，不落库）。"""
    from app.services import search_service  # 延迟导入避免循环

    obj = await get_or_404(db, dyn_id)
    if obj.search_kind == SearchKind.SHOT_SEARCH:
        request = query_serde.build_shot_search_request(obj.query, page=page, page_size=page_size)
        return await search_service.run_shot_search(
            db, request, parser=parser, embedding_provider=embedding_provider, settings=settings
        )
    request = query_serde.build_description_match_request(obj.query, limit=page_size)
    return await search_service.run_description_match(
        db, request, parser=parser, embedding_provider=embedding_provider, settings=settings
    )
