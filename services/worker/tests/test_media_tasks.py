"""镜头分析核心流程集成测试（需要 TEST_DATABASE_URL + ffmpeg）。

直接调用 _analyze（绕过 Celery 与 advisory lock），覆盖：
拆镜头落库、派生文件生成、原子代次替换（重分析不重复/不留孤儿）、
单镜头短视频、源缺失。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    Export,
    MediaProcessingRun,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AssetStatus,
    ExportStatus,
    MediaRunStatus,
    ShotStatus,
)
from clipmind_shared.testing import ffmpeg_available, make_multi_scene_video, make_test_video
from sqlalchemy import select

from clipmind_worker.config import WorkerSettings
from clipmind_worker.media.tasks import _analyze

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="需要 ffmpeg")


def _settings(data_dir: str, **over) -> WorkerSettings:
    base = dict(
        data_dir=data_dir,
        shot_detector_type="fixed",
        fallback_segment_duration=2.0,
        min_shot_duration=0.5,
        max_shot_duration=30.0,
        proxy_preset="ultrafast",
        proxy_max_height=240,
        disk_min_free_mb=1,
        ffmpeg_timeout=120.0,
    )
    base.update(over)
    return WorkerSettings(**base)


def _make_asset(session, filename: str = "视频 01.mp4") -> Asset:
    sd = SourceDirectory(
        name="d",
        mount_path="/app/source",
        include_extensions=["mp4"],
        exclude_patterns=[],
        recursive=True,
        read_only=True,
    )
    session.add(sd)
    session.commit()
    session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id,
        relative_path=filename,
        normalized_relative_path=filename,
        filename=filename,
        extension="mp4",
        file_size=1000,
        status=AssetStatus.INDEXED,
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def _new_run(session, asset) -> MediaProcessingRun:
    run = MediaProcessingRun(
        run_uuid=uuid.uuid4().hex,
        asset_id=asset.id,
        status=MediaRunStatus.QUEUED,
        queued_at=utcnow(),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _ready_shots(session, asset_id):
    return (
        session.execute(
            select(Shot)
            .where(Shot.asset_id == asset_id, Shot.status == ShotStatus.READY)
            .order_by(Shot.sequence_no)
        )
        .scalars()
        .all()
    )


def _abs(root: str, rel: str) -> str:
    return os.path.join(root, rel.replace("/", os.sep))


@needs_ffmpeg
def test_analyze_creates_shots_and_files(session, tmp_path):
    src = make_multi_scene_video(str(tmp_path / "m.mp4"), scenes=4, seg_duration=2)
    data_dir = os.path.realpath(str(tmp_path / "data"))
    settings = _settings(data_dir)
    asset = _make_asset(session)
    run = _new_run(session, asset)

    result = _analyze(
        session, run, asset, settings,
        src_abs=src, data_root_real=data_dir, worker_name="test",
    )
    assert result["status"] == "completed"

    shots = _ready_shots(session, asset.id)
    assert len(shots) == 4  # 8s / 2s
    session.refresh(asset)
    session.refresh(run)
    assert asset.status == AssetStatus.SHOT_SPLIT
    assert run.status == MediaRunStatus.COMPLETED
    assert run.generation == 1
    assert run.progress == 100
    for i, s in enumerate(shots, start=1):
        assert s.sequence_no == i
        assert s.end_time > s.start_time
        for rel in (s.keyframe_path, s.thumbnail_path, s.proxy_path):
            assert rel is not None
            assert os.path.isfile(_abs(data_dir, rel)), rel
    # staging 已清理
    assert not os.path.isdir(os.path.join(data_dir, "assets", str(asset.id), "runs", run.run_uuid))


@needs_ffmpeg
def test_reanalysis_atomic_replace(session, tmp_path):
    src = make_multi_scene_video(str(tmp_path / "m.mp4"), scenes=3, seg_duration=2)
    data_dir = os.path.realpath(str(tmp_path / "data"))
    settings = _settings(data_dir)
    asset = _make_asset(session)

    run1 = _new_run(session, asset)
    _analyze(session, run1, asset, settings, src_abs=src, data_root_real=data_dir,
             worker_name="t1")
    shots1 = _ready_shots(session, asset.id)
    old_ids = [s.id for s in shots1]
    old_dirs = [os.path.join(data_dir, "assets", str(asset.id), "active", "shots", str(i))
                for i in old_ids]
    assert all(os.path.isdir(d) for d in old_dirs)

    # 第二次分析（同一视频）→ 原子替换
    run2 = _new_run(session, asset)
    _analyze(session, run2, asset, settings, src_abs=src, data_root_real=data_dir,
             worker_name="t2")
    shots2 = _ready_shots(session, asset.id)

    # 数量一致（幂等，无重复），全部为第 2 代，旧镜头与旧目录消失
    assert len(shots2) == len(shots1)
    assert all(s.generation == 2 for s in shots2)
    all_shots = session.execute(select(Shot).where(Shot.asset_id == asset.id)).scalars().all()
    assert all(s.generation == 2 for s in all_shots)  # 旧代次已删除
    for d in old_dirs:
        assert not os.path.isdir(d), f"旧目录应已清理: {d}"
    for s in shots2:
        assert os.path.isfile(_abs(data_dir, s.proxy_path))


@needs_ffmpeg
def test_export_survives_reanalysis(session, tmp_path):
    """重分析删除旧镜头后，导出记录仍可追溯（shot_id 置空、来源快照与文件保留）。"""
    src = make_multi_scene_video(str(tmp_path / "m.mp4"), scenes=3, seg_duration=2)
    data_dir = os.path.realpath(str(tmp_path / "data"))
    settings = _settings(data_dir)
    asset = _make_asset(session)

    _analyze(session, _new_run(session, asset), asset, settings,
             src_abs=src, data_root_real=data_dir, worker_name="t1")
    shot0 = _ready_shots(session, asset.id)[0]

    # 为该镜头创建一条已完成导出（含来源快照 + 真实文件）
    euid = uuid.uuid4().hex
    edir = os.path.join(data_dir, "exports", euid)
    os.makedirs(edir, exist_ok=True)
    with open(os.path.join(edir, "clip.mp4"), "wb") as f:
        f.write(b"CLIP")
    exp = Export(
        export_uuid=euid, asset_id=asset.id, shot_id=shot0.id,
        status=ExportStatus.COMPLETED, mode="reencode",
        source_asset_id=asset.id, source_shot_id=shot0.id,
        source_generation=shot0.generation, source_sequence_no=shot0.sequence_no,
        source_start_time=shot0.start_time, source_end_time=shot0.end_time,
        source_filename=asset.filename, source_relative_path=asset.relative_path,
        output_path=f"exports/{euid}/clip.mp4", filename="clip.mp4",
        queued_at=utcnow(),
    )
    session.add(exp)
    session.commit()
    export_id = exp.id
    old_shot_id = shot0.id

    # 重分析（删除第一代镜头）
    _analyze(session, _new_run(session, asset), asset, settings,
             src_abs=src, data_root_real=data_dir, worker_name="t2")

    session.expire_all()
    survived = session.get(Export, export_id)
    assert survived is not None, "导出记录应保留"
    assert survived.shot_id is None, "旧镜头删除后 shot_id 置空（SET NULL）"
    assert survived.asset_id == asset.id, "Asset 未删 → asset_id 保留"
    assert survived.source_asset_id == asset.id
    assert survived.source_shot_id == old_shot_id
    assert survived.source_filename == asset.filename
    assert survived.source_relative_path == asset.relative_path
    # 已生成文件仍在
    assert os.path.isfile(os.path.join(data_dir, "exports", euid, "clip.mp4"))


@needs_ffmpeg
def test_single_short_video_one_shot(session, tmp_path):
    src = make_test_video(str(tmp_path / "s.mp4"), duration=1, width=160, height=120, fps=10)
    data_dir = os.path.realpath(str(tmp_path / "data"))
    settings = _settings(data_dir, fallback_segment_duration=5.0, min_shot_duration=0.3)
    asset = _make_asset(session)
    run = _new_run(session, asset)
    _analyze(session, run, asset, settings, src_abs=src, data_root_real=data_dir,
             worker_name="t")
    shots = _ready_shots(session, asset.id)
    assert len(shots) == 1


def test_source_missing(session, tmp_path):
    data_dir = os.path.realpath(str(tmp_path / "data"))
    settings = _settings(data_dir)
    asset = _make_asset(session)
    run = _new_run(session, asset)
    result = _analyze(session, run, asset, settings,
                      src_abs=str(tmp_path / "nope.mp4"),
                      data_root_real=data_dir, worker_name="t")
    assert result["status"] == "source_missing"
    session.refresh(asset)
    session.refresh(run)
    assert asset.status == AssetStatus.SOURCE_MISSING
    assert run.status == MediaRunStatus.FAILED
