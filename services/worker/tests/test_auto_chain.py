"""AAP 自动衔接单元/集成测试（需要 TEST_DATABASE_URL；不需要 ffmpeg / broker）。

锁定：空镜头 AI run 必须 FAILED 且恢复素材状态（假成功修复）；
auto_request_* 活动 run 幂等；ai_budget_exceeded 的 UTC 日口径。
send_task 用桩替换（不连真实 broker）。
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIAnalysisRun,
    AICallLog,
    Asset,
    MediaProcessingRun,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AICallStatus,
    AIRunStatus,
    AssetStatus,
    MediaRunStatus,
)

from clipmind_worker import auto_chain
from clipmind_worker.ai.runner import run_asset_analysis
from clipmind_worker.config import WorkerSettings


def _make_asset(session, *, status=AssetStatus.INDEXED) -> Asset:
    sd = SourceDirectory(
        name=f"ac-{uuid.uuid4().hex[:6]}", mount_path="/app/source",
        include_extensions=["mp4"], exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    session.commit()
    session.refresh(sd)
    a = Asset(
        source_directory_id=sd.id, relative_path=f"{uuid.uuid4().hex[:6]}.mp4",
        normalized_relative_path=f"{uuid.uuid4().hex[:6]}.mp4", filename="v.mp4",
        extension="mp4", file_size=10, status=status,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


class _StubResult:
    id = "stub-task-id"


def test_empty_shots_ai_run_fails_and_restores_status(session, tmp_path):
    """假成功修复：无镜头素材的 AI run 必须 FAILED，素材状态回 INDEXED。"""
    asset = _make_asset(session, status=AssetStatus.INDEXED)
    run = AIAnalysisRun(
        run_uuid=uuid.uuid4().hex, asset_id=asset.id,
        status=AIRunStatus.QUEUED, queued_at=utcnow(),
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    settings = WorkerSettings(data_dir=str(tmp_path), ai_provider="fake")
    result = run_asset_analysis(session, run, asset, settings)

    assert result["status"] == "failed"
    session.refresh(run)
    session.refresh(asset)
    assert run.status == AIRunStatus.FAILED
    assert "拆镜头" in (run.error_message or "")
    assert asset.status == AssetStatus.INDEXED  # 不被污染为 SHOT_SPLIT / 卡在 AI_ANALYZING


def test_auto_request_shot_analysis_idempotent(session, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        auto_chain.celery_app, "send_task",
        lambda name, args=None, queue=None: calls.append((name, args, queue)) or _StubResult(),
    )
    asset = _make_asset(session)

    assert auto_chain.auto_request_shot_analysis(session, asset.id) is True
    assert len(calls) == 1
    run = session.query(MediaProcessingRun).filter_by(asset_id=asset.id).one()
    assert run.status == MediaRunStatus.QUEUED
    assert run.celery_task_id == "stub-task-id"

    # 已有活动 run：幂等 False，不再入队
    assert auto_chain.auto_request_shot_analysis(session, asset.id) is False
    assert len(calls) == 1


def test_auto_request_ai_idempotent(session, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        auto_chain.celery_app, "send_task",
        lambda name, args=None, queue=None: calls.append((name, args, queue)) or _StubResult(),
    )
    asset = _make_asset(session, status=AssetStatus.SHOT_SPLIT)

    assert auto_chain.auto_request_ai(session, asset.id) is True
    assert auto_chain.auto_request_ai(session, asset.id) is False
    assert len(calls) == 1
    run = session.query(AIAnalysisRun).filter_by(asset_id=asset.id).one()
    assert run.status == AIRunStatus.QUEUED


def test_ai_budget_exceeded_utc_day(session):
    asset = _make_asset(session)
    run = AIAnalysisRun(
        run_uuid=uuid.uuid4().hex, asset_id=asset.id,
        status=AIRunStatus.COMPLETED, queued_at=utcnow(),
    )
    session.add(run)
    session.commit()

    def _log(cost, *, days_ago=0):
        row = AICallLog(
            run_id=run.id, asset_id=asset.id, provider="fake", model="m",
            method="analyze", attempt_no=1, est_cost=cost,
            status=AICallStatus.SUCCESS,
        )
        session.add(row)
        session.commit()
        if days_ago:
            row.created_at = utcnow() - timedelta(days=days_ago)
            session.commit()

    _log(0.30)
    _log(0.25)
    _log(9.99, days_ago=2)  # 昨天之前的花费不计入今日

    spent = auto_chain.ai_spent_today(session)
    assert abs(spent - 0.55) < 1e-6
    assert auto_chain.ai_budget_exceeded(session, 0.5) is True
    assert auto_chain.ai_budget_exceeded(session, 1.0) is False
    assert auto_chain.ai_budget_exceeded(session, 0) is False  # 0=不限
