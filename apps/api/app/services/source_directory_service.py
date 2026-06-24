"""SourceDirectory 服务：CRUD + 路径白名单校验。"""

from __future__ import annotations

from collections.abc import Sequence

from clipmind_shared.constants import SUPPORTED_VIDEO_EXTENSIONS
from clipmind_shared.models import SourceDirectory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.source_directory import SourceDirectoryCreate, SourceDirectoryUpdate
from app.security import validate_mount_path


def _normalize_extensions(exts: list[str] | None) -> list[str]:
    if not exts:
        return list(SUPPORTED_VIDEO_EXTENSIONS)
    cleaned = {e.lower().lstrip(".").strip() for e in exts if e and e.strip()}
    return sorted(cleaned) or list(SUPPORTED_VIDEO_EXTENSIONS)


async def list_source_directories(db: AsyncSession) -> Sequence[SourceDirectory]:
    result = await db.execute(select(SourceDirectory).order_by(SourceDirectory.id))
    return result.scalars().all()


async def get_source_directory(db: AsyncSession, sd_id: int) -> SourceDirectory | None:
    return await db.get(SourceDirectory, sd_id)


async def create_source_directory(
    db: AsyncSession, data: SourceDirectoryCreate
) -> SourceDirectory:
    # 白名单 + realpath 校验（越界抛 PathNotAllowed -> 422）
    validate_mount_path(data.mount_path)

    sd = SourceDirectory(
        name=data.name,
        mount_path=data.mount_path,
        enabled=data.enabled,
        recursive=data.recursive,
        include_extensions=_normalize_extensions(data.include_extensions),
        exclude_patterns=data.exclude_patterns or [],
        read_only=True,  # 源目录恒为只读
    )
    db.add(sd)
    await db.commit()
    await db.refresh(sd)
    return sd


async def update_source_directory(
    db: AsyncSession, sd: SourceDirectory, data: SourceDirectoryUpdate
) -> SourceDirectory:
    if data.mount_path is not None:
        validate_mount_path(data.mount_path)
        sd.mount_path = data.mount_path
    if data.name is not None:
        sd.name = data.name
    if data.recursive is not None:
        sd.recursive = data.recursive
    if data.enabled is not None:
        sd.enabled = data.enabled
    if data.include_extensions is not None:
        sd.include_extensions = _normalize_extensions(data.include_extensions)
    if data.exclude_patterns is not None:
        sd.exclude_patterns = data.exclude_patterns
    # read_only 不可取消
    sd.read_only = True

    await db.commit()
    await db.refresh(sd)
    return sd
