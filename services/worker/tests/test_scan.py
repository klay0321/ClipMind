"""扫描核心逻辑集成测试（需要 TEST_DATABASE_URL + ffmpeg）。

直接调用 _scan_files / _mark_missing（绕过 Celery 与 advisory lock），
覆盖：新增、幂等、修改、缺失标记、重现、损坏文件、忽略不支持格式。
"""

from __future__ import annotations

import os

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Asset, ScanRun, SourceDirectory
from clipmind_shared.models.enums import AssetStatus, ScanRunStatus
from clipmind_shared.testing import ffmpeg_available, make_corrupt_video, make_test_video
from sqlalchemy import func, select, update

from clipmind_worker.scanning.reconcile import ReconcileStats
from clipmind_worker.tasks.scan import _mark_missing, _scan_files


def _stats() -> ReconcileStats:
    return ReconcileStats(full_hash_budget=1 << 40)

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="需要 ffmpeg")


def _make_sd(session, root: str) -> SourceDirectory:
    sd = SourceDirectory(
        name="测试目录",
        mount_path=root,
        include_extensions=["mp4"],
        exclude_patterns=[],
        recursive=True,
        read_only=True,
    )
    session.add(sd)
    session.commit()
    session.refresh(sd)
    return sd


def _new_run(session, sd) -> ScanRun:
    # 关闭该目录现有活动 run（模拟扫描任务完成），避免触发部分唯一索引
    session.execute(
        update(ScanRun)
        .where(
            ScanRun.source_directory_id == sd.id,
            ScanRun.status.in_([ScanRunStatus.QUEUED, ScanRunStatus.RUNNING]),
        )
        .values(status=ScanRunStatus.COMPLETED)
    )
    session.commit()
    run = ScanRun(
        source_directory_id=sd.id,
        status=ScanRunStatus.RUNNING,
        queued_at=utcnow(),
        started_at=utcnow(),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _asset_count(session) -> int:
    return session.scalar(select(func.count()).select_from(Asset))


def _get_asset(session, filename: str) -> Asset:
    return session.execute(select(Asset).where(Asset.filename == filename)).scalar_one()


@needs_ffmpeg
def test_scan_full_lifecycle(session, tmp_path):
    make_test_video(str(tmp_path / "a.mp4"))
    make_test_video(str(tmp_path / "b.mp4"))
    root = os.path.realpath(str(tmp_path))
    sd = _make_sd(session, root)

    # 首次扫描：两个新文件
    run1 = _new_run(session, sd)
    counts1 = _scan_files(session, sd, run1, root, _stats())
    _mark_missing(session, sd.id, run1, _stats())
    assert counts1["discovered"] == 2
    assert counts1["new"] == 2
    assert _asset_count(session) == 2
    assert _get_asset(session, "a.mp4").status == AssetStatus.INDEXED

    # 幂等重扫：无新增/修改，无重复
    run2 = _new_run(session, sd)
    counts2 = _scan_files(session, sd, run2, root, _stats())
    _mark_missing(session, sd.id, run2, _stats())
    assert counts2["new"] == 0
    assert counts2["modified"] == 0
    assert _asset_count(session) == 2

    # 修改 a.mp4（改变时长 -> 改变大小/mtime）
    make_test_video(str(tmp_path / "a.mp4"), duration=2)
    run3 = _new_run(session, sd)
    counts3 = _scan_files(session, sd, run3, root, _stats())
    _mark_missing(session, sd.id, run3, _stats())
    assert counts3["modified"] >= 1
    assert _asset_count(session) == 2

    # 删除 b.mp4 -> 标记缺失
    os.remove(str(tmp_path / "b.mp4"))
    run4 = _new_run(session, sd)
    _scan_files(session, sd, run4, root, _stats())
    missing = _mark_missing(session, sd.id, run4, _stats())
    assert missing == 1
    assert _get_asset(session, "b.mp4").status == AssetStatus.SOURCE_MISSING

    # b.mp4 重新出现 -> 恢复 indexed
    make_test_video(str(tmp_path / "b.mp4"))
    run5 = _new_run(session, sd)
    _scan_files(session, sd, run5, root, _stats())
    _mark_missing(session, sd.id, run5, _stats())
    assert _get_asset(session, "b.mp4").status == AssetStatus.INDEXED


@needs_ffmpeg
def test_scan_corrupt_marks_error(session, tmp_path):
    make_corrupt_video(str(tmp_path / "broken.mp4"))
    root = os.path.realpath(str(tmp_path))
    sd = _make_sd(session, root)
    run = _new_run(session, sd)
    counts = _scan_files(session, sd, run, root, _stats())
    assert counts["errored"] == 1
    broken = _get_asset(session, "broken.mp4")
    assert broken.status == AssetStatus.ERROR
    assert broken.error_message


def test_scan_ignores_unsupported_formats(session, tmp_path):
    (tmp_path / "note.txt").write_bytes(b"hello")
    (tmp_path / "image.jpg").write_bytes(b"x")
    root = os.path.realpath(str(tmp_path))
    sd = _make_sd(session, root)
    run = _new_run(session, sd)
    counts = _scan_files(session, sd, run, root, _stats())
    assert counts["discovered"] == 0
    assert _asset_count(session) == 0
