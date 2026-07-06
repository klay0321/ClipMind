"""网页上传：把上传视频写入独立可写区（/app/uploads），再触发索引。

- 绝不写只读 NAS 源目录（/app/source）；上传区是独立白名单根。
- 扩展名白名单 + 大小限制 + 路径安全（safe_join_within_root）；同名自动去重。
- 写入后确保一个「上传素材」源目录存在并入队扫描索引该文件。
"""

from __future__ import annotations

import os

from clipmind_shared.constants import SUPPORTED_MEDIA_EXTENSIONS
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import SourceDirectory
from clipmind_shared.models.enums import ScanStatus
from clipmind_shared.security import safe_join_within_root
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services import scan_dispatch

UPLOAD_DIR_NAME = "上传素材"


class UploadError(Exception):
    """上传校验/写入失败。"""


def _ext_ok(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lstrip(".").lower()
    return ext in SUPPORTED_MEDIA_EXTENSIONS  # PM：视频 + 图片素材


def _safe_name(filename: str) -> str:
    base = os.path.basename(filename or "").strip()
    base = base.replace("\\", "_").replace("/", "_")
    return base or "upload.mp4"


async def _ensure_upload_source_dir(db: AsyncSession, upload_root: str) -> SourceDirectory:
    res = await db.execute(
        select(SourceDirectory).where(SourceDirectory.mount_path == upload_root)
    )
    sd = res.scalars().first()
    if sd is not None:
        # PM 升级路径：老上传目录补齐新支持的扩展名（幂等 union，不丢用户自定义）
        missing = [e for e in SUPPORTED_MEDIA_EXTENSIONS
                   if e not in (sd.include_extensions or [])]
        if missing:
            sd.include_extensions = sorted(
                {*(sd.include_extensions or []), *SUPPORTED_MEDIA_EXTENSIONS}
            )
            sd.updated_at = utcnow()
            await db.commit()
            await db.refresh(sd)
        return sd
    sd = SourceDirectory(
        name=UPLOAD_DIR_NAME,
        mount_path=upload_root,
        enabled=True,
        recursive=True,
        include_extensions=list(SUPPORTED_MEDIA_EXTENSIONS),
        exclude_patterns=[],
        read_only=True,
        scan_status=ScanStatus.NEVER_SCANNED,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(sd)
    await db.commit()
    await db.refresh(sd)
    return sd


async def save_upload(db: AsyncSession, *, filename: str, stream) -> dict:  # noqa: ANN001
    """保存上传文件到上传区并触发索引，返回结果摘要。"""
    settings = get_settings()
    if not _ext_ok(filename):
        raise UploadError("不支持的文件类型（仅限 " + "/".join(SUPPORTED_MEDIA_EXTENSIONS) + "）")

    root = os.path.realpath(settings.upload_dir)
    os.makedirs(root, exist_ok=True)

    name = _safe_name(filename)
    dest = safe_join_within_root(root, name)
    stem, ext = os.path.splitext(name)
    i = 1
    while os.path.exists(dest):
        dest = safe_join_within_root(root, f"{stem}-{i}{ext}")
        i += 1

    max_bytes = settings.upload_max_mb * 1024 * 1024
    tmp = dest + ".part"
    written = 0
    try:
        with open(tmp, "wb") as f:
            while True:
                chunk = await stream.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise UploadError(f"文件超过 {settings.upload_max_mb}MB 上限")
                f.write(chunk)
        os.replace(tmp, dest)
    finally:
        # 任意失败路径（超限/写盘异常/客户端中断/replace 失败）都清理 .part；
        # 成功路径下 os.replace 已移走 tmp，exists 为 False，无副作用。异常照常向上抛。
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

    sd = await _ensure_upload_source_dir(db, root)
    run = await scan_dispatch.request_scan(db, sd)
    return {
        "filename": os.path.basename(dest),
        "bytes": written,
        "source_directory_id": sd.id,
        "scan_run_id": run.id,
        "celery_task_id": run.celery_task_id,
    }
