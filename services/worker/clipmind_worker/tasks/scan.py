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
from clipmind_shared.models import Asset, AssetLocation, ScanRun, SourceDirectory
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
from clipmind_worker.scanning.reconcile import (
    ReconcileStats,
    add_copy_location,
    add_primary_location,
    find_active_location,
    mark_content_conflict,
    match_by_content,
    relink_moved_asset,
    touch_location,
)
from clipmind_worker.scanning.walker import iter_video_files

settings = get_settings()

# advisory lock 命名空间（两个 int4 键：namespace + source_directory_id）
ADVISORY_LOCK_NAMESPACE = 0x4C4D  # "LM"


def _truncate(text: str) -> str:
    return text[:ERROR_MESSAGE_MAX_LEN]


def _probe_and_apply(session: Session, asset: Asset, abs_path: str, counts: dict[str, int]) -> None:
    """FFprobe 并把媒体元数据写入 Asset（新建/接受的内容才调用）。"""
    try:
        probe = probe_video(abs_path, timeout=settings.ffprobe_timeout)
        apply_probe_to_asset(asset, probe)
        asset.status = AssetStatus.INDEXED
        asset.error_message = None
        asset.poster_path = None  # 扫描结束统一重生成
    except ProbeError as exc:
        clear_probe_fields(asset)
        asset.status = AssetStatus.ERROR
        asset.error_message = _truncate(f"{exc.reason}: {exc.detail}".strip())
        counts["errored"] += 1


def _process_file(
    session: Session,
    sd: SourceDirectory,
    run: ScanRun,
    abs_path: str,
    rel: str,
    counts: dict[str, int],
    stats: ReconcileStats,
) -> None:
    norm = normalize_relative_path(rel)
    st = os.stat(abs_path)
    new_mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC)

    # PR-C：路径查找走活动 AssetLocation（路径不再是 Asset 身份）
    loc = find_active_location(session, sd.id, norm)

    if loc is not None:
        asset = session.get(Asset, loc.asset_id)
        if asset is None:  # 理论不可达（FK 保证）
            return
        stats.existing_assets += 1
        stored_size = loc.file_size if loc.file_size is not None else asset.file_size
        stored_mtime = (
            datetime.fromtimestamp(loc.mtime_ns / 1e9, tz=UTC)
            if loc.mtime_ns is not None
            else asset.modified_at
        )
        action = decide_action(
            exists=True,
            is_source_missing=(loc.location_status == "missing"),
            stored_size=stored_size,
            stored_mtime=stored_mtime,
            new_size=st.st_size,
            new_mtime=new_mtime,
        )

        # 场景 A：路径不变、内容不变——touch 位置与投影，不读内容、不 probe
        if not needs_probe(action):
            touch_location(loc, st)
            asset.last_seen_scan_id = run.id
            asset.last_seen_at = utcnow()
            return

        # 路径不变但 size/mtime 变化（或缺失后重现）：用 quick_hash 判定内容是否真变
        quick_hash = compute_quick_hash(abs_path, st.st_size)
        if quick_hash == asset.quick_hash:
            # 内容未变（mtime 漂移 / 文件找回）：恢复 present 并 touch
            touch_location(loc, st)
            if loc.is_primary:
                asset.file_size = st.st_size
                asset.modified_at = new_mtime
            asset.last_seen_scan_id = run.id
            asset.last_seen_at = utcnow()
            if action == FileAction.REAPPEARED and asset.status == AssetStatus.SOURCE_MISSING:
                asset.status = AssetStatus.INDEXED
            return

        # 场景 B：同路径内容被替换——不静默覆盖身份，标 conflict 等人工确认
        asset.last_seen_scan_id = run.id
        asset.last_seen_at = utcnow()
        mark_content_conflict(session, loc, asset, stats)
        counts["modified"] += 1
        return

    # ---- 新路径：内容身份匹配（场景 C/D/E）----
    matched, has_present, qfp_value, ambiguous_ids = match_by_content(
        session, abs_path=abs_path, st=st, stats=stats
    )
    quick_hash = compute_quick_hash(abs_path, st.st_size)

    if matched is not None:
        matched.last_seen_scan_id = run.id
        matched.last_seen_at = utcnow()
        if has_present:
            # 场景 D：复制/多位置——同一 Asset 增加非 primary 位置，不重复分析
            add_copy_location(
                session, matched,
                source_root_id=sd.id, relative_path=rel, normalized_path=norm,
                st=st, stats=stats,
            )
        else:
            # 场景 C：移动/改名——Asset ID 与全部业务数据保留
            relink_moved_asset(
                session, matched,
                source_root_id=sd.id, relative_path=rel, normalized_path=norm,
                st=st, scan_quick_hash=quick_hash, stats=stats,
            )
        return

    # 无权威匹配：新建 Asset（场景 E 的 quick 命中只作候选记录，绝不自动合并）
    ext = os.path.splitext(rel)[1].lstrip(".").lower()
    asset = Asset(source_directory_id=sd.id, first_seen_at=utcnow())
    session.add(asset)
    counts["new"] += 1
    stats.new_assets += 1

    asset.relative_path = rel
    asset.normalized_relative_path = norm
    asset.filename = os.path.basename(rel)
    asset.extension = ext
    # PM：按扩展名判定媒体类型（图片走同一 Asset 管线，无拆镜头/代理派生）
    from clipmind_shared.constants import SUPPORTED_IMAGE_EXTENSIONS

    asset.media_kind = "image" if ext in SUPPORTED_IMAGE_EXTENSIONS else "video"
    asset.file_size = st.st_size
    asset.modified_at = new_mtime
    asset.quick_hash = quick_hash
    if qfp_value is not None:
        asset.quick_fingerprint = qfp_value
        from clipmind_shared.fingerprint import QUICK_FP_VERSION

        asset.quick_fingerprint_version = QUICK_FP_VERSION
        asset.fingerprint_state = "quick_ready"
    asset.metadata_version = METADATA_VERSION
    asset.last_seen_scan_id = run.id
    asset.last_seen_at = utcnow()
    _probe_and_apply(session, asset, abs_path, counts)
    session.flush()  # 取 asset.id 建位置
    add_primary_location(
        session, asset,
        source_root_id=sd.id, relative_path=rel, normalized_path=norm, st=st,
    )
    if ambiguous_ids:
        stats.ambiguous_candidates += 1
        stats.ambiguous.append(
            {"new_asset_id": asset.id, "candidate_asset_ids": ambiguous_ids[:10]}
        )


