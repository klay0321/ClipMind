"""PR-C 分级指纹计算任务（quick / full；单资产与批量共用一个 job 任务）。

安全与正确性：
- 源文件只读打开、分块读取（clipmind_shared.fingerprint），绝不写源目录；
- 批量任务内部**串行**处理资产列表：一个 job 同一时刻只顺序读一个文件，
  避免大量并发顺序读占满 NAS；
- 幂等：full_hash 已存在且文件 size/mtime 与位置记录一致时跳过（skipped）；
- 计算期间文件变化（前后 size/mtime_ns 核对不一致）→ 本次结果作废并记 failed，
  绝不写入半截哈希；
- 并发防护：per-asset advisory lock，拿不到锁的资产计 skipped（另一任务在算），
  并发任务不会互相覆盖；
- 进度与失败以 FingerprintJob 数据库行为事实来源；results 只存 asset_id 与受控
  结果值（不存路径、不存完整哈希）。
"""

from __future__ import annotations

import os
from typing import Any

from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN, TASK_FINGERPRINT_JOB
from clipmind_shared.db.base import utcnow
from clipmind_shared.fingerprint import (
    FileChangedDuringHashing,
    compute_full_sha256,
    compute_quick_fingerprint,
)
from clipmind_shared.models import Asset, AssetLocation, FingerprintJob, SourceDirectory
from clipmind_shared.security import (
    PathTraversal,
    resolve_and_validate_root,
    safe_join_within_root,
)
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from clipmind_worker.celery_app import celery_app
from clipmind_worker.config import get_settings
from clipmind_worker.db import engine

settings = get_settings()

# per-asset 指纹互斥（namespace + asset_id）
ADVISORY_LOCK_NAMESPACE = 0x4650  # "FP"


def _truncate(message: str) -> str:
    return message[:ERROR_MESSAGE_MAX_LEN]


def _resolve_abs_path(session: Session, asset: Asset) -> str | None:
    """按兼容投影（= primary 位置）解析源文件绝对路径；缺失/越界返回 None。"""
    sd = session.get(SourceDirectory, asset.source_directory_id)
    if sd is None:
        return None
    try:
        root_real = resolve_and_validate_root(sd.mount_path, settings.allowed_roots_list)
        abs_path = safe_join_within_root(root_real, asset.relative_path)
    except (PathTraversal, Exception):  # noqa: BLE001 - 白名单/穿越失败一律视为不可用
        return None
    return abs_path if os.path.isfile(abs_path) else None


def _primary_location(session: Session, asset_id: int) -> AssetLocation | None:
    return (
        session.execute(
            select(AssetLocation).where(
                AssetLocation.asset_id == asset_id, AssetLocation.is_primary.is_(True)
            )
        )
        .scalars()
        .first()
    )


def _full_hash_fresh(asset: Asset, abs_path: str) -> bool:
    """full_hash 已存在且文件未变化（size 一致）时无需重算。"""
    if not asset.full_hash or asset.fingerprint_state == "stale":
        return False
    try:
        st = os.stat(abs_path)
    except OSError:
        return False
    return asset.content_size == st.st_size


