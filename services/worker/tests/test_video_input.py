"""P2a.1 视频输入打标测试（需要 TEST_DATABASE_URL；FakeProvider，不联网）。

锁定：ai_input_mode=video 且代理可用时走 analyze_video；代理缺失/超限自动
回退关键帧（绝不失败）；模式切换指纹不同（不误命中缓存）。
"""

from __future__ import annotations

import os
import uuid

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import AIAnalysisRun, AIShotAnalysis, Asset, Shot, SourceDirectory
from clipmind_shared.models.enums import AIRunStatus, AssetStatus, ShotStatus
from sqlalchemy import select

from clipmind_worker.ai.runner import run_asset_analysis
from clipmind_worker.config import WorkerSettings


def _settings(data_dir: str, **over) -> WorkerSettings:
    base = dict(data_dir=data_dir, ai_provider="fake", ai_retries=0)
    base.update(over)
    return WorkerSettings(**base)


def _seed(session, data_dir: str, *, with_proxy: bool, proxy_bytes: int = 1024):
    tag = uuid.uuid4().hex[:8]
    sd = SourceDirectory(
        name=f"vi-{tag}", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    session.commit()
    asset = Asset(
        source_directory_id=sd.id, relative_path=f"{tag}.mp4",
        normalized_relative_path=f"{tag}.mp4", filename=f"{tag}.mp4", extension="mp4",
        file_size=10, status=AssetStatus.SHOT_SPLIT,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    session.commit()
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=1, start_time=0.0, end_time=2.0,
        duration=2.0, detector_type="fixed", status=ShotStatus.READY,
    )
    session.add(shot)
    session.commit()
    # 关键帧（frames 回退路径可用）
    kf_rel = f"assets/{asset.id}/active/shots/{shot.id}/kf0.webp"
    kf_abs = os.path.join(data_dir, *kf_rel.split("/"))
    os.makedirs(os.path.dirname(kf_abs), exist_ok=True)
    with open(kf_abs, "wb") as f:
        f.write(f"kf-{shot.id}".encode())
    shot.keyframe_path = kf_rel
    shot.keyframe_paths = [kf_rel]
    if with_proxy:
        px_rel = f"assets/{asset.id}/active/shots/{shot.id}/proxy.mp4"
        px_abs = os.path.join(data_dir, *px_rel.split("/"))
        with open(px_abs, "wb") as f:
            f.write(b"\x00" * proxy_bytes)
        shot.proxy_path = px_rel
    session.commit()
    return asset, shot


def _run(session, asset) -> AIAnalysisRun:
    run = AIAnalysisRun(
        run_uuid=uuid.uuid4().hex, asset_id=asset.id,
        status=AIRunStatus.QUEUED, queued_at=utcnow(),
    )
    session.add(run)
    session.commit()
    return run


def _analysis(session, shot_id) -> AIShotAnalysis:
    return session.execute(
        select(AIShotAnalysis).where(AIShotAnalysis.shot_id == shot_id)
    ).scalar_one()


def test_video_mode_uses_proxy_video(session, tmp_path):
    asset, shot = _seed(session, str(tmp_path), with_proxy=True)
    settings = _settings(str(tmp_path), ai_input_mode="video")
    result = run_asset_analysis(session, _run(session, asset), asset, settings)
    assert result["status"] == "completed"
    row = _analysis(session, shot.id)
    assert "视频输入" in (row.parsed_result or {}).get("one_line", "")
    assert row.input_summary and row.input_summary.get("source") == "proxy_video"


def test_video_mode_falls_back_without_proxy(session, tmp_path):
    asset, shot = _seed(session, str(tmp_path), with_proxy=False)
    settings = _settings(str(tmp_path), ai_input_mode="video")
    result = run_asset_analysis(session, _run(session, asset), asset, settings)
    assert result["status"] == "completed"  # 回退关键帧，绝不因缺代理失败
    row = _analysis(session, shot.id)
    assert "视频输入" not in (row.parsed_result or {}).get("one_line", "")
    assert row.input_summary.get("frames") == 1


def test_video_mode_falls_back_when_oversized(session, tmp_path):
    asset, shot = _seed(session, str(tmp_path), with_proxy=True, proxy_bytes=2 * 1024 * 1024)
    settings = _settings(str(tmp_path), ai_input_mode="video", ai_video_max_mb=1)
    result = run_asset_analysis(session, _run(session, asset), asset, settings)
    assert result["status"] == "completed"
    row = _analysis(session, shot.id)
    assert row.input_summary.get("source") != "proxy_video"  # 超限回退


def test_mode_switch_changes_fingerprint_no_false_cache_hit(session, tmp_path):
    asset, shot = _seed(session, str(tmp_path), with_proxy=True)
    r1 = run_asset_analysis(
        session, _run(session, asset), asset, _settings(str(tmp_path), ai_input_mode="frames")
    )
    assert r1["skipped_cached"] == 0
    fp_frames = _analysis(session, shot.id).input_fingerprint
    # 切 video 模式：指纹不同 → 重新分析而非缓存命中
    r2 = run_asset_analysis(
        session, _run(session, asset), asset, _settings(str(tmp_path), ai_input_mode="video")
    )
    assert r2["skipped_cached"] == 0
    fp_video = _analysis(session, shot.id).input_fingerprint
    assert fp_video != fp_frames
    # 同模式重跑：缓存命中不重复计费
    r3 = run_asset_analysis(
        session, _run(session, asset), asset, _settings(str(tmp_path), ai_input_mode="video")
    )
    assert r3["skipped_cached"] == 1
