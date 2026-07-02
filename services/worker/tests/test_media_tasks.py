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
    """当前代次 READY 镜头（PR-C：retired 历史代次不在默认口径内）。"""
    return (
        session.execute(
            select(Shot)
            .where(
                Shot.asset_id == asset_id,
                Shot.status == ShotStatus.READY,
                Shot.retired_at.is_(None),
            )
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
        # 关键帧条（默认 aux_keyframes=4）落库 + 文件已搬入该镜头 active 目录
        assert s.keyframe_paths is not None and len(s.keyframe_paths) == 4
        shot_active = os.path.join(
            data_dir, "assets", str(asset.id), "active", "shots", str(s.id)
        )
        for rel in s.keyframe_paths:
            abs_p = _abs(data_dir, rel)
            assert os.path.isfile(abs_p) and os.path.getsize(abs_p) > 0, rel
            assert os.path.dirname(abs_p) == shot_active  # 位于该镜头 active 目录内
    # staging 已清理
    assert not os.path.isdir(os.path.join(data_dir, "assets", str(asset.id), "runs", run.run_uuid))


@needs_ffmpeg
def test_analyze_aux_keyframes_zero_leaves_strip_none(session, tmp_path):
    src = make_test_video(str(tmp_path / "z.mp4"), duration=3, width=160, height=120, fps=10)
    data_dir = os.path.realpath(str(tmp_path / "data"))
    settings = _settings(data_dir, fallback_segment_duration=5.0, min_shot_duration=0.3,
                         aux_keyframes=0)
    asset = _make_asset(session)
    _analyze(session, _new_run(session, asset), asset, settings,
             src_abs=src, data_root_real=data_dir, worker_name="t")
    for s in _ready_shots(session, asset.id):
        assert s.keyframe_paths is None  # 无辅助帧 → 列存 NULL


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

    # 数量一致（幂等，无重复），当前代次全部为第 2 代；
    # PR-C 代次保留：旧代次镜头**不再物理删除**（retired 只读历史），派生目录保留
    assert len(shots2) == len(shots1)
    assert all(s.generation == 2 for s in shots2)
    all_shots = session.execute(select(Shot).where(Shot.asset_id == asset.id)).scalars().all()
    retired = [s for s in all_shots if s.retired_at is not None]
    assert {s.id for s in retired} == set(old_ids), "旧代次应保留并标记 retired"
    assert all(s.generation == 1 for s in retired)
    assert all(s.status == ShotStatus.READY for s in retired), "retired 镜头保持 READY（只读）"
    for d in old_dirs:
        assert os.path.isdir(d), f"旧代次派生目录应保留（血缘/历史查看）: {d}"
    new_shot_ids = {s.id for s in shots2}
    for s in shots2:
        assert os.path.isfile(_abs(data_dir, s.proxy_path))
        # 新代次关键帧条指向新镜头目录下的真实文件
        assert s.keyframe_paths and len(s.keyframe_paths) == 4
        for rel in s.keyframe_paths:
            assert os.path.isfile(_abs(data_dir, rel)), rel
            assert f"{os.sep}shots{os.sep}{s.id}{os.sep}" in _abs(data_dir, rel)
            assert s.id in new_shot_ids


@needs_ffmpeg
def test_export_survives_reanalysis(session, tmp_path):
    """重分析后导出记录仍可追溯（PR-C：旧镜头保留为 retired，shot_id 不再置空）。"""
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

    # 重分析（PR-C：第一代镜头保留为 retired）
    _analyze(session, _new_run(session, asset), asset, settings,
             src_abs=src, data_root_real=data_dir, worker_name="t2")

    session.expire_all()
    survived = session.get(Export, export_id)
    assert survived is not None, "导出记录应保留"
    assert survived.shot_id == old_shot_id, "旧镜头保留（retired），便利引用不再断开"
    old_shot = session.get(Shot, old_shot_id)
    assert old_shot is not None and old_shot.retired_at is not None
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


def _poster_asset(session, src_root: str, relative_path: str, duration=3.0) -> Asset:
    sd = SourceDirectory(
        name="d", mount_path=src_root, include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    session.commit()
    session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id, relative_path=relative_path,
        normalized_relative_path=relative_path, filename=os.path.basename(relative_path),
        extension="mp4", file_size=1, duration=duration,
        status=AssetStatus.INDEXED, first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@needs_ffmpeg
def test_generate_asset_poster_writes_poster(session, tmp_path):
    from clipmind_worker.media.tasks import _generate_poster

    src_root = os.path.realpath(str(tmp_path / "src"))
    os.makedirs(src_root, exist_ok=True)
    make_test_video(os.path.join(src_root, "p.mp4"), duration=3, width=160, height=120, fps=10)
    data_dir = os.path.realpath(str(tmp_path / "data"))
    settings = _settings(data_dir, allowed_source_roots=src_root)
    asset = _poster_asset(session, src_root, "p.mp4")
    sd = session.get(SourceDirectory, asset.source_directory_id)

    res = _generate_poster(session, asset, sd, settings)
    assert res.get("poster") is True
    assert asset.poster_path == f"assets/{asset.id}/poster.webp"
    poster_abs = os.path.join(data_dir, "assets", str(asset.id), "poster.webp")
    assert os.path.isfile(poster_abs) and os.path.getsize(poster_abs) > 0
    # 海报在 asset 目录下、不在 active/（重分析不会清掉）
    assert "active" not in asset.poster_path


def test_generate_asset_poster_source_missing(session, tmp_path):
    from clipmind_worker.media.tasks import _generate_poster

    src_root = os.path.realpath(str(tmp_path / "src"))
    os.makedirs(src_root, exist_ok=True)
    settings = _settings(os.path.realpath(str(tmp_path / "data")), allowed_source_roots=src_root)
    asset = _poster_asset(session, src_root, "missing.mp4")
    sd = session.get(SourceDirectory, asset.source_directory_id)

    res = _generate_poster(session, asset, sd, settings)
    assert res.get("skipped") is True
    assert asset.poster_path is None  # 源缺失不写海报


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