def _process_asset(
    session: Session, job: FingerprintJob, asset_id: int, kind: str
) -> str:
    """处理单个资产，返回受控结果值：ok / skipped / locked / missing / failed / changed。"""
    asset = session.get(Asset, asset_id)
    if asset is None:
        return "missing"
    abs_path = _resolve_abs_path(session, asset)
    if abs_path is None:
        asset.fingerprint_state = "failed"
        asset.fingerprint_error = "源文件缺失或不可访问"
        session.commit()
        return "missing"

    if kind == "full" and _full_hash_fresh(asset, abs_path):
        return "skipped"

    def on_progress(done: int, total: int) -> None:
        pct = int(done * 100 / total) if total else 100
        if pct != job.progress:
            job.progress = pct
            session.commit()

    try:
        if kind == "quick":
            qfp = compute_quick_fingerprint(abs_path)
            asset.quick_fingerprint = qfp.value
            asset.quick_fingerprint_version = qfp.version
            if asset.fingerprint_state in ("pending", "failed", "stale", "quick_ready"):
                asset.fingerprint_state = (
                    "full_ready" if asset.full_hash and asset.fingerprint_state != "stale"
                    else "quick_ready"
                )
        else:
            full = compute_full_sha256(abs_path, progress_cb=on_progress)
            asset.full_hash = full.value
            asset.full_hash_algorithm = full.algorithm
            asset.content_size = full.size
            asset.fingerprint_state = "full_ready"
        asset.fingerprint_error = None
        asset.fingerprinted_at = utcnow()
        loc = _primary_location(session, asset.id)
        if loc is not None:
            st = os.stat(abs_path)
            loc.file_size = st.st_size
            loc.mtime_ns = st.st_mtime_ns
            loc.verified_at = utcnow()
        session.commit()
        return "ok"
    except FileChangedDuringHashing as exc:
        session.rollback()
        asset = session.get(Asset, asset_id)
        if asset is not None:
            asset.fingerprint_state = "failed"
            asset.fingerprint_error = _truncate(f"文件在计算期间变化，结果作废: {exc}")
            session.commit()
        return "changed"
    except OSError as exc:
        session.rollback()
        asset = session.get(Asset, asset_id)
        if asset is not None:
            asset.fingerprint_state = "failed"
            asset.fingerprint_error = _truncate(f"读取失败: {exc}")
            session.commit()
        return "failed"


@celery_app.task(name=TASK_FINGERPRINT_JOB, bind=True, acks_late=True)
def fingerprint_job_run(self, job_id: int) -> dict[str, Any]:  # noqa: ANN001
    with engine.connect() as conn:
        session = Session(bind=conn)
        try:
            job = session.get(FingerprintJob, job_id)
            if job is None:
                return {"error": "job_not_found", "job_id": job_id}
            if job.status not in ("queued",):
                return {"skipped": True, "reason": f"status={job.status}"}

            job.status = "running"
            job.started_at = utcnow()
            job.total_count = len(job.asset_ids)
            session.commit()

            results: dict[str, str] = {}
            completed = skipped = failed = 0
            asset_ids = list(job.asset_ids)
            for asset_id in asset_ids:
                # 经 session 执行（保持在 session 事务内）——直接在裸连接上执行会
                # 隐式开启连接级事务，使后续 session.commit 退化为 savepoint、
                # 连接关闭时整体回滚（advisory lock 是连接级，commit 不释放）。
                locked = session.execute(
                    text("SELECT pg_try_advisory_lock(:ns, :key)"),
                    {"ns": ADVISORY_LOCK_NAMESPACE, "key": asset_id},
                ).scalar()
                if not locked:
                    results[str(asset_id)] = "locked"
                    skipped += 1
                    continue
                try:
                    outcome = _process_asset(session, job, asset_id, job.kind)
                finally:
                    session.execute(
                        text("SELECT pg_advisory_unlock(:ns, :key)"),
                        {"ns": ADVISORY_LOCK_NAMESPACE, "key": asset_id},
                    )
                results[str(asset_id)] = outcome
                if outcome == "ok":
                    completed += 1
                elif outcome == "skipped":
                    skipped += 1
                else:
                    failed += 1
                job.completed_count = completed
                job.skipped_count = skipped
                job.failed_count = failed
                job.progress = 0
                session.commit()

            job.results = results
            job.finished_at = utcnow()
            if failed == 0:
                job.status = "completed"
            elif completed or skipped:
                job.status = "partial"
            else:
                job.status = "failed"
            session.commit()
            return {
                "job_id": job.id,
                "status": job.status,
                "completed": completed,
                "skipped": skipped,
                "failed": failed,
            }
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            job = session.get(FingerprintJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = _truncate(str(exc))
                job.finished_at = utcnow()
                session.commit()
            raise
        finally:
            session.close()
