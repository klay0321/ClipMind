"""AI Worker 任务事务持久化回归测试（需要 TEST_DATABASE_URL）。

针对历史 bug：`_run` 用 `Session(bind=conn)`，在取 advisory lock 前调用 `session.commit()`，
关闭了 session 事务；随后 `exec_driver_sql` 取锁另起连接级事务，session 以 savepoint 加入，
`run_asset_analysis` 内的 commit 仅释放 savepoint，连接关闭时整体回滚 ——
worker 自报成功但 run 仍 queued、ai_shot_analysis/shot_tag 全空。

本测试**经真实任务入口 `_run`**（engine.connect + Session(bind=conn) + advisory lock）执行，
并用**全新 Session / 多次重连**断言数据真正落库，能在旧 savepoint 实现下失败。
不依赖 ffmpeg / 网络（FakeProvider）。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.ai import ProviderAuthError
from clipmind_shared.ai.provider import ProviderCapabilities, ProviderHealth
from clipmind_shared.ai.providers.fake import FakeProvider
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIAnalysisRun,
    AIShotAnalysis,
    Asset,
    Shot,
    ShotTag,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AIRunStatus,
    AssetStatus,
    ShotStatus,
    TagSource,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import clipmind_worker.ai.runner as runner
import clipmind_worker.ai.tasks as tasks
from clipmind_worker.config import WorkerSettings

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def _sync_url() -> str:
    return TEST_DATABASE_URL.replace("+asyncpg", "+psycopg")


def _fresh_session():
    """全新引擎 + 会话（模拟"新连接重新查询"，不复用任务的 session）。"""
    eng = create_engine(_sync_url(), future=True)
    return eng, sessionmaker(bind=eng, expire_on_commit=False)()


class _RaisingProvider:
    name = "stub"

    def __init__(self, exc: Exception):
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


def _seed(session, data_dir: str, *, n_shots: int = 3, frames: int = 2):
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
    for seq in range(1, n_shots + 1):
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
            ap = os.path.join(data_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(ap), exist_ok=True)
            with open(ap, "wb") as f:
                f.write(f"{shot.id}-{k}".encode())
            rels.append(rel)
        shot.keyframe_path = rels[0]
        shot.keyframe_paths = rels
        session.commit()
    run = AIAnalysisRun(
        run_uuid=uuid.uuid4().hex, asset_id=asset.id,
        status=AIRunStatus.QUEUED, queued_at=utcnow(),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return asset.id, run.id


@pytest.fixture
def task_engine(monkeypatch):
    """把 tasks 模块的 engine/SessionLocal 指向测试库，让 _run 在测试库上执行。"""
    if not TEST_DATABASE_URL:
        pytest.skip("需要 TEST_DATABASE_URL")
    eng = create_engine(_sync_url(), future=True)
    monkeypatch.setattr(tasks, "engine", eng)
    monkeypatch.setattr(
        tasks, "SessionLocal", sessionmaker(bind=eng, expire_on_commit=False, autoflush=False)
    )
    yield eng
    eng.dispose()


def _patch(monkeypatch, data_dir, provider):
    s = WorkerSettings(data_dir=str(data_dir), ai_provider="fake", ai_retries=0, ai_max_images=8)
    monkeypatch.setattr(tasks, "get_settings", lambda: s)
    monkeypatch.setattr(runner, "build_provider", lambda settings: provider)


def test_ai_task_persists_results_after_advisory_lock_transaction(
    task_engine, tmp_path, monkeypatch
):
    # 1) 用独立 session 播种，然后关闭它（任务自己开连接）
    eng0, s0 = _fresh_session()
    asset_id, run_id = _seed(s0, str(tmp_path), n_shots=3)
    s0.close()
    eng0.dispose()

    # 2) 经真实任务入口执行
    _patch(monkeypatch, tmp_path, FakeProvider())
    res = tasks._run(run_id, only_shot_id=None, worker_name="test-worker")
    assert res["analyzed"] == 3
    assert res["status"] == "completed"

    # 3) 全新 Session #1：断言真正落库（旧 savepoint 实现会全空 → 此处失败）
    eng1, s1 = _fresh_session()
    run = s1.get(AIAnalysisRun, run_id)
    assert run.status == AIRunStatus.COMPLETED
    assert run.finished_at is not None
    assert run.worker_name == "test-worker"
    assert run.progress == 100
    assert run.total_shots == 3
    assert run.analyzed_shots == 3
    n_shot = s1.execute(
        select(func.count()).select_from(AIShotAnalysis).where(AIShotAnalysis.asset_id == asset_id)
    ).scalar()
    assert n_shot == 3
    n_tag = s1.execute(
        select(func.count())
        .select_from(ShotTag)
        .join(Shot, Shot.id == ShotTag.shot_id)
        .where(
            Shot.asset_id == asset_id,
            ShotTag.active.is_(True),
            ShotTag.source == TagSource.AI,
        )
    ).scalar()
    assert n_tag > 0
    s1.close()
    eng1.dispose()

    # 4) 再开一个全新 Session #2：数据仍在
    eng2, s2 = _fresh_session()
    assert s2.get(AIAnalysisRun, run_id).status == AIRunStatus.COMPLETED
    assert (
        s2.execute(
            select(func.count())
            .select_from(AIShotAnalysis)
            .where(AIShotAnalysis.asset_id == asset_id)
        ).scalar()
        == 3
    )
    s2.close()
    eng2.dispose()


def test_ai_task_persists_failed_run_on_provider_error(task_engine, tmp_path, monkeypatch):
    eng0, s0 = _fresh_session()
    asset_id, run_id = _seed(s0, str(tmp_path), n_shots=2)
    s0.close()
    eng0.dispose()

    _patch(monkeypatch, tmp_path, _RaisingProvider(ProviderAuthError("nope")))
    res = tasks._run(run_id, only_shot_id=None, worker_name="test-worker")
    assert res["status"] == "failed"

    # 全新 Session：run 必须持久化为 failed（绝不停留在 queued）+ error_message 落库
    eng1, s1 = _fresh_session()
    run = s1.get(AIAnalysisRun, run_id)
    assert run.status == AIRunStatus.FAILED
    assert run.status != AIRunStatus.QUEUED
    assert (run.error_message or "") != ""
    s1.close()
    eng1.dispose()
