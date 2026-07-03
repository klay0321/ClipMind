"""PR-C 稳定素材身份测试：指纹模块 + 扫描 reconcile 场景 A–E（需要 TEST_DATABASE_URL）。

锁定 docs/ASSET_IDENTITY.md 冻结语义：
- 完整 SHA256 是唯一权威身份；quick fingerprint 只筛候选、绝不自动合并；
- 移动 relink 保留 Asset ID 与业务数据；复制 = 多位置不重复分析；
- 同路径内容替换 → conflict + stale，不静默覆盖身份；
- 位置历史不物理删除；中文路径全链路可用。
"""

from __future__ import annotations

import os
import shutil
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.fingerprint import (
    FileChangedDuringHashing,
    compute_full_sha256,
    compute_quick_fingerprint,
    short_hash,
)
from clipmind_shared.models import Asset, AssetLocation, ScanRun, Shot, SourceDirectory
from clipmind_shared.models.enums import (
    AssetStatus,
    ScanRunStatus,
    ShotStatus,
)
from clipmind_shared.testing import ffmpeg_available, make_test_video
from sqlalchemy import select

from clipmind_worker.scanning.reconcile import ReconcileStats
from clipmind_worker.tasks.scan import _mark_missing, _process_file

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="需要 ffmpeg")


# ============================ 指纹模块（纯函数） ============================


def test_quick_fingerprint_stable_and_versioned(tmp_path):
    p = tmp_path / "文件 一.bin"  # 中文路径 + 空格
    p.write_bytes(os.urandom(4 * 1024 * 1024))
    a = compute_quick_fingerprint(str(p))
    b = compute_quick_fingerprint(str(p))
    assert a.value == b.value and a.version == "qfp1" and a.size == p.stat().st_size


def test_quick_fingerprint_differs_on_middle_change(tmp_path):
    """头尾相同、中部不同的文件必须有不同 quick fingerprint（含中部块）。"""
    size = 8 * 1024 * 1024
    head, tail = os.urandom(1024 * 1024), os.urandom(1024 * 1024)
    mid1, mid2 = os.urandom(size - 2 * 1024 * 1024), os.urandom(size - 2 * 1024 * 1024)
    p1, p2 = tmp_path / "a.bin", tmp_path / "b.bin"
    p1.write_bytes(head + mid1 + tail)
    p2.write_bytes(head + mid2 + tail)
    assert compute_quick_fingerprint(str(p1)).value != compute_quick_fingerprint(str(p2)).value


def test_full_sha256_chunked_with_progress(tmp_path):
    import hashlib

    payload = os.urandom(3 * 1024 * 1024 + 7)
    p = tmp_path / "big.bin"
    p.write_bytes(payload)
    seen: list[tuple[int, int]] = []
    res = compute_full_sha256(
        str(p), chunk_size=1024 * 1024, progress_cb=lambda d, t: seen.append((d, t))
    )
    assert res.value == hashlib.sha256(payload).hexdigest()
    assert res.algorithm == "sha256" and res.size == len(payload)
    assert len(seen) == 4 and seen[-1][0] == len(payload)  # 分块进度


def test_full_sha256_aborts_when_file_changes(tmp_path, monkeypatch):
    p = tmp_path / "c.bin"
    p.write_bytes(os.urandom(1024 * 1024))

    import clipmind_shared.fingerprint as fp

    real_stamp = fp.FileStamp.of
    calls = {"n": 0}

    def fake_of(path):
        calls["n"] += 1
        st = real_stamp(path)
        if calls["n"] >= 2:  # 计算后核对时假装 mtime 变了
            return fp.FileStamp(size=st.size, mtime_ns=st.mtime_ns + 999)
        return st

    monkeypatch.setattr(fp.FileStamp, "of", staticmethod(fake_of))
    with pytest.raises(FileChangedDuringHashing):
        fp.compute_full_sha256(str(p))


def test_short_hash():
    assert short_hash(None) is None
    assert short_hash("abcdef1234567890", 8) == "abcdef12"


# ============================ 扫描 reconcile ============================


def _mk_root(session, tmp_path, name="root"):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    sd = SourceDirectory(
        name=f"sd-{name}-{uuid.uuid4().hex[:4]}",
        mount_path=str(d),
        include_extensions=["mp4", "bin"],
        exclude_patterns=[],
        recursive=True,
        read_only=True,
    )
    session.add(sd)
    session.commit()
    session.refresh(sd)
    return sd, d


