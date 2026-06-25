"""标签字典服务（PR-03B）。无物理删除；archive 后历史 ShotTag 保留、新审核不再推荐。"""

from __future__ import annotations

from clipmind_shared.models import Tag
from clipmind_shared.models.enums import ProductStatus, TagType
from clipmind_shared.review import normalize_name
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class TagError(Exception):
    """标签业务错误。"""


async def list_tags(
    db: AsyncSession,
    *,
    tag_type: TagType | None = None,
    status: ProductStatus | None = None,
    q: str | None = None,
) -> list[Tag]:
    stmt = select(Tag)
    if tag_type is not None:
        stmt = stmt.where(Tag.tag_type == tag_type)
    if status is not None:
        stmt = stmt.where(Tag.status == status)
    if q:
        stmt = stmt.where(Tag.normalized_name.like(f"%{normalize_name(q)}%"))
    stmt = stmt.order_by(Tag.tag_type, Tag.tag_name)
    return list((await db.execute(stmt)).scalars().all())


async def create_tag(db: AsyncSession, tag_type: TagType, name: str) -> Tag:
    name = (name or "").strip()
    if not name:
        raise TagError("标签名不能为空")
    tag = Tag(tag_type=tag_type, tag_name=name, normalized_name=normalize_name(name))
    db.add(tag)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise TagError("同类型下已存在同名标签") from exc
    await db.refresh(tag)
    return tag


async def update_tag(db: AsyncSession, tag: Tag, name: str) -> Tag:
    name = (name or "").strip()
    if not name:
        raise TagError("标签名不能为空")
    tag.tag_name = name
    tag.normalized_name = normalize_name(name)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise TagError("同类型下已存在同名标签") from exc
    await db.refresh(tag)
    return tag


async def archive_tag(db: AsyncSession, tag: Tag) -> Tag:
    tag.status = ProductStatus.ARCHIVED
    await db.commit()
    await db.refresh(tag)
    return tag
