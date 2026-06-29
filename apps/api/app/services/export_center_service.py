"""PR-06B 统一导出中心服务（只读聚合 + 重试 + 安全删除 + 下载记录）。

- 聚合 export（clip）/ script_export（script）/ bundle_export（bundle）三表为统一 DTO，
  **绝不破坏性合表**、绝不重写已通过验收的 CSV 导出。
- 分页可靠：先对三表投影 (kind,id,created_at) 做 UNION ALL，仅对该投影排序分页取本页
  (kind,id)，再按 kind 批量取整行——不把整表载入 Python。稳定排序 created_at DESC, kind, id。
- 重试仅 failed；删除仅 completed/failed，删派生文件经 realpath + 子树包含校验，**绝不碰源**。
- 下载记录写 download_log（无鉴权，不记 user）。
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import BundleExport, DownloadLog, Export, ScriptExport
from clipmind_shared.models.enums import (
    EXPORT_KIND_BUNDLE,
    EXPORT_KIND_CLIP,
    EXPORT_KIND_SCRIPT,
    EXPORT_KINDS,
    ExportStatus,
)
from clipmind_shared.security import PathTraversal, is_within, safe_join_within_root
from fastapi import HTTPException
from sqlalchemy import and_, func, literal, select, tuple_, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.schemas.export_center import ExportActionOut, ExportCenterItem
from app.tasks_client import (
    enqueue_export_bundle,
    enqueue_export_clip,
    enqueue_export_script,
)

_MODEL_BY_KIND = {
    EXPORT_KIND_CLIP: Export,
    EXPORT_KIND_SCRIPT: ScriptExport,
    EXPORT_KIND_BUNDLE: BundleExport,
}
_SUBTREE_BY_KIND = {
    EXPORT_KIND_CLIP: "exports",
    EXPORT_KIND_SCRIPT: "script_exports",
    EXPORT_KIND_BUNDLE: "bundle_exports",
}
_DELETABLE = (ExportStatus.COMPLETED, ExportStatus.FAILED)

# 列表分页页大小硬上限（防御超大分页）
MAX_PAGE_SIZE_GUARD = 100


# ============================ DTO 映射 ============================


def _to_item(row, kind: str, download_count: int = 0) -> ExportCenterItem:
    if kind == EXPORT_KIND_CLIP:
        fmt = "mp4"
        row_count = None
        download_url = f"/api/exports/{row.id}/download"
        source = {
            "source_filename": row.source_filename,
            "sequence_no": row.source_sequence_no,
            "asset_id": row.asset_id,
            "shot_id": row.shot_id,
        }
    elif kind == EXPORT_KIND_SCRIPT:
        fmt = row.export_format
        row_count = row.row_count
        download_url = f"/api/scripts/{row.script_project_id}/exports/{row.id}/download"
        source = {"script_project_id": row.script_project_id}
    else:  # bundle
        fmt = "zip"
        row_count = row.row_count
        download_url = f"/api/exports/bundle/{row.id}/download"
        source = {"shot_count": len(row.shot_ids or [])}

    return ExportCenterItem(
        kind=kind,
        id=row.id,
        export_uuid=row.export_uuid,
        project_id=row.project_id,
        status=row.status,
        format=fmt,
        filename=row.filename,
        has_file=bool(row.output_path),
        row_count=row_count,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        download_url=download_url,
        download_count=download_count,
        source=source,
    )


# ============================ 列表（聚合 + 稳定分页） ============================


def _kind_projection(model, kind: str, *, status, project_id, created_from, created_to):
    q = select(
        literal(kind).label("kind"),
        model.id.label("id"),
        model.created_at.label("created_at"),
    )
    conds = []
    if status is not None:
        conds.append(model.status == status)
    if project_id is not None:
        conds.append(model.project_id == project_id)
    if created_from is not None:
        conds.append(model.created_at >= created_from)
    if created_to is not None:
        conds.append(model.created_at <= created_to)
    if conds:
        q = q.where(and_(*conds))
    return q


async def list_exports(
    db: AsyncSession,
    *,
    kind: str | None,
    status: ExportStatus | None,
    project_id: int | None,
    created_from: datetime | None,
    created_to: datetime | None,
    page: int,
    page_size: int,
) -> tuple[list[ExportCenterItem], int]:
    kinds = [kind] if kind in EXPORT_KINDS else list(EXPORT_KINDS)
    projections = [
        _kind_projection(
            _MODEL_BY_KIND[k], k,
            status=status, project_id=project_id,
            created_from=created_from, created_to=created_to,
        )
        for k in kinds
    ]
    u = projections[0] if len(projections) == 1 else union_all(*projections)
    u = u.subquery()

    total = int(await db.scalar(select(func.count()).select_from(u)) or 0)
    if total == 0:
        return [], 0

    page_rows = (
        await db.execute(
            select(u.c.kind, u.c.id)
            .order_by(u.c.created_at.desc(), u.c.kind, u.c.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    if not page_rows:
        return [], total

    # 本页 (kind,id) → 按 kind 批量取整行
    ids_by_kind: dict[str, list[int]] = {}
    for k, rid in page_rows:
        ids_by_kind.setdefault(k, []).append(rid)

    rows_by_key: dict[tuple[str, int], object] = {}
    for k, ids in ids_by_kind.items():
        model = _MODEL_BY_KIND[k]
        fetched = (await db.scalars(select(model).where(model.id.in_(ids)))).all()
        for r in fetched:
            rows_by_key[(k, r.id)] = r

    # 下载次数（本页一次聚合）
    pairs = [(k, rid) for k, rid in page_rows]
    counts: dict[tuple[str, int], int] = {}
    dl_rows = (
        await db.execute(
            select(DownloadLog.export_kind, DownloadLog.export_id, func.count())
            .where(tuple_(DownloadLog.export_kind, DownloadLog.export_id).in_(pairs))
            .group_by(DownloadLog.export_kind, DownloadLog.export_id)
        )
    ).all()
    for k, rid, c in dl_rows:
        counts[(k, rid)] = int(c)

    items: list[ExportCenterItem] = []
    for k, rid in page_rows:
        row = rows_by_key.get((k, rid))
        if row is not None:
            items.append(_to_item(row, k, counts.get((k, rid), 0)))
    return items, total


# ============================ 单条 / 重试 / 删除 ============================


async def _get_row_or_404(db: AsyncSession, kind: str, export_id: int):
    if kind not in EXPORT_KINDS:
        raise HTTPException(status_code=404, detail="未知导出类型")
    row = await db.get(_MODEL_BY_KIND[kind], export_id)
    if row is None:
        raise HTTPException(status_code=404, detail="导出不存在")
    return row


async def get_export(db: AsyncSession, kind: str, export_id: int) -> ExportCenterItem:
    row = await _get_row_or_404(db, kind, export_id)
    count = int(
        await db.scalar(
            select(func.count())
            .select_from(DownloadLog)
            .where(DownloadLog.export_kind == kind, DownloadLog.export_id == export_id)
        )
        or 0
    )
    return _to_item(row, kind, count)


async def retry_export(db: AsyncSession, kind: str, export_id: int) -> ExportActionOut:
    """仅 failed 可重试：复用同一行/同一目录重置为 QUEUED 并重新入队（幂等防重复点击）。"""
    row = await _get_row_or_404(db, kind, export_id)
    if row.status != ExportStatus.FAILED:
        raise HTTPException(
            status_code=409, detail="仅失败的导出可重试（queued/running/completed 不可重试）"
        )
    # 保留历史错误到一个独立字段不必要——重置 error 让重试干净；旧错误已在审计/日志层留存
    row.status = ExportStatus.QUEUED
    row.error_message = None
    row.queued_at = utcnow()
    row.started_at = None
    row.finished_at = None
    await db.commit()
    await db.refresh(row)

    try:
        if kind == EXPORT_KIND_CLIP:
            task_id = enqueue_export_clip(row.id)
        elif kind == EXPORT_KIND_SCRIPT:
            task_id = enqueue_export_script(row.id)
        else:
            task_id = enqueue_export_bundle(row.id)
    except Exception as exc:  # noqa: BLE001
        row.status = ExportStatus.FAILED
        row.error_message = f"重新入队失败: {exc}"[:2000]
        row.finished_at = utcnow()
        await db.commit()
        raise
    row.celery_task_id = task_id
    await db.commit()
    return ExportActionOut(kind=kind, id=row.id, status=row.status, detail="已重新入队")


def _safe_delete_export_file(output_path: str | None, kind: str) -> None:
    """删除派生导出文件（经 realpath + 允许子树包含校验，拒绝穿越/软链；绝不碰源）。

    删除失败抛 500（绝不静默声称成功）；允许根仅 clip/script/bundle 三个导出子树。
    """
    if not output_path:
        return
    data_root = os.path.realpath(get_settings().data_dir)
    subtree = safe_join_within_root(data_root, _SUBTREE_BY_KIND[kind])
    try:
        abs_file = safe_join_within_root(data_root, output_path)
    except PathTraversal as exc:
        raise HTTPException(status_code=400, detail="导出文件路径非法") from exc
    if not is_within(abs_file, subtree):
        raise HTTPException(status_code=400, detail="导出文件不在允许的派生目录内")
    try:
        if os.path.isfile(abs_file):
            os.remove(abs_file)
        # 删除 {uuid} 目录（仅当其直接位于允许子树之下）
        parent = os.path.dirname(abs_file)
        if os.path.dirname(parent) == subtree and os.path.isdir(parent):
            shutil.rmtree(parent)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail="删除导出文件失败，记录未删除"
        ) from exc


async def delete_export(db: AsyncSession, kind: str, export_id: int) -> None:
    """删除导出记录及其派生文件（仅 completed/failed；先删文件再删行，失败不静默成功）。"""
    row = await _get_row_or_404(db, kind, export_id)
    if row.status not in _DELETABLE:
        raise HTTPException(
            status_code=409, detail="仅已完成/失败的导出可删除（queued/running 不可删除）"
        )
    _safe_delete_export_file(row.output_path, kind)
    await db.delete(row)
    await db.commit()


# ============================ 下载记录 ============================


async def record_download(db: AsyncSession, kind: str, export_id: int) -> None:
    """成功开始返回文件时记录一次下载（无鉴权，不记 user）。"""
    db.add(DownloadLog(export_kind=kind, export_id=export_id, created_at=utcnow()))
    await db.commit()
