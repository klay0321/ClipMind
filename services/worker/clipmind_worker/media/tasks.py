"""PR-02 媒体处理 Celery 任务：镜头分析（拆镜头 + 派生）与片段导出。

设计要点（与扫描任务一致，但镜头分析以 MediaProcessingRun 为事实来源）：
- 互斥：素材级 advisory lock（命名空间 0x4D44，与扫描 0x4C4D 区分）+ 部分唯一索引。
- 进度：DB 行 progress/current_step/completed_shots/heartbeat_at，逐镜头 commit。
- 原子代次替换（重新分析不破坏旧结果）：
    1. 全部派生先写 run staging 目录；
    2. 校验全部输出；
    3. 事务插入新 Shot（PROCESSING，按 shot_id 计算最终路径）→ commit（旧 READY 仍对外）；
    4. 原子搬运 staging 文件到 active/shots/{shot_id}/；
    5. 一次事务：新 Shot 置 READY + 删除旧代次 Shot（原子切换）；
    6. 提交后清理旧派生文件与 staging。
  任意步骤失败 → run FAILED，旧 READY 镜头与文件保持可用。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from clipmind_shared.constants import (
    ERROR_MESSAGE_MAX_LEN,
    TASK_ANALYZE_SHOTS,
    TASK_EXPORT_SHOT_CLIP,
    TASK_GENERATE_ASSET_POSTER,
)
from clipmind_shared.db.base import utcnow
from clipmind_shared.ffprobe import ProbeError, probe_video
from clipmind_shared.models import (
    Asset,
    Export,
    MediaProcessingRun,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    STEP_DERIVING,
    STEP_DETECTING,
    STEP_FINALIZING,
    STEP_PROBING,
    AssetStatus,
    ExportStatus,
    MediaRunStatus,
    ShotStatus,
)
from clipmind_shared.security import (
    PathSecurityError,
    resolve_and_validate_root,
    safe_join_within_root,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clipmind_worker.celery_app import celery_app
from clipmind_worker.config import WorkerSettings, get_settings
from clipmind_worker.db import SessionLocal, engine
from clipmind_worker.media import ffmpeg, storage
from clipmind_worker.media.derive import (
    KEYFRAME_NAME,
    PROXY_NAME,
    THUMBNAIL_NAME,
    MediaConfig,
    derive_shot,
    strip_frame_name,
)
from clipmind_worker.media.detector import ShotConfig, detect_shots

logger = logging.getLogger(__name__)

ADVISORY_LOCK_NAMESPACE = 0x4D44  # "MD" media（与扫描 0x4C4D 区分）

# 素材海报（asset 级派生封面，未分析素材也有；存 assets/{id}/poster.webp，不在 active 下）
POSTER_NAME = "poster.webp"
POSTER_MAX_WIDTH = 480
POSTER_FRACTION = 0.1  # 取片长 10% 处，避开纯黑开头，封面更具代表性


def _truncate(text: str) -> str:
    return text[:ERROR_MESSAGE_MAX_LEN]


# 原子替换的两个故障窗口注入点（生产恒为 no-op；仅供测试 monkeypatch 模拟崩溃，
# 不通过任何 API/配置暴露）。
def _fault_after_insert() -> None:  # T1 已提交新 processing 镜头，文件尚未搬移
    pass


def _fault_after_move() -> None:  # 文件已搬入 active，T2 尚未置 READY/删旧代次
    pass


def _shot_config(s: WorkerSettings) -> ShotConfig:
    return ShotConfig(
        detector_type=s.shot_detector_type,
        scene_threshold=s.scene_threshold,
        min_shot_duration=s.min_shot_duration,
        max_shot_duration=s.max_shot_duration,
        fallback_segment_duration=s.fallback_segment_duration,
        head_padding=s.head_padding,
        tail_padding=s.tail_padding,
    )


def _media_config(s: WorkerSettings) -> MediaConfig:
    return MediaConfig(
        keyframe_max_width=s.keyframe_max_width,
        thumbnail_max_width=s.thumbnail_max_width,
        proxy_max_height=s.proxy_max_height,
        proxy_crf=s.proxy_crf,
        proxy_preset=s.proxy_preset,
        proxy_keep_audio=s.proxy_keep_audio,
        proxy_audio_bitrate=s.proxy_audio_bitrate,
        aux_keyframes=s.aux_keyframes,
        ffmpeg_timeout=s.ffmpeg_timeout,
        ffprobe_timeout=s.ffprobe_timeout,
    )


def _cleanup_before_run(session: Session, root: str, asset_id: int) -> None:
    """清理上次崩溃残留：非 READY 镜头行 + 其 active 目录；陈旧 staging；孤儿 active 目录。"""
    transient = (
        session.execute(
            select(Shot).where(Shot.asset_id == asset_id, Shot.status != ShotStatus.READY)
        )
        .scalars()
        .all()
    )
    for s in transient:
        storage.remove_path(storage.active_shot_dir(root, asset_id, s.id))
        session.delete(s)
    session.commit()

    # 陈旧 staging（同一时刻仅一个活动 run，runs/* 必为崩溃残留）
    rdir = storage.runs_dir(root, asset_id)
    if os.path.isdir(rdir):
        for name in os.listdir(rdir):
            storage.remove_path(os.path.join(rdir, name))

    # 孤儿 active/shots/{id}：无对应 ready Shot 行的目录
    ready_ids = {
        sid
        for (sid,) in session.execute(
            select(Shot.id).where(Shot.asset_id == asset_id, Shot.status == ShotStatus.READY)
        ).all()
    }
    shots_root = os.path.join(storage.active_dir(root, asset_id), "shots")
    if os.path.isdir(shots_root):
        for name in os.listdir(shots_root):
            if not name.isdigit() or int(name) not in ready_ids:
                storage.remove_path(os.path.join(shots_root, name))


def _finalize(
    session: Session,
    root: str,
    run: MediaProcessingRun,
    asset: Asset,
    generation: int,
    staged: list[tuple[int, Any, Any]],
) -> None:
    """原子代次替换：插入新镜头 → 搬运文件 → 一次事务置 READY 并删除旧代次。"""
    new_shots: list[tuple[Shot, Any]] = []
    for seq, boundary, _derived in staged:
        shot = Shot(
            asset_id=asset.id,
            processing_run_id=run.id,
            generation=generation,
            sequence_no=seq,
            start_time=boundary.start,
            end_time=boundary.end,
            duration=boundary.duration,
            detector_type=boundary.detector_type,
            detector_confidence=boundary.confidence,
            status=ShotStatus.PROCESSING,
        )
        session.add(shot)
        new_shots.append((shot, _derived))
    session.flush()  # 取 shot.id

    for shot, derived in new_shots:
        dst = storage.active_shot_dir(root, asset.id, shot.id)
        shot.keyframe_path = storage.relpath(root, os.path.join(dst, KEYFRAME_NAME))
        shot.thumbnail_path = storage.relpath(root, os.path.join(dst, THUMBNAIL_NAME))
        shot.proxy_path = storage.relpath(root, os.path.join(dst, PROXY_NAME))
        shot.keyframe_paths = [
            storage.relpath(root, os.path.join(dst, strip_frame_name(k)))
            for k in range(len(derived.strip))
        ] or None
    session.commit()  # T1：新镜头存在但 PROCESSING（隐藏）；旧 READY 仍对外
    _fault_after_insert()  # 故障窗口 A（测试注入）

    # 搬运 staging → active（同一文件系统，原子重命名）
    for shot, derived in new_shots:
        dst = storage.active_shot_dir(root, asset.id, shot.id)
        storage.ensure_dir(dst)
        storage.atomic_move(derived.keyframe, os.path.join(dst, KEYFRAME_NAME))
        storage.atomic_move(derived.thumbnail, os.path.join(dst, THUMBNAIL_NAME))
        storage.atomic_move(derived.proxy, os.path.join(dst, PROXY_NAME))
        for k, strip_src in enumerate(derived.strip):
            storage.atomic_move(strip_src, os.path.join(dst, strip_frame_name(k)))

    _fault_after_move()  # 故障窗口 B（测试注入）

    # T2：原子切换 —— 新镜头 READY + 删除旧代次镜头
    old_shots = (
        session.execute(
            select(Shot).where(Shot.asset_id == asset.id, Shot.generation < generation)
        )
        .scalars()
        .all()
    )
    old_dirs = [storage.active_shot_dir(root, asset.id, s.id) for s in old_shots]
    for shot, _derived in new_shots:
        shot.status = ShotStatus.READY
    for s in old_shots:
        session.delete(s)
    session.commit()

    # 提交后清理旧派生目录
    for d in old_dirs:
        storage.remove_path(d)


def _analyze(
    session: Session,
    run: MediaProcessingRun,
    asset: Asset,
    settings: WorkerSettings,
    *,
    src_abs: str,
    data_root_real: str,
    worker_name: str,
) -> dict[str, Any]:
    """镜头分析核心流程（无锁；任务包装层负责加锁/异常处理）。可被测试直接调用。"""
    shot_cfg = _shot_config(settings)
    media_cfg = _media_config(settings)

    # 1) 启动 + 分配代次号
    generation = (
        session.execute(
            select(func.coalesce(func.max(MediaProcessingRun.generation), 0)).where(
                MediaProcessingRun.asset_id == asset.id
            )
        ).scalar()
        or 0
    ) + 1
    run.status = MediaRunStatus.RUNNING
    run.started_at = utcnow()
    run.heartbeat_at = utcnow()
    run.worker_name = worker_name
    run.current_step = STEP_PROBING
    run.progress = 0
    run.generation = generation
    run.config_snapshot = {**shot_cfg.to_snapshot(), "media": media_cfg.__dict__}
    asset.status = AssetStatus.PROCESSING
    session.commit()

    # 源缺失：标记后返回（不抛，避免 Celery 重试风暴）
    if not os.path.isfile(src_abs):
        run.status = MediaRunStatus.FAILED
        run.error_message = "source_missing"
        run.finished_at = utcnow()
        asset.status = AssetStatus.SOURCE_MISSING
        session.commit()
        return {"status": "source_missing", "run_id": run.id}

    probe = probe_video(src_abs, timeout=settings.ffprobe_timeout)
    duration = probe.duration
    if duration is None or duration <= 0:
        raise ValueError("unknown_or_zero_duration")
    has_audio = probe.has_audio

    storage.ensure_dir(data_root_real)
    _cleanup_before_run(session, data_root_real, asset.id)
    storage.check_disk_space(data_root_real, settings.disk_min_free_mb)

    # 2) 检测镜头边界
    run.current_step = STEP_DETECTING
    run.heartbeat_at = utcnow()
    session.commit()
    boundaries = detect_shots(src_abs, duration=duration, config=shot_cfg)
    run.total_shots = len(boundaries)
    run.completed_shots = 0
    session.commit()

    # 3) 逐镜头派生到 staging
    run.current_step = STEP_DERIVING
    session.commit()
    staging = storage.run_staging_dir(data_root_real, asset.id, run.run_uuid)
    storage.ensure_dir(staging)
    staged: list[tuple[int, Any, Any]] = []
    total = len(boundaries)
    for i, boundary in enumerate(boundaries, start=1):
        shot_stage = os.path.join(staging, f"shot_{i:04d}")
        derived = derive_shot(src_abs, boundary, shot_stage, has_audio=has_audio, config=media_cfg)
        staged.append((i, boundary, derived))
        run.completed_shots = i
        run.progress = int(i / total * 90)  # 预留 10% 给 finalize
        run.heartbeat_at = utcnow()
        session.commit()

    # 4) 原子代次替换
    run.current_step = STEP_FINALIZING
    run.progress = 90
    session.commit()
    _finalize(session, data_root_real, run, asset, generation, staged)

    run.status = MediaRunStatus.COMPLETED
    run.progress = 100
    run.finished_at = utcnow()
    run.heartbeat_at = utcnow()
    asset.status = AssetStatus.SHOT_SPLIT
    session.commit()

    # 清理本次 run 目录（含 staging）
    storage.remove_path(storage.run_dir(data_root_real, asset.id, run.run_uuid))

    return {
        "run_id": run.id,
        "asset_id": asset.id,
        "generation": generation,
        "shots": total,
        "status": run.status.value,
    }


def _fail_run(run_id: int, asset_id: int, exc: Exception, settings: WorkerSettings) -> None:
    """失败处理：标记 run FAILED，按是否仍有 READY 镜头恢复 asset 状态，清理 staging。"""
    with SessionLocal() as session:
        run = session.get(MediaProcessingRun, run_id)
        run_uuid = run.run_uuid if run else None
        if run is not None:
            run.status = MediaRunStatus.FAILED
            run.error_message = _truncate(str(exc))
            run.finished_at = utcnow()
        asset = session.get(Asset, asset_id)
        if asset is not None:
            has_ready = session.execute(
                select(func.count())
                .select_from(Shot)
                .where(Shot.asset_id == asset_id, Shot.status == ShotStatus.READY)
            ).scalar()
            asset.status = AssetStatus.SHOT_SPLIT if has_ready else AssetStatus.INDEXED
        session.commit()
    if run_uuid:
        try:
            root = storage.data_root(settings.data_dir)
            storage.remove_path(storage.run_dir(root, asset_id, run_uuid))
        except OSError:
            pass


@celery_app.task(name=TASK_ANALYZE_SHOTS, bind=True, acks_late=True)
def analyze_shots(self, run_id: int) -> dict[str, Any]:  # noqa: ANN001
    settings = get_settings()
    with engine.connect() as conn:
        session = Session(bind=conn)
        try:
            run = session.get(MediaProcessingRun, run_id)
            if run is None:
                return {"error": "media_run_not_found", "run_id": run_id}
            if run.status != MediaRunStatus.QUEUED:
                return {"skipped": True, "reason": f"status={run.status.value}"}
            asset = session.get(Asset, run.asset_id)
            if asset is None:
                run.status = MediaRunStatus.FAILED
                run.error_message = "asset_not_found"
                run.finished_at = utcnow()
                session.commit()
                return {"error": "asset_not_found"}
            sd = session.get(SourceDirectory, asset.source_directory_id)
            if sd is None:
                run.status = MediaRunStatus.FAILED
                run.error_message = "source_directory_not_found"
                run.finished_at = utcnow()
                session.commit()
                return {"error": "source_directory_not_found"}

            asset_id = asset.id
            locked = conn.exec_driver_sql(
                "SELECT pg_try_advisory_lock(%s, %s)",
                (ADVISORY_LOCK_NAMESPACE, asset_id),
            ).scalar()
            if not locked:
                return {"skipped": True, "reason": "locked"}

            try:
                src_root = resolve_and_validate_root(sd.mount_path, settings.allowed_roots_list)
                src_abs = safe_join_within_root(src_root, asset.relative_path)
                root = storage.data_root(settings.data_dir)
                return _analyze(
                    session,
                    run,
                    asset,
                    settings,
                    src_abs=src_abs,
                    data_root_real=root,
                    worker_name=self.request.hostname or "",
                )
            except PathSecurityError as exc:
                session.rollback()
                _fail_run(run_id, asset_id, exc, settings)
                return {"error": "path_security", "detail": str(exc)}
            except Exception as exc:  # noqa: BLE001 - 记录失败并向上抛交给 Celery
                session.rollback()
                _fail_run(run_id, asset_id, exc, settings)
                raise
            finally:
                conn.exec_driver_sql(
                    "SELECT pg_advisory_unlock(%s, %s)",
                    (ADVISORY_LOCK_NAMESPACE, asset_id),
                )
        finally:
            session.close()


def _generate_poster(
    session: Session, asset: Asset, sd: SourceDirectory, settings: WorkerSettings
) -> dict[str, Any]:
    """海报生成核心（无 SessionLocal/锁；可被测试直接传 session 调用）。"""
    try:
        src_root = resolve_and_validate_root(sd.mount_path, settings.allowed_roots_list)
        src_abs = safe_join_within_root(src_root, asset.relative_path)
    except PathSecurityError as exc:
        return {"skipped": True, "reason": f"path_security: {exc}"}
    if not os.path.isfile(src_abs):
        return {"skipped": True, "reason": "source_missing"}
    try:
        root = storage.data_root(settings.data_dir)
        storage.check_disk_space(root, settings.disk_min_free_mb)
        adir = storage.ensure_dir(storage.asset_dir(root, asset.id))
        poster_abs = os.path.join(adir, POSTER_NAME)
        duration = asset.duration or 0.0
        ts = min(1.0, duration * POSTER_FRACTION) if duration > 0 else 0.0
        ffmpeg.extract_keyframe(
            src_abs, ts, poster_abs,
            max_width=POSTER_MAX_WIDTH, timeout=settings.ffmpeg_timeout,
        )
        if not os.path.isfile(poster_abs) or os.path.getsize(poster_abs) == 0:
            return {"skipped": True, "reason": "poster_empty"}
        asset.poster_path = storage.relpath(root, poster_abs)
        session.commit()
        return {"asset_id": asset.id, "poster": True}
    except Exception as exc:  # noqa: BLE001 - 海报为锦上添花，失败不影响主流程
        session.rollback()
        return {"skipped": True, "reason": _truncate(str(exc))}


@celery_app.task(name=TASK_GENERATE_ASSET_POSTER, bind=True, acks_late=True)
def generate_asset_poster(self, asset_id: int) -> dict[str, Any]:  # noqa: ANN001
    """从源视频抽一帧生成素材海报（best-effort）：失败仅跳过，绝不写源目录。"""
    settings = get_settings()
    with SessionLocal() as session:
        asset = session.get(Asset, asset_id)
        if asset is None:
            return {"error": "asset_not_found", "asset_id": asset_id}
        sd = session.get(SourceDirectory, asset.source_directory_id)
        if sd is None:
            return {"error": "source_directory_not_found"}
        return _generate_poster(session, asset, sd, settings)


def _export_display_name(source_filename: str, start: float, end: float) -> str:
    """对外下载文件名（来自来源快照，可含中文，由 API 做 RFC5987 编码）。"""
    stem = os.path.splitext(source_filename or "clip")[0]

    def fmt(x: float) -> str:
        return f"{int(x // 60):02d}m{int(x % 60):02d}s"

    return f"{stem}_{fmt(start)}-{fmt(end)}.mp4"


@celery_app.task(name=TASK_EXPORT_SHOT_CLIP, bind=True, acks_late=True)
def export_shot_clip(self, export_id: int) -> dict[str, Any]:  # noqa: ANN001
    settings = get_settings()
    with SessionLocal() as session:
        export = session.get(Export, export_id)
        if export is None:
            return {"error": "export_not_found", "export_id": export_id}
        if export.status != ExportStatus.QUEUED:
            return {"skipped": True, "reason": f"status={export.status.value}"}
        asset = session.get(Asset, export.asset_id)
        if asset is None:
            export.status = ExportStatus.FAILED
            export.error_message = "asset_not_found"
            export.finished_at = utcnow()
            session.commit()
            return {"error": "asset_not_found"}
        sd = session.get(SourceDirectory, asset.source_directory_id)

        export.status = ExportStatus.RUNNING
        export.started_at = utcnow()
        session.commit()

        try:
            # 来源解析使用快照的相对路径（不依赖旧 Shot；asset 仍存在用于白名单根）
            src_root = resolve_and_validate_root(sd.mount_path, settings.allowed_roots_list)
            src_abs = safe_join_within_root(src_root, export.source_relative_path)
            if not os.path.isfile(src_abs):
                raise FileNotFoundError("source_missing")

            root = storage.data_root(settings.data_dir)
            storage.check_disk_space(root, settings.disk_min_free_mb)
            edir = storage.export_dir(root, export.export_uuid)
            storage.ensure_dir(edir)
            out_abs = os.path.join(edir, "clip.mp4")  # 磁盘名固定 ASCII，避免编码问题

            try:
                has_audio = probe_video(src_abs, timeout=settings.ffprobe_timeout).has_audio
            except ProbeError:
                has_audio = False

            ffmpeg.export_clip(
                src_abs,
                export.source_start_time,
                export.source_end_time,
                out_abs,
                mode=export.mode,
                has_audio=has_audio,
                timeout=settings.ffmpeg_timeout,
            )
            ffmpeg.validate_media(out_abs, ffprobe_timeout=settings.ffprobe_timeout)

            export.output_path = storage.relpath(root, out_abs)
            export.filename = _export_display_name(
                export.source_filename, export.source_start_time, export.source_end_time
            )
            export.status = ExportStatus.COMPLETED
            export.finished_at = utcnow()
            session.commit()
            return {"export_id": export.id, "status": export.status.value}
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            failed = session.get(Export, export_id)
            if failed is not None:
                failed.status = ExportStatus.FAILED
                failed.error_message = _truncate(str(exc))
                failed.finished_at = utcnow()
                session.commit()
            raise