def _mk_run(session, sd) -> ScanRun:
    # 完结旧活动 run（同目录同一时刻至多一个活动扫描的部分唯一索引）
    for old in session.execute(
        select(ScanRun).where(
            ScanRun.source_directory_id == sd.id,
            ScanRun.status.in_([ScanRunStatus.QUEUED, ScanRunStatus.RUNNING]),
        )
    ).scalars():
        old.status = ScanRunStatus.COMPLETED
        old.finished_at = utcnow()
    session.commit()
    run = ScanRun(
        source_directory_id=sd.id,
        status=ScanRunStatus.RUNNING,
        started_at=utcnow(),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _scan_one(session, sd, run, abs_path, rel, stats=None):
    stats = stats or ReconcileStats(full_hash_budget=1 << 40)
    counts = {"discovered": 0, "new": 0, "modified": 0, "errored": 0}
    _process_file(session, sd, run, str(abs_path), rel, counts, stats)
    session.commit()
    return counts, stats


def _write_media(path, size=256 * 1024):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))


def test_new_file_creates_asset_with_location(session, tmp_path):
    sd, root = _mk_root(session, tmp_path)
    f = root / "子目录" / "素材 A.bin"
    _write_media(f)
    run = _mk_run(session, sd)
    counts, stats = _scan_one(session, sd, run, f, "子目录/素材 A.bin")
    assert counts["new"] == 1 and stats.new_assets == 1
    asset = session.execute(select(Asset)).scalars().first()
    assert asset.quick_fingerprint and asset.quick_fingerprint_version == "qfp1"
    assert asset.fingerprint_state == "quick_ready"
    locs = session.execute(select(AssetLocation)).scalars().all()
    assert len(locs) == 1 and locs[0].is_primary and locs[0].location_status == "present"
    assert locs[0].mtime_ns is not None


def test_scenario_a_unchanged_touch_only(session, tmp_path):
    sd, root = _mk_root(session, tmp_path)
    f = root / "a.bin"
    _write_media(f)
    run1 = _mk_run(session, sd)
    _scan_one(session, sd, run1, f, "a.bin")
    asset = session.execute(select(Asset)).scalars().one()
    fp_before = asset.quick_fingerprint
    run2 = _mk_run(session, sd)
    counts, stats = _scan_one(session, sd, run2, f, "a.bin")
    assert counts["new"] == 0 and stats.existing_assets == 1
    session.refresh(asset)
    assert asset.last_seen_scan_id == run2.id
    assert asset.quick_fingerprint == fp_before


def test_scenario_b_content_replaced_marks_conflict(session, tmp_path):
    """同路径内容替换：conflict + stale，不静默覆盖原身份。"""
    sd, root = _mk_root(session, tmp_path)
    f = root / "b.bin"
    _write_media(f)
    run1 = _mk_run(session, sd)
    _scan_one(session, sd, run1, f, "b.bin")
    asset = session.execute(select(Asset)).scalars().one()
    old_quick = asset.quick_hash

    _write_media(f, size=300 * 1024)  # 替换内容（size 变）
    run2 = _mk_run(session, sd)
    counts, stats = _scan_one(session, sd, run2, f, "b.bin")
    assert stats.content_conflicts == 1 and counts["modified"] == 1
    session.refresh(asset)
    assert asset.fingerprint_state == "stale"
    assert asset.quick_hash == old_quick, "原身份元数据不被覆盖"
    loc = session.execute(select(AssetLocation)).scalars().one()
    assert loc.location_status == "conflict"


def test_scenario_c_move_relinks_same_asset(session, tmp_path):
    """移动/改名：full SHA256 相同 → 同一 Asset relink，业务数据保留。"""
    sd, root = _mk_root(session, tmp_path)
    f = root / "old" / "m.bin"
    _write_media(f)
    run1 = _mk_run(session, sd)
    _scan_one(session, sd, run1, f, "old/m.bin")
    asset = session.execute(select(Asset)).scalars().one()
    asset_id = asset.id
    # 预先具备权威 full_hash（指纹任务已算过）
    full = compute_full_sha256(str(f))
    asset.full_hash = full.value
    asset.full_hash_algorithm = full.algorithm
    asset.content_size = full.size
    asset.fingerprint_state = "full_ready"
    # 挂一个 Shot（业务数据保留的证据）
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=1,
        start_time=0.0, end_time=1.0, duration=1.0,
        detector_type="fixed", status=ShotStatus.READY,
    )
    session.add(shot)
    session.commit()

    # 移动文件 → 旧路径缺失 + 新路径出现
    new_f = root / "已使用区" / "m2.bin"
    new_f.parent.mkdir(parents=True)
    shutil.move(str(f), str(new_f))

    run2 = _mk_run(session, sd)
    stats = ReconcileStats(full_hash_budget=1 << 40)
    # 先按扫描顺序处理新路径（旧路径本轮未发现）
    _scan_one(session, sd, run2, new_f, "已使用区/m2.bin", stats)
    _mark_missing(session, sd.id, run2, stats)

    assert stats.moved_locations == 1
    assets = session.execute(select(Asset)).scalars().all()
    assert len(assets) == 1 and assets[0].id == asset_id, "不重复创建 Asset"
    session.refresh(asset)
    assert asset.normalized_relative_path.endswith("m2.bin"), "投影切到新位置"
    locs = session.execute(select(AssetLocation).order_by(AssetLocation.id)).scalars().all()
    assert len(locs) == 2
    assert locs[0].location_status == "historical" and not locs[0].is_primary
    assert locs[1].location_status == "present" and locs[1].is_primary
    assert session.get(Shot, shot.id) is not None, "业务数据保留"


