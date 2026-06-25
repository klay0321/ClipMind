"""标签字典路由（PR-03B）。"""

from __future__ import annotations

from clipmind_shared.models import Tag
from clipmind_shared.models.enums import ProductStatus, TagType
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.tag import TagIn, TagOut, TagUpdateIn
from app.services import tag_service
from app.services.tag_service import TagError

router = APIRouter(tags=["tags"])


@router.get("/tags", response_model=list[TagOut])
async def list_tags(
    tag_type: TagType | None = None,
    status_filter: ProductStatus | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[TagOut]:
    rows = await tag_service.list_tags(db, tag_type=tag_type, status=status_filter, q=q)
    return [TagOut.model_validate(t) for t in rows]


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(body: TagIn, db: AsyncSession = Depends(get_db)) -> TagOut:
    try:
        tag = await tag_service.create_tag(db, body.tag_type, body.tag_name)
    except TagError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TagOut.model_validate(tag)


@router.put("/tags/{tag_id}", response_model=TagOut)
async def update_tag(
    tag_id: int, body: TagUpdateIn, db: AsyncSession = Depends(get_db)
) -> TagOut:
    tag = await db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    try:
        tag = await tag_service.update_tag(db, tag, body.tag_name)
    except TagError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TagOut.model_validate(tag)


@router.post("/tags/{tag_id}/archive", response_model=TagOut)
async def archive_tag(tag_id: int, db: AsyncSession = Depends(get_db)) -> TagOut:
    tag = await db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    return TagOut.model_validate(await tag_service.archive_tag(db, tag))