def _update_run_counts(run: ScanRun, counts: dict[str, int]) -> None:
    run.files_discovered = counts["discovered"]
    run.files_new = counts["new"]
    run.files_modified = counts["modified"]
    run.files_errored = counts["errored"]


def _scan_files(
    session: Session, sd: SourceDirectory, run: ScanRun, root_real: str,
    stats: ReconcileStats,
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
        _process_file(session, sd, run, abs_path, rel, counts, stats)
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


def _mark_missing(
    session: Session, sd_id: int, run: ScanRun, stats: ReconcileStats
) -> int:
    """仅遍历完整成功后调用：位置级缺失标记 + 副本晋升 + 兼容的素材级缺失。"""
    # 1) 位置级：本 root 下本次未 touch 的 present 位置 → missing（历史不物理删除）
    started = run.started_at or utcnow()
    loc_result = session.execute(
        update(AssetLocation)
        .where(
            AssetLocation.source_root_id == sd_id,
            AssetLocation.location_status == "present",
            AssetLocation.last_seen_at < started,
        )
        .values(location_status="missing", missing_at=utcnow())
    )
    missing_locations = loc_result.rowcount or 0
    stats.missing_locations += missing_locations
    session.commit()

    # 2) 副本晋升：primary 缺失但存在其他 present 副本 → 副本成为 primary（内容仍可用）
    orphaned = (
        session.execute(
            select(AssetLocation).where(
                AssetLocation.is_primary.is_(True),
                AssetLocation.location_status == "missing",
            )
        )
        .scalars()
        .all()
    )
    for old_primary in orphaned:
        replacement = (
            session.execute(
                select(AssetLocation).where(
                    AssetLocation.asset_id == old_primary.asset_id,
                    AssetLocation.location_status == "present",
                    AssetLocation.id != old_primary.id,
                ).order_by(AssetLocation.last_seen_at.desc())
            )
            .scalars()
            .first()
        )
        if replacement is None:
            continue
        asset = session.get(Asset, old_primary.asset_id)
        old_primary.is_primary = False
        old_primary.location_status = "historical"
        session.flush()
        replacement.is_primary = True
        if asset is not None:
            asset.source_directory_id = replacement.source_root_id
            asset.relative_path = replacement.relative_path
            asset.normalized_relative_path = replacement.normalized_path
            asset.filename = os.path.basename(replacement.relative_path)
        stats.moved_locations += 1
        stats.moved.append(
            {
                "asset_id": old_primary.asset_id,
                "from": [old_primary.relative_path],
                "to": replacement.relative_path,
                "promoted_copy": True,
            }
        )
    session.commit()

    # 3) 素材级（兼容投影）：本次未见且已无任何 present 位置 → source_missing
    no_present = ~select(AssetLocation.id).where(
        AssetLocation.asset_id == Asset.id,
        AssetLocation.location_status == "present",
    ).exists()
    stmt = (
        update(Asset)
        .where(
            Asset.source_directory_id == sd_id,
            Asset.status != AssetStatus.SOURCE_MISSING,
            (
                (Asset.last_seen_scan_id.is_(None))
                | (Asset.last_seen_scan_id != run.id)
            ),
            no_present,
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
                stats = ReconcileStats(
                    full_hash_budget=settings.scan_full_hash_budget_bytes
                )
                counts = _scan_files(session, sd, run, root_real, stats)
                missing = _mark_missing(session, sd_id, run, stats)

                run.files_missing = missing
                run.reconciliation = stats.to_jsonb()
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
                    **stats.counts(),
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
        old_quick = asset.quick_hash
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

        # PR-C：单素材重扫 = 人工显式接受当前路径内容。内容确实变化时旧内容指纹
        # 全部作废（避免旧哈希把新内容误 relink 到旧身份），位置 conflict → present。
        if old_quick is not None and asset.quick_hash != old_quick:
            asset.full_hash = None
            asset.full_hash_algorithm = None
            asset.content_size = None
            asset.quick_fingerprint = None
            asset.quick_fingerprint_version = None
            asset.fingerprint_state = "pending"
            asset.fingerprint_error = None
        loc = (
            session.execute(
                select(AssetLocation).where(
                    AssetLocation.asset_id == asset.id,
                    AssetLocation.is_primary.is_(True),
                )
            )
            .scalars()
            .first()
        )
        if loc is not None:
            loc.location_status = "present"
            loc.missing_at = None
            loc.file_size = st.st_size
            loc.mtime_ns = st.st_mtime_ns
            loc.last_seen_at = utcnow()
        indexed = asset.status == AssetStatus.INDEXED
        asset_id_val = asset.id
        session.commit()
        if indexed:
            celery_app.send_task(
                TASK_GENERATE_ASSET_POSTER, args=[asset_id_val], queue=QUEUE_MEDIA
            )
        return {"status": asset.status.value, "asset_id": asset.id}