def test_scenario_d_copy_adds_second_location(session, tmp_path):
    """复制：旧位置仍在 → 同一 Asset 增加非 primary 位置，不重复分析。"""
    sd, root = _mk_root(session, tmp_path)
    f = root / "c1.bin"
    _write_media(f)
    run1 = _mk_run(session, sd)
    _scan_one(session, sd, run1, f, "c1.bin")
    asset = session.execute(select(Asset)).scalars().one()
    full = compute_full_sha256(str(f))
    asset.full_hash = full.value
    asset.full_hash_algorithm = full.algorithm
    asset.content_size = full.size
    session.commit()

    f2 = root / "copy" / "c1-副本.bin"
    f2.parent.mkdir(parents=True)
    shutil.copyfile(str(f), str(f2))
    run2 = _mk_run(session, sd)
    counts, stats = _scan_one(session, sd, run2, f2, "copy/c1-副本.bin")
    assert stats.additional_locations == 1 and counts["new"] == 0
    assets = session.execute(select(Asset)).scalars().all()
    assert len(assets) == 1, "同内容不重复创建 Asset"
    locs = session.execute(select(AssetLocation)).scalars().all()
    assert len(locs) == 2
    primaries = [loc for loc in locs if loc.is_primary]
    assert len(primaries) == 1, "至多一个 primary"


def test_scenario_e_quick_only_is_candidate_not_merge(session, tmp_path):
    """quick 命中但无 full_hash：只记 ambiguous，新建 Asset，绝不自动合并。"""
    sd, root = _mk_root(session, tmp_path)
    f = root / "e1.bin"
    _write_media(f)
    run1 = _mk_run(session, sd)
    _scan_one(session, sd, run1, f, "e1.bin")
    a1 = session.execute(select(Asset)).scalars().one()
    assert a1.full_hash is None  # 未算权威指纹

    f2 = root / "e2.bin"
    shutil.copyfile(str(f), str(f2))  # 同字节 → quick fingerprint 相同
    run2 = _mk_run(session, sd)
    counts, stats = _scan_one(session, sd, run2, f2, "e2.bin")
    assert counts["new"] == 1 and stats.ambiguous_candidates == 1
    assets = session.execute(select(Asset).order_by(Asset.id)).scalars().all()
    assert len(assets) == 2, "不自动合并"
    assert stats.ambiguous[0]["candidate_asset_ids"] == [a1.id]


def test_missing_location_and_reappear(session, tmp_path):
    sd, root = _mk_root(session, tmp_path)
    f = root / "g.bin"
    _write_media(f)
    run1 = _mk_run(session, sd)
    _scan_one(session, sd, run1, f, "g.bin")
    asset = session.execute(select(Asset)).scalars().one()

    # 消失
    payload = f.read_bytes()
    f.unlink()
    run2 = _mk_run(session, sd)
    stats = ReconcileStats(full_hash_budget=1 << 40)
    _mark_missing(session, sd.id, run2, stats)
    loc = session.execute(select(AssetLocation)).scalars().one()
    assert loc.location_status == "missing" and stats.missing_locations == 1
    session.refresh(asset)
    assert asset.status == AssetStatus.SOURCE_MISSING

    # 同内容重现 → present 恢复
    f.write_bytes(payload)
    run3 = _mk_run(session, sd)
    _scan_one(session, sd, run3, f, "g.bin")
    session.refresh(loc)
    session.refresh(asset)
    assert loc.location_status == "present" and loc.missing_at is None
    assert asset.status != AssetStatus.SOURCE_MISSING


@needs_ffmpeg
def test_real_video_new_asset_probe(session, tmp_path):
    """合成视频经新扫描路径仍正常 probe 索引（回归）。"""
    sd, root = _mk_root(session, tmp_path)
    src = make_test_video(str(root / "视频.mp4"), duration=1)
    run = _mk_run(session, sd)
    counts, _ = _scan_one(session, sd, run, src, "视频.mp4")
    assert counts["new"] == 1 and counts["errored"] == 0
    asset = session.execute(select(Asset)).scalars().one()
    assert asset.status == AssetStatus.INDEXED and asset.duration is not None
