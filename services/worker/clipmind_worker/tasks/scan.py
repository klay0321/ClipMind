"""扫描任务：目录扫描 + 单素材重扫。

设计要点：
- 扫描状态以数据库 ScanRun 为事实来源。
- 互斥：PostgreSQL session 级 advisory lock（绑定单一连接，跨多次 commit 保持），
  叠加 ScanRun 的部分唯一索引（API 层防重）。
- 缺失检测：基于 last_seen_scan_id，仅在遍历完整成功后用 SQL 批量标记；失败不标记。
- 分层变化检测：未变文件不读内容、不 probe。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from clipmind_shared.constants import (
    ERROR_MESSAGE_MAX_LEN,
    METADATA_VERSION,
    QUEUE_MEDIA,
    SCAN_COMMIT_BATCH,
    TASK_GENERATE_ASSET_POSTER,
    TASK_RESCAN_ASSET,
    TASK_SCAN_SOURCE_DIRECTORY,
)
from clipmind_shared.db.base import utcnow
from clipmind_shared.ffprobe import ProbeError, probe_video
from clipmind_shared.models import Asset, ScanRun, SourceDirectory
from clipmind_shared.models.enums import AssetStatus, ScanRunStatus, ScanStatus
from clipmind_shared.pathutil import normalize_relative_path
from clipmind_shared.security import (
    PathTraversal,
    resolve_and_validate_root,
    safe_join_within_root,
)
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from clipmind_worker.celery_app import celery_app
from clipmind_worker.config import get_settings
from clipmind_worker.db import SessionLocal, engine
from clipmind_worker.scanning import (
    apply_probe_to_asset,
    clear_probe_fields,
    compute_quick_hash,
    decide_action,
)
from clipmind_worker.scanning.diff import FileAction, needs_probe
from clipmind_worker.scanning.walker import iter_video_files

settings = get_settings()

# advisory lock 命名空间（两个 int4 键：namespace + source_directory_id）
ADVISORY_LOCK_NAMESPACE = 0x4C4D  # "LM"


def _truncate(text: str) -> str:
    return text[:ERROR_MESSAGE_MAX_LEN]


def _process_file(
    session: Session,
    sd: SourceDirectory,
    run: ScanRun,
    abs_path: str,
    rel: str,
    counts: dict[str, int],
) -> None:
    norm = normalize_relative_path(rel)
    st = os.stat(abs_path)
    new_mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC)

    asset = session.execute(
        select(Asset).where(
            Asset.source_directory_id == sd.id,
            Asset.normalized_relative_path == norm,
        )
    ).scalar_one_or_none()

    action = decide_action(
        exists=asset is not None,
        is_source_missing=(asset is not None and asset.status == AssetStatus.SOURCE_MISSING),
        stored_size=asset.file_size if asset else None,
        stored_mtime=asset.modified_at if asset else None,
        new_size=st.st_size,
        new_mtime=new_mtime,
    )

    # 第一层：未变文件只更新"最后发现"标记，不读内容、不 probe
    if not needs_probe(action):
        if asset is not None:  # UNCHANGED 分支 asset 必然存在
            asset.last_seen_scan_id = run.id
            asset.last_seen_at = utcnow()
        return

    # 第二层：新增/变化/重现 才计算 quick_hash + FFprobe
    ext = os.path.splitext(rel)[1].lstrip(".").lower()
    quick_hash = compute_quick_hash(abs_path, st.st_size)

    probe = None
    probe_error: str | None = None
    try:
        probe = probe_video(abs_path, timeout=settings.ffprobe_timeout)
    except ProbeError as exc:
        probe_error = _truncate(f"{exc.reason}: {exc.detail}".strip())

    if asset is None:
        asset = Asset(source_directory_id=sd.id, first_seen_at=utcnow())
        session.add(asset)
        counts["new"] += 1
    elif action == FileAction.MODIFIED:
        counts["modified"] += 1
    elif action == FileAction.REAPPEARED:
        counts["new"] += 1

    asset.relative_path = rel
    asset.normalized_relative_path = norm
    asset.filename = os.path.basename(rel)
    asset.extension = ext
    asset.file_size = st.st_size
    asset.modified_at = new_mtime
    asset.quick_hash = quick_hash
    asset.metadata_version = METADATA_VERSION
    asset.last_seen_scan_id = run.id
    asset.last_seen_at = utcnow()

    if probe is not None:
        apply_probe_to_asset(asset, probe)
        asset.status = AssetStatus.INDEXED
        asset.error_message = None
        # 新增/变化的素材失效旧海报，扫描结束统一重生成（内容可能已变）
        asset.poster_path = None
    else:
        clear_probe_fields(asset)
        asset.status = AssetStatus.ERROR
        asset.error_message = probe_error
        counts["errored"] += 1


def _update_run_counts(run: ScanRun, counts: dict[str, int]) -> None:
    run.files_discovered = counts["discovered"]
    run.files_new = counts["new"]
    run.files_modified = counts["modified"]
    run.files_errored = counts["errored"]


def _scan_files(
    session: Session, sd: SourceDirectory, run: ScanRun, root_real: str
) -> dict[str, int]:
    counts = {"discovered": 0, "new": 0, "modified": 0, "errored": 0}
    batch = 0
    for abs_path, rel in iter_video_files(
        root_real,
        recursive=sd.recursive,
        include_extensions=sd.include_extensions,
        exclude_patterns=sd.exclude_patterns,
    ):
        counts["discovered"] += 1
        _process_file(session, sd, run, abs_path, rel, counts)
        batch += 1
        if batch >= SCAN_COMMIT_BATCH:
            _update_run_counts(run, counts)
            run.heartbeat_at = utcnow()
            session.commit()
            batch = 0
    _update_run_counts(run, counts)
    run.heartbeat_at = utcnow()
    session.commit()
    return counts


def _enqueue_posters(session: Session, sd_id: int, run_id: int) -> int:
    """为本次扫描已索引但缺海报的素材入队海报生成（media 队列，best-effort）。"""
    ids = (
        session.execute(
            select(Asset.id).where(
                Asset.source_directory_id == sd_id,
                Asset.last_seen_scan_id == run_id,
                Asset.status == AssetStatus.INDEXED,
                Asset.poster_path.is_(None),
            )
        )
        .scalars()
        .all()
    )
    for aid in ids:
        celery_app.send_task(TASK_GENERATE_ASSET_POSTER, args=[aid], queue=QUEUE_MEDIA)
    return len(ids)


def _mark_missing(session: Session, sd_id: int, run_id: int) -> int:
    """仅遍历完整成功后调用：本次未发现的素材标记为 source_missing。"""
    stmt = (
        update(Asset)
        .where(
            Asset.source_directory_id == sd_id,
            Asset.status != AssetStatus.SOURCE_MISSING,
            (
                (Asset.last_seen_scan_id.is_(None))
                | (Asset.last_seen_scan_id != run_id)
            ),
        )
        .values(status=AssetStatus.SOURCE_MISSING)
    )
    result = session.execute(stmt)
    session.commit()
    return result.rowcount or 0


@celery_app.task(name=TASK_SCAN_SOURCE_DIRECTORY, bind=True, acks_late=True)
def scan_source_directory(self, scan_run_id: int) -> dict[str, Any]:  # noqa: ANN001
    # 用单一连接同时承载 ORM 会话与 advisory lock，保证锁跨多次 commit 存活
    with engine.connect() as conn:
        session = Session(bind=conn)
        try:
            run = session.get(ScanRun, scan_run_id)
            if run is None:
                return {"error": "scan_run_not_found", "scan_run_id": scan_run_id}
            if run.status != ScanRunStatus.QUEUED:
                return {"skipped": True, "reason": f"status={run.status.value}"}
            sd = session.get(SourceDirectory, run.source_directory_id)
            if sd is None:
                run.status = ScanRunStatus.FAILED
                run.error_message = "source_directory_not_found"
                run.finished_at = utcnow()
                session.commit()
                return {"error": "source_directory_not_found"}

            sd_id = sd.id
            locked = conn.exec_driver_sql(
                "SELECT pg_try_advisory_lock(%s, %s)",
                (ADVISORY_LOCK_NAMESPACE, sd_id),
            ).scalar()
            if not locked:
                return {"skipped": True, "reason": "locked"}

            try:
                run.status = ScanRunStatus.RUNNING
                run.started_at = utcnow()
                run.heartbeat_at = utcnow()
                run.worker_name = self.request.hostname or ""
                sd.scan_status = ScanStatus.SCANNING
                session.commit()

                root_real = resolve_and_validate_root(
                    sd.mount_path, settings.allowed_roots_list
                )
                counts = _scan_files(session, sd, run, root_real)
                missing = _mark_missing(session, sd_id, run.id)

                run.files_missing = missing
                run.status = ScanRunStatus.COMPLETED
                run.finished_at = utcnow()
                sd.scan_status = ScanStatus.COMPLETED
                sd.last_scanned_at = utcnow()
                session.commit()

                posters = _enqueue_posters(session, sd_id, run.id)

                return {
                    "scan_run_id": run.id,
                    "discovered": counts["discovered"],
                    "new": counts["new"],
                    "modified": counts["modified"],
                    "errored": counts["errored"],
                    "missing": missing,
                    "posters_queued": posters,
                }
            except Exception as exc:  # noqa: BLE001 - 记录失败并向上抛交给 Celery
                session.rollback()
                failed_run = session.get(ScanRun, scan_run_id)
                if failed_run is not None:
                    failed_run.status = ScanRunStatus.FAILED
                    failed_run.error_message = _truncate(str(exc))
                    failed_run.finished_at = utcnow()
                    failed_sd = session.get(SourceDirectory, failed_run.source_directory_id)
                    if failed_sd is not None:
                        failed_sd.scan_status = ScanStatus.FAILED
                    session.commit()
                raise
            finally:
                conn.exec_driver_sql(
                    "SELECT pg_advisory_unlock(%s, %s)",
                    (ADVISORY_LOCK_NAMESPACE, sd_id),
                )
        finally:
            session.close()


@celery_app.task(name=TASK_RESCAN_ASSET, bind=True, acks_late=True)
def rescan_asset(self, asset_id: int) -> dict[str, Any]:  # noqa: ANN001
    with SessionLocal() as session:
        asset = session.get(Asset, asset_id)
        if asset is None:
            return {"error": "asset_not_found", "asset_id": asset_id}
        sd = session.get(SourceDirectory, asset.source_directory_id)
        if sd is None:
            return {"error": "source_directory_not_found"}

        root_real = resolve_and_validate_root(sd.mount_path, settings.allowed_roots_list)
        try:
            abs_path = safe_join_within_root(root_real, asset.relative_path)
        except PathTraversal:
            asset.status = AssetStatus.SOURCE_MISSING
            session.commit()
            return {"status": AssetStatus.SOURCE_MISSING.value}

        if not os.path.isfile(abs_path):
            asset.status = AssetStatus.SOURCE_MISSING
            session.commit()
            return {"status": AssetStatus.SOURCE_MISSING.value}

        st = os.stat(abs_path)
        asset.file_size = st.st_size
        asset.modified_at = datetime.fromtimestamp(st.st_mtime, tz=UTC)
        asset.quick_hash = compute_quick_hash(abs_path, st.st_size)
        asset.metadata_version = METADATA_VERSION
        try:
            probe = probe_video(abs_path, timeout=settings.ffprobe_timeout)
            apply_probe_to_asset(asset, probe)
            asset.status = AssetStatus.INDEXED
            asset.error_message = None
            asset.poster_path = None  # 重扫强制重生成海报
        except ProbeError as exc:
            clear_probe_fields(asset)
            asset.status = AssetStatus.ERROR
            asset.error_message = _truncate(f"{exc.reason}: {exc.detail}".strip())
        asset.last_seen_at = utcnow()
        indexed = asset.status == AssetStatus.INDEXED
        asset_id_val = asset.id
        session.commit()
        if indexed:
            celery_app.send_task(
                TASK_GENERATE_ASSET_POSTER, args=[asset_id_val], queue=QUEUE_MEDIA
            )
        return {"status": asset.status.value, "asset_id": asset.id}
