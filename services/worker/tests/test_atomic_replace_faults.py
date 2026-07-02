"""原子代次替换的故障窗口注入测试（需要 TEST_DATABASE_URL + ffmpeg）。

A. T1 已提交新 processing 镜头、文件尚未搬移时崩溃；
B. 文件已搬入 active、T2 尚未置 READY/删旧代次时崩溃。

两种情况均验证：旧 READY 镜头仍可见/文件在；新 processing 不进入正常镜头列表（仅 READY）；
重试会清理 processing 记录/孤儿目录；重试成功后仅新 generation 为 READY，无重复。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Asset, MediaProcessingRun, Shot, SourceDirectory
from clipmind_shared.models.enums import AssetStatus, MediaRunStatus, ShotStatus
from clipmind_shared.testing import ffmpeg_available, make_multi_scene_video

from clipmind_worker.config import WorkerSettings
from clipmind_worker.media import tasks
from clipmind_worker.media.tasks import _analyze

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="需要 ffmpeg")


def _boom() -> None:
    raise RuntimeError("injected crash")


def _settings(data_dir: str) -> WorkerSettings:
    return WorkerSettings(
        data_dir=data_dir, shot_detector_type="fixed", fallback_segment_duration=2.0,
        min_shot_duration=0.5, max_shot_duration=30.0, proxy_preset="ultrafast",
        proxy_max_height=240, disk_min_free_mb=1, ffmpeg_timeout=120.0,
    )


def _make_asset(session) -> Asset:
    sd = SourceDirectory(name="f", mount_path="/app/source", include_extensions=["mp4"],
                         exclude_patterns=[], recursive=True, read_only=True)
    session.add(sd)
    session.commit()
    session.refresh(sd)
    a = Asset(source_directory_id=sd.id, relative_path="v.mp4",
              normalized_relative_path="v.mp4", filename="v.mp4", extension="mp4",
              file_size=1, status=AssetStatus.INDEXED,
              first_seen_at=utcnow(), last_seen_at=utcnow())
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def _new_run(session, asset) -> int:
    run = MediaProcessingRun(run_uuid=uuid.uuid4().hex, asset_id=asset.id,
                             status=MediaRunStatus.QUEUED, queued_at=utcnow())
    session.add(run)
    session.commit()
    session.refresh(run)
    return run.id


def _ready(session, asset_id):
    """当前代次 READY 镜头（PR-C：retired 历史代次不在默认口径内）。"""
    return (session.query(Shot)
            .filter(Shot.asset_id == asset_id, Shot.status == ShotStatus.READY,
                    Shot.retired_at.is_(None))
            .order_by(Shot.sequence_no).all())


def _by_status(session, asset_id, status):
    return session.query(Shot).filter(Shot.asset_id == asset_id, Shot.status == status).all()


def _run_obj(session, run_id):
    return session.get(MediaProcessingRun, run_id)


def _fail_run(session, run_id, asset):
    """模拟任务包装层失败处理：run 标 FAILED、asset 回退（保留旧 ready 则 shot_split）。"""
    session.rollback()
    r = _run_obj(session, run_id)
    r.status = MediaRunStatus.FAILED
    a = session.get(Asset, asset.id)
    a.status = AssetStatus.SHOT_SPLIT if _ready(session, asset.id) else AssetStatus.INDEXED
    session.commit()


def _kf_abs(data_dir, shot):
    if not shot.keyframe_path:
        return None
    return os.path.join(data_dir, shot.keyframe_path.replace("/", os.sep))


def _run_fault_scenario(session, tmp_path, monkeypatch, hook_name: str):
    src = make_multi_scene_video(str(tmp_path / "m.mp4"), scenes=3, seg_duration=2)
    data_dir = os.path.realpath(str(tmp_path / "data"))
    settings = _settings(data_dir)
    asset = _make_asset(session)

    # run1：成功 gen1
    _analyze(session, _run_obj(session, _new_run(session, asset)), asset, settings,
             src_abs=src, data_root_real=data_dir, worker_name="t1")
    gen1 = _ready(session, asset.id)
    n = len(gen1)
    gen1_ids = [s.id for s in gen1]
    assert n >= 2
    # 旧文件存在
    for s in gen1:
        assert os.path.isfile(_kf_abs(data_dir, s))

    # run2：注入故障
    monkeypatch.setattr(tasks, hook_name, _boom)
    run2_id = _new_run(session, asset)
    with pytest.raises(RuntimeError):
        _analyze(session, _run_obj(session, run2_id), asset, settings,
                 src_abs=src, data_root_real=data_dir, worker_name="t2")
    _fail_run(session, run2_id, asset)

    # 旧 READY 仍是被服务的集合，文件仍在
    ready_now = _ready(session, asset.id)
    assert [s.id for s in ready_now] == gen1_ids
    for s in ready_now:
        assert os.path.isfile(_kf_abs(data_dir, s))
    # 新 gen2 为 processing，不在 READY 列表
    proc = _by_status(session, asset.id, ShotStatus.PROCESSING)
    assert len(proc) >= 1 and all(s.generation == 2 for s in proc)
    # run2 失败
    assert _run_obj(session, run2_id).status == MediaRunStatus.FAILED

    # run3：去除故障，重试 → 清理 + 成功
    monkeypatch.setattr(tasks, hook_name, lambda: None)
    _analyze(session, _run_obj(session, _new_run(session, asset)), asset, settings,
             src_abs=src, data_root_real=data_dir, worker_name="t3")

    session.expire_all()
    final = session.query(Shot).filter(Shot.asset_id == asset.id).all()
    ready3 = _ready(session, asset.id)
    assert len(ready3) == n, "重试后当前代次 ready 镜头数稳定"
    assert all(s.generation == 3 for s in ready3), "当前代次应为第 3 代"
    # PR-C 代次保留：gen1 保留为 retired（只读历史），目录保留；
    # gen2 的 processing 残留（崩溃产物，从未 READY）仍被清理
    retired = [s for s in final if s.retired_at is not None]
    assert {s.id for s in retired} == set(gen1_ids), "gen1 应保留为 retired"
    assert all(s.status == ShotStatus.READY for s in retired)
    assert not [s for s in final if s.status == ShotStatus.PROCESSING], "processing 残留应清理"
    for sid in gen1_ids:
        d = os.path.join(data_dir, "assets", str(asset.id), "active", "shots", str(sid))
        assert os.path.isdir(d), "retired 代次派生目录应保留"
    # 孤儿目录检查：合法目录 = 全部 READY 镜头（含 retired 历史）
    proc_dirs_root = os.path.join(data_dir, "assets", str(asset.id), "active", "shots")
    legal_ids = {s.id for s in final if s.status == ShotStatus.READY}
    if os.path.isdir(proc_dirs_root):
        for name in os.listdir(proc_dirs_root):
            assert int(name) in legal_ids, f"孤儿目录残留 {name}"


@needs_ffmpeg
def test_fault_after_insert(session, tmp_path, monkeypatch):
    _run_fault_scenario(session, tmp_path, monkeypatch, "_fault_after_insert")


@needs_ffmpeg
def test_fault_after_move(session, tmp_path, monkeypatch):
    _run_fault_scenario(session, tmp_path, monkeypatch, "_fault_after_move")
