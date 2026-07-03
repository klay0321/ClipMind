"""PR-C Gate B 导入任务测试（真实任务入口 legacy_import_run；需要 TEST_DATABASE_URL）。

锁定：幂等（重复运行不增证据、observation_count 累加）、绝不覆盖人工 review_status、
dry_run 零证据写入、location scope 过滤、事件与证据同事务落库。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    AssetLocation,
    LegacyUsageEvidence,
    LegacyUsageEvidenceEvent,
    LegacyUsageImportRun,
    LegacyUsageRule,
    SourceDirectory,
)
from clipmind_shared.models.enums import AssetStatus
from sqlalchemy import create_engine, func, select

import clipmind_worker.tasks.legacy_import as legacy_import
from clipmind_worker.tasks.legacy_import import legacy_import_run

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


@pytest.fixture
def task_engine(monkeypatch):
    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "+psycopg")
    eng = create_engine(url, future=True)
    monkeypatch.setattr(legacy_import, "engine", eng)
    yield eng
    eng.dispose()


def _seed_root(session) -> SourceDirectory:
    sd = SourceDirectory(
        name=f"lu-{uuid.uuid4().hex[:8]}",
        mount_path="/app/source",
        include_extensions=["mp4"],
        exclude_patterns=[],
        recursive=True,
        read_only=True,
    )
    session.add(sd)
    session.commit()
    return sd


def _seed_asset(session, sd, rel: str) -> Asset:
    asset = Asset(
        source_directory_id=sd.id,
        relative_path=rel,
        normalized_relative_path=rel.lower(),
        filename=rel.rsplit("/", 1)[-1],
        extension="mp4",
        file_size=1,
        status=AssetStatus.INDEXED,
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    session.add(asset)
    session.commit()
    return asset


def _seed_location(session, sd, asset, rel: str, status="present") -> AssetLocation:
    loc = AssetLocation(
        asset_id=asset.id,
        source_root_id=sd.id,
        relative_path=rel,
        normalized_path=rel.lower(),
        location_status=status,
        is_primary=status == "present",
    )
    session.add(loc)
    session.commit()
    return loc


def _seed_rule(session, *, pattern="historical-marker", target="directory_segment",
               operator="equals", **kw) -> LegacyUsageRule:
    from clipmind_shared.legacy_rules import normalize_text

    rule = LegacyUsageRule(
        name=f"r-{uuid.uuid4().hex[:6]}",
        match_target=target,
        match_operator=operator,
        pattern=pattern,
        normalized_pattern=normalize_text(pattern),
        **kw,
    )
    session.add(rule)
    session.commit()
    return rule


def _seed_run(session, rule, *, dry_run=False, source_directory_id=None) -> LegacyUsageImportRun:
    run = LegacyUsageImportRun(
        source_directory_id=source_directory_id,
        status="pending",
        dry_run=dry_run,
        rule_snapshot=[
            {
                "rule_id": rule.id,
                "name": rule.name,
                "match_target": rule.match_target,
                "match_operator": rule.match_operator,
                "pattern": rule.pattern,
                "case_sensitive": rule.case_sensitive,
            }
        ],
        location_scope=["present", "missing", "historical"],
    )
    session.add(run)
    session.commit()
    return run


def _counts(session):
    ev = session.scalar(select(func.count(LegacyUsageEvidence.id)))
    evt = session.scalar(select(func.count(LegacyUsageEvidenceEvent.id)))
    return int(ev or 0), int(evt or 0)


def test_import_idempotent_and_never_overwrites_review(task_engine, session):
    sd = _seed_root(session)
    asset = _seed_asset(session, sd, "historical-marker/a.mp4")
    _seed_location(session, sd, asset, "historical-marker/a.mp4")
    rule = _seed_rule(session)
    run1 = _seed_run(session, rule)

    out1 = legacy_import_run.run(run1.id)
    assert out1["status"] == "completed"
    assert out1["created"] == 1 and out1["existing"] == 0

    ev = session.execute(select(LegacyUsageEvidence)).scalars().one()
    assert ev.review_status == "pending"
    assert ev.observation_count == 1
    assert ev.rule_snapshot["pattern"] == "historical-marker"
    events = session.execute(select(LegacyUsageEvidenceEvent)).scalars().all()
    assert [e.action for e in events] == ["detected"]

    # 人工接受后再次导入：绝不覆盖 review_status，只累计观察
    ev.review_status = "accepted"
    ev.reviewed_at = utcnow()
    session.commit()

    run2 = _seed_run(session, rule)
    out2 = legacy_import_run.run(run2.id)
    assert out2["created"] == 0 and out2["existing"] == 1

    session.expire_all()
    ev2 = session.execute(select(LegacyUsageEvidence)).scalars().one()  # 仍只有一条
    assert ev2.review_status == "accepted"
    assert ev2.observation_count == 2
    assert ev2.import_run_id == run2.id
    actions = [
        e.action
        for e in session.execute(
            select(LegacyUsageEvidenceEvent).order_by(LegacyUsageEvidenceEvent.id)
        ).scalars()
    ]
    assert actions == ["detected", "observed_again"]


def test_dry_run_writes_no_evidence(task_engine, session):
    sd = _seed_root(session)
    asset = _seed_asset(session, sd, "historical-marker/b.mp4")
    _seed_location(session, sd, asset, "historical-marker/b.mp4")
    rule = _seed_rule(session)
    run = _seed_run(session, rule, dry_run=True)

    before = _counts(session)
    out = legacy_import_run.run(run.id)
    assert out["dry_run"] is True
    assert out["created"] == 1  # 只是统计"将新建"
    assert _counts(session) == before  # 零写入

    session.refresh(run)
    assert run.status == "completed"
    assert run.matched_asset_count == 1


def test_location_scope_and_source_dir_filtering(task_engine, session):
    sd1 = _seed_root(session)
    sd2 = _seed_root(session)
    a1 = _seed_asset(session, sd1, "historical-marker/c1.mp4")
    a2 = _seed_asset(session, sd2, "historical-marker/c2.mp4")
    _seed_location(session, sd1, a1, "historical-marker/c1.mp4", status="historical")
    _seed_location(session, sd2, a2, "historical-marker/c2.mp4")

    # 规则不含 historical 位置 → sd1 的历史位置不产生证据
    rule = _seed_rule(session, include_historical_locations=False)
    run = _seed_run(session, rule)
    legacy_import_run.run(run.id)
    evs = session.execute(select(LegacyUsageEvidence)).scalars().all()
    assert {e.asset_id for e in evs} == {a2.id}

    # run 限定 sd1 且规则含 historical → 只补 sd1
    rule2 = _seed_rule(session)
    run2 = _seed_run(session, rule2, source_directory_id=sd1.id)
    out2 = legacy_import_run.run(run2.id)
    assert out2["created"] == 1
    session.expire_all()
    run2db = session.get(LegacyUsageImportRun, run2.id)
    assert run2db.scanned_location_count == 1  # 只扫 sd1 的位置


def test_run_status_guard(task_engine, session):
    rule = _seed_rule(session)
    run = _seed_run(session, rule)
    run.status = "cancelled"
    session.commit()
    out = legacy_import_run.run(run.id)
    assert out.get("skipped") is True
    assert legacy_import_run.run(999999)["error"] == "run_not_found"
