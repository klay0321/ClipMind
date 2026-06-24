"""AI 分析编排核心集成测试（需要 TEST_DATABASE_URL；不需要 ffmpeg / 网络）。

用 FakeProvider 与桩 provider 覆盖：正常完成、缓存去重、无图降级、全失败、致命鉴权错误。
"""

from __future__ import annotations

import os
import uuid

from clipmind_shared.ai import ProviderAuthError, ProviderBadResponse
from clipmind_shared.ai.provider import ProviderCapabilities, ProviderHealth
from clipmind_shared.ai.providers.fake import FakeProvider
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIAnalysisRun,
    AICallLog,
    AIShotAnalysis,
    Asset,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AICallStatus,
    AIRunStatus,
    AIShotAnalysisStatus,
    AssetStatus,
    ShotStatus,
)
from sqlalchemy import select

from clipmind_worker.ai.runner import run_asset_analysis
from clipmind_worker.config import WorkerSettings


def _settings(data_dir: str, **over) -> WorkerSettings:
    base = dict(data_dir=data_dir, ai_provider="fake", ai_retries=0, ai_max_images=8)
    base.update(over)
    return WorkerSettings(**base)


def _make_asset(session) -> Asset:
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    session.commit()
    session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id, relative_path="v.mp4", normalized_relative_path="v.mp4",
        filename="v.mp4", extension="mp4", file_size=1000, status=AssetStatus.SHOT_SPLIT,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def _make_shot(session, asset, data_dir, seq, frames=2) -> Shot:
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=seq,
        start_time=float(seq), end_time=float(seq) + 1.0, duration=1.0,
        detector_type="fixed", status=ShotStatus.READY,
    )
    session.add(shot)
    session.commit()
    session.refresh(shot)
    rels = []
    for k in range(frames):
        rel = f"assets/{asset.id}/active/shots/{shot.id}/kf{k}.webp"
        abspath = os.path.join(data_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "wb") as f:
            f.write(f"{shot.id}-{k}".encode())
        rels.append(rel)
    shot.keyframe_path = rels[0]
    shot.keyframe_paths = rels
    session.commit()
    return shot


def _new_run(session, asset) -> AIAnalysisRun:
    run = AIAnalysisRun(
        run_uuid=uuid.uuid4().hex, asset_id=asset.id,
        status=AIRunStatus.QUEUED, queued_at=utcnow(),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _analyses(session, asset_id):
    return list(
        session.execute(
            select(AIShotAnalysis).where(AIShotAnalysis.asset_id == asset_id)
        ).scalars().all()
    )


class _RaisingProvider:
    name = "stub"

    def __init__(self, exc):
        self._exc = exc
        self._model = "stub-1"

    def capabilities(self):
        return ProviderCapabilities(
            supports_images=True, supports_structured_output=True, max_images_per_call=8
        )

    def health(self):
        return ProviderHealth(ok=True)

    def analyze_frames(self, frames, *, prompt, schema, timeout=30.0):
        raise self._exc


def test_run_completes_and_writes_results(session, tmp_path):
    s = _settings(str(tmp_path))
    asset = _make_asset(session)
    for i in range(1, 4):
        _make_shot(session, asset, str(tmp_path), i)
    run = _new_run(session, asset)

    res = run_asset_analysis(session, run, asset, s, provider=FakeProvider())

    assert res["status"] == "completed"
    assert res["analyzed"] == 3
    assert res["failed"] == 0
    rows = _analyses(session, asset.id)
    assert len(rows) == 3
    assert all(r.status == AIShotAnalysisStatus.COMPLETED for r in rows)
    assert all(r.parsed_result is not None for r in rows)
    assert all(r.input_fingerprint for r in rows)
    calls = session.execute(select(AICallLog)).scalars().all()
    assert len([c for c in calls if c.status == AICallStatus.SUCCESS]) == 3
    session.refresh(asset)
    assert asset.status == AssetStatus.SHOT_SPLIT


def test_cache_skips_second_run(session, tmp_path):
    s = _settings(str(tmp_path))
    asset = _make_asset(session)
    for i in range(1, 3):
        _make_shot(session, asset, str(tmp_path), i)

    run1 = _new_run(session, asset)
    run_asset_analysis(session, run1, asset, s, provider=FakeProvider())

    run2 = _new_run(session, asset)
    res2 = run_asset_analysis(session, run2, asset, s, provider=FakeProvider())
    assert res2["skipped_cached"] == 2
    assert res2["analyzed"] == 0
    assert res2["status"] == "completed"


def test_degraded_when_no_image_support(session, tmp_path):
    s = _settings(str(tmp_path))
    asset = _make_asset(session)
    _make_shot(session, asset, str(tmp_path), 1)
    run = _new_run(session, asset)

    res = run_asset_analysis(
        session, run, asset, s, provider=FakeProvider(supports_images=False)
    )
    assert res["degraded"] is True
    assert res["status"] == "completed"
    rows = _analyses(session, asset.id)
    assert rows and all(r.status == AIShotAnalysisStatus.DEGRADED for r in rows)
    assert all(r.parsed_result is None for r in rows)


def test_all_failed_marks_run_failed(session, tmp_path):
    s = _settings(str(tmp_path))
    asset = _make_asset(session)
    _make_shot(session, asset, str(tmp_path), 1)
    run = _new_run(session, asset)

    res = run_asset_analysis(
        session, run, asset, s, provider=_RaisingProvider(ProviderBadResponse("boom"))
    )
    assert res["failed"] == 1
    assert res["status"] == "failed"
    rows = _analyses(session, asset.id)
    assert rows and rows[0].status == AIShotAnalysisStatus.FAILED


def test_fatal_auth_error_fails_run(session, tmp_path):
    s = _settings(str(tmp_path))
    asset = _make_asset(session)
    _make_shot(session, asset, str(tmp_path), 1)
    _make_shot(session, asset, str(tmp_path), 2)
    run = _new_run(session, asset)

    res = run_asset_analysis(
        session, run, asset, s, provider=_RaisingProvider(ProviderAuthError("nope"))
    )
    assert res["status"] == "failed"
    session.refresh(run)
    assert run.status == AIRunStatus.FAILED
    assert "auth_error" in (run.error_message or "")
