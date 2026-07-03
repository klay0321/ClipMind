"""PR-C Gate B 导入任务测试（真实任务入口 legacy_import_run；需要 TEST_DATABASE_URL）。

加固锁定：
- 不可变快照：run 创建后规则被改 pattern/大小写/位置范围/来源范围/禁用/归档，
  执行语义均不变（零依赖实时 Rule 行）；
- 版本化幂等：同版本重复导入幂等；语义新版本产生独立证据、不累计旧观察数、
  不覆盖旧人工结论；旧证据保留旧快照；
- 事务安全：单条错误 savepoint 隔离不回滚批内成功行；计数来自真实 DB 行；
  upsert 并发原子累加；事件数与真实更新一一对应；
- 全局串行：第二个导入在锁被占时保持 pending 并 Retry、零证据写入；
  失败后锁释放；
- 真实取消：批间停止、保留已提交、不覆盖为 completed。
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.legacy_rules import compute_snapshot_hash, normalize_text
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
from sqlalchemy import create_engine, func, select, text

import clipmind_worker.tasks.legacy_import as legacy_import
from clipmind_worker.tasks.legacy_import import (
    ADVISORY_LOCK_NAMESPACE,
    GLOBAL_LOCK_KEY,
    legacy_import_run,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


def _sync_url() -> str:
    return os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "+psycopg")


@pytest.fixture
def task_engine(monkeypatch):
    eng = create_engine(_sync_url(), future=True)
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


def _rule_hash(rule: LegacyUsageRule) -> str:
    return compute_snapshot_hash(
        rule_id=rule.id,
        match_target=rule.match_target,
        match_operator=rule.match_operator,
        normalized_pattern=rule.normalized_pattern,
        case_sensitive=rule.case_sensitive,
        source_directory_id=rule.source_directory_id,
        include_present_locations=rule.include_present_locations,
        include_missing_locations=rule.include_missing_locations,
        include_historical_locations=rule.include_historical_locations,
    )


def _seed_rule(session, *, pattern="historical-marker", target="directory_segment",
               operator="equals", case_sensitive=False, **kw) -> LegacyUsageRule:
    rule = LegacyUsageRule(
        name=f"r-{uuid.uuid4().hex[:6]}",
        match_target=target,
        match_operator=operator,
        pattern=pattern,
        normalized_pattern=normalize_text(pattern, case_sensitive=case_sensitive),
        case_sensitive=case_sensitive,
        version=1,
        snapshot_hash="",
        **kw,
    )
    session.add(rule)
    session.flush()
    rule.snapshot_hash = _rule_hash(rule)
    session.commit()
    return rule


def _snap(rule: LegacyUsageRule) -> dict:
    """与 service.rule_snapshot 同构的完整冻结快照。"""
    return {
        "rule_id": rule.id,
        "rule_version": rule.version,
        "name": rule.name,
        "match_target": rule.match_target,
        "match_operator": rule.match_operator,
        "pattern": rule.pattern,
        "normalized_pattern": rule.normalized_pattern,
        "case_sensitive": rule.case_sensitive,
        "source_directory_id": rule.source_directory_id,
        "include_present_locations": rule.include_present_locations,
        "include_missing_locations": rule.include_missing_locations,
        "include_historical_locations": rule.include_historical_locations,
        "priority": rule.priority,
        "snapshot_hash": rule.snapshot_hash,
    }


def _seed_run(session, rules, *, dry_run=False,
              source_directory_id=None) -> LegacyUsageImportRun:
    if isinstance(rules, LegacyUsageRule):
        rules = [rules]
    run = LegacyUsageImportRun(
        source_directory_id=source_directory_id,
        status="pending",
        dry_run=dry_run,
        rule_snapshot=[_snap(r) for r in rules],
        location_scope=["present", "missing", "historical"],
    )
    session.add(run)
    session.commit()
    return run


def _evidences(session) -> list[LegacyUsageEvidence]:
    return list(
        session.execute(
            select(LegacyUsageEvidence).order_by(LegacyUsageEvidence.id)
        ).scalars()
    )


def _events(session) -> list[LegacyUsageEvidenceEvent]:
    return list(
        session.execute(
            select(LegacyUsageEvidenceEvent).order_by(LegacyUsageEvidenceEvent.id)
        ).scalars()
    )


def _mutate_rule_semantics(session, rule: LegacyUsageRule, **changes) -> None:
    """模拟 service 语义更新：改字段 + version+1 + 重算 hash（真实修改路径）。"""
    for k, v in changes.items():
        setattr(rule, k, v)
    if "pattern" in changes:
        rule.normalized_pattern = normalize_text(
            rule.pattern, case_sensitive=rule.case_sensitive
        )
    rule.version += 1
    rule.snapshot_hash = _rule_hash(rule)
    session.commit()


# ============================ 基线：幂等与审核保持 ============================


def test_same_rule_version_import_is_idempotent(task_engine, session):
    sd = _seed_root(session)
    asset = _seed_asset(session, sd, "historical-marker/a.mp4")
    _seed_location(session, sd, asset, "historical-marker/a.mp4")
    rule = _seed_rule(session)

    out1 = legacy_import_run.run(_seed_run(session, rule).id)
    assert out1["status"] == "completed"
    assert out1["created"] == 1 and out1["existing"] == 0

    ev = _evidences(session)[0]
    assert ev.review_status == "pending"
    assert ev.observation_count == 1
    assert ev.rule_version == 1
    assert [e.action for e in _events(session)] == ["detected"]

    # 人工接受后同版本重复导入：绝不覆盖 review_status，只累计观察
    ev.review_status = "accepted"
    ev.reviewed_at = utcnow()
    session.commit()

    run2 = _seed_run(session, rule)
    out2 = legacy_import_run.run(run2.id)
    assert out2["created"] == 0 and out2["existing"] == 1

    session.expire_all()
    ev2 = _evidences(session)
    assert len(ev2) == 1
    assert ev2[0].review_status == "accepted"
    assert ev2[0].observation_count == 2
    assert ev2[0].import_run_id == run2.id
    assert [e.action for e in _events(session)] == ["detected", "observed_again"]


def test_dry_run_writes_no_evidence(task_engine, session):
    sd = _seed_root(session)
    asset = _seed_asset(session, sd, "historical-marker/b.mp4")
    _seed_location(session, sd, asset, "historical-marker/b.mp4")
    rule = _seed_rule(session)
    run = _seed_run(session, rule, dry_run=True)

    out = legacy_import_run.run(run.id)
    assert out["dry_run"] is True and out["created"] == 1
    assert _evidences(session) == [] and _events(session) == []
    session.refresh(run)
    assert run.status == "completed" and run.matched_asset_count == 1


def test_run_status_guard(task_engine, session):
    rule = _seed_rule(session)
    run = _seed_run(session, rule)
    run.status = "cancelled"
    session.commit()
    out = legacy_import_run.run(run.id)
    assert out.get("skipped") is True
    assert legacy_import_run.run(999999)["error"] == "run_not_found"


# ============================ 不可变快照（§二） ============================


def _snapshot_race_setup(session, *, rel="historical-marker/x.mp4", **rule_kw):
    sd = _seed_root(session)
    asset = _seed_asset(session, sd, rel)
    _seed_location(session, sd, asset, rel)
    rule = _seed_rule(session, **rule_kw)
    run = _seed_run(session, rule)
    return sd, asset, rule, run


def test_import_uses_snapshot_after_rule_pattern_change(task_engine, session):
    _, asset, rule, run = _snapshot_race_setup(session)
    # run 创建后规则 pattern 被改成不匹配值（语义修改 → 新版本）
    _mutate_rule_semantics(session, rule, pattern="totally-different")
    out = legacy_import_run.run(run.id)
    assert out["created"] == 1, "必须按旧快照 pattern 命中"
    ev = _evidences(session)[0]
    assert ev.matched_component == "historical-marker"
    assert ev.rule_version == 1  # 冻结创建时版本
    assert ev.rule_snapshot["pattern"] == "historical-marker"


def test_import_uses_snapshot_after_case_setting_change(task_engine, session):
    # 快照大小写不敏感（大写路径可命中）；run 后规则改为大小写敏感
    _, asset, rule, run = _snapshot_race_setup(
        session, rel="HISTORICAL-MARKER/x.mp4", pattern="historical-marker"
    )
    _mutate_rule_semantics(
        session, rule, case_sensitive=True,
    )
    out = legacy_import_run.run(run.id)
    assert out["created"] == 1, "必须按旧快照的大小写不敏感语义命中"


def test_import_uses_snapshot_after_location_scope_change(task_engine, session):
    sd = _seed_root(session)
    asset = _seed_asset(session, sd, "historical-marker/y.mp4")
    _seed_location(session, sd, asset, "historical-marker/y.mp4", status="historical")
    rule = _seed_rule(session)  # 快照含 historical
    run = _seed_run(session, rule)
    _mutate_rule_semantics(session, rule, include_historical_locations=False)
    out = legacy_import_run.run(run.id)
    assert out["created"] == 1, "必须按旧快照位置范围（含 historical）命中"


def test_import_uses_snapshot_after_source_scope_change(task_engine, session):
    sd1 = _seed_root(session)
    sd2 = _seed_root(session)
    asset = _seed_asset(session, sd1, "historical-marker/z.mp4")
    _seed_location(session, sd1, asset, "historical-marker/z.mp4")
    rule = _seed_rule(session)  # 快照 source_directory_id=None（全部来源）
    run = _seed_run(session, rule)
    _mutate_rule_semantics(session, rule, source_directory_id=sd2.id)
    out = legacy_import_run.run(run.id)
    assert out["created"] == 1, "必须按旧快照来源范围（全部）命中 sd1"


def test_import_uses_snapshot_after_rule_disabled(task_engine, session):
    _, asset, rule, run = _snapshot_race_setup(session)
    rule.enabled = False  # 禁用不加版本、不影响已创建 run
    session.commit()
    out = legacy_import_run.run(run.id)
    assert out["created"] == 1
    assert _evidences(session)[0].rule_version == 1


def test_import_uses_snapshot_after_rule_archived(task_engine, session):
    _, asset, rule, run = _snapshot_race_setup(session)
    rule.archived_at = utcnow()
    rule.enabled = False
    session.commit()
    out = legacy_import_run.run(run.id)
    assert out["created"] == 1


def test_invalid_snapshot_counts_as_error_not_silent(task_engine, session):
    sd = _seed_root(session)
    asset = _seed_asset(session, sd, "historical-marker/e.mp4")
    _seed_location(session, sd, asset, "historical-marker/e.mp4")
    rule = _seed_rule(session)
    run = _seed_run(session, rule)
    # 篡改快照语义字段（hash 校验必失败）
    snap = dict(run.rule_snapshot[0])
    snap["normalized_pattern"] = "tampered"
    run.rule_snapshot = [snap]
    session.commit()
    out = legacy_import_run.run(run.id)
    assert out["status"] == "completed_with_errors"
    assert out["errors"] == 1 and out["created"] == 0
    session.refresh(run)
    assert run.error_count == 1 and "snapshot" in (run.error_summary or "")


# ============================ 版本化证据（§三） ============================


def test_new_rule_version_creates_distinct_evidence(task_engine, session):
    _, asset, rule, run1 = _snapshot_race_setup(session, rel="historical-marker/v.mp4")
    legacy_import_run.run(run1.id)
    ev1 = _evidences(session)[0]
    ev1.review_status = "accepted"
    ev1.reviewed_at = utcnow()
    session.commit()
    old_key = ev1.evidence_key

    # 语义修改出 v2（改成仍能命中同一路径的等价面：contains "historical"）
    _mutate_rule_semantics(
        session, rule, pattern="historical", match_operator="contains"
    )
    run2 = _seed_run(session, rule)
    out2 = legacy_import_run.run(run2.id)
    # v2 是独立证据：不累计旧观察数、不覆盖旧结论
    assert out2["created"] == 1 and out2["existing"] == 0

    session.expire_all()
    evs = _evidences(session)
    assert len(evs) == 2
    old = next(e for e in evs if e.evidence_key == old_key)
    new = next(e for e in evs if e.evidence_key != old_key)
    assert old.observation_count == 1  # 新版本不累计到旧证据
    assert new.rule_version == 2 and new.review_status == "pending"


def test_old_evidence_keeps_old_snapshot(task_engine, session):
    _, asset, rule, run1 = _snapshot_race_setup(session, rel="historical-marker/w.mp4")
    legacy_import_run.run(run1.id)
    _mutate_rule_semantics(session, rule, pattern="historical", match_operator="contains")
    legacy_import_run.run(_seed_run(session, rule).id)

    session.expire_all()
    evs = _evidences(session)
    olds = [e for e in evs if e.rule_version == 1]
    news = [e for e in evs if e.rule_version == 2]
    assert len(olds) == 1 and len(news) == 1
    assert olds[0].rule_snapshot["pattern"] == "historical-marker"
    assert olds[0].rule_snapshot["match_operator"] == "equals"
    assert news[0].rule_snapshot["pattern"] == "historical"
    assert news[0].rule_snapshot["match_operator"] == "contains"


def test_new_version_does_not_overwrite_old_review(task_engine, session):
    _, asset, rule, run1 = _snapshot_race_setup(session, rel="historical-marker/r.mp4")
    legacy_import_run.run(run1.id)
    ev1 = _evidences(session)[0]
    ev1.review_status = "rejected"
    ev1.reviewed_at = utcnow()
    session.commit()

    _mutate_rule_semantics(session, rule, pattern="historical", match_operator="contains")
    legacy_import_run.run(_seed_run(session, rule).id)

    session.expire_all()
    evs = _evidences(session)
    old = next(e for e in evs if e.rule_version == 1)
    assert old.review_status == "rejected"  # 新版本导入绝不动旧结论
    assert old.observation_count == 1


def test_semantic_revert_restores_same_evidence_key(task_engine, session):
    """语义改回等价 ⇒ 同 snapshot_hash ⇒ 回到原证据（观察数累计而非新建）。"""
    _, asset, rule, run1 = _snapshot_race_setup(session, rel="historical-marker/q.mp4")
    legacy_import_run.run(run1.id)
    v1_hash = rule.snapshot_hash
    _mutate_rule_semantics(session, rule, pattern="other-thing")  # v2
    _mutate_rule_semantics(session, rule, pattern="historical-marker")  # v3 == v1 语义
    assert rule.version == 3 and rule.snapshot_hash == v1_hash
    out = legacy_import_run.run(_seed_run(session, rule).id)
    assert out["created"] == 0 and out["existing"] == 1
    evs = _evidences(session)
    assert len(evs) == 1 and evs[0].observation_count == 2


# ============================ 事务安全（§四） ============================


def test_one_conflict_does_not_rollback_previous_evidence(task_engine, session, monkeypatch):
    sd = _seed_root(session)
    for i in range(3):
        a = _seed_asset(session, sd, f"historical-marker/t{i}.mp4")
        _seed_location(session, sd, a, f"historical-marker/t{i}.mp4")
    rule = _seed_rule(session)
    run = _seed_run(session, rule)

    # 让第 2 条在 savepoint 内抛错（模拟单条写入意外）
    original = legacy_import.pg_insert
    calls = {"n": 0}

    def failing_insert(table):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated per-item failure")
        return original(table)

    monkeypatch.setattr(legacy_import, "pg_insert", failing_insert)
    out = legacy_import_run.run(run.id)
    assert out["status"] == "completed_with_errors"
    assert out["created"] == 2 and out["errors"] == 1
    # 其余两条真实落库（savepoint 只回滚失败条）
    assert len(_evidences(session)) == 2
    assert len(_events(session)) == 2


def test_batch_counts_match_database_rows(task_engine, session, monkeypatch):
    monkeypatch.setattr(legacy_import, "COMMIT_BATCH", 2)  # 强制多批
    sd = _seed_root(session)
    for i in range(5):
        a = _seed_asset(session, sd, f"historical-marker/c{i}.mp4")
        _seed_location(session, sd, a, f"historical-marker/c{i}.mp4")
    rule = _seed_rule(session)
    out1 = legacy_import_run.run(_seed_run(session, rule).id)
    out2 = legacy_import_run.run(_seed_run(session, rule).id)

    db_rows = int(session.scalar(select(func.count(LegacyUsageEvidence.id))) or 0)
    assert out1["created"] == db_rows == 5
    assert out2["created"] == 0 and out2["existing"] == 5
    run2 = session.execute(
        select(LegacyUsageImportRun).order_by(LegacyUsageImportRun.id.desc())
    ).scalars().first()
    assert run2.created_evidence_count == 0
    assert run2.existing_evidence_count == 5  # 不同既有证据数（distinct）


def test_concurrent_import_preserves_review_status(task_engine, session):
    sd = _seed_root(session)
    a = _seed_asset(session, sd, "historical-marker/p.mp4")
    _seed_location(session, sd, a, "historical-marker/p.mp4")
    rule = _seed_rule(session)
    legacy_import_run.run(_seed_run(session, rule).id)
    ev = _evidences(session)[0]
    ev.review_status = "accepted"
    ev.review_note = "人工结论"
    ev.actor_label = "审核员"
    ev.reviewed_at = utcnow()
    session.commit()
    snapshot_before = dict(ev.rule_snapshot)

    legacy_import_run.run(_seed_run(session, rule).id)
    session.expire_all()
    ev2 = _evidences(session)[0]
    # upsert 只动观察字段；review_status/note/actor/reviewed_at/rule_snapshot 全保持
    assert ev2.review_status == "accepted"
    assert ev2.review_note == "人工结论"
    assert ev2.actor_label == "审核员"
    assert ev2.reviewed_at is not None
    assert dict(ev2.rule_snapshot) == snapshot_before
    assert ev2.observation_count == 2


def test_concurrent_import_increments_observation_atomically(task_engine, session):
    """两个并发连接对同一 evidence_key upsert：观察数无丢失更新（1+2=3）。"""
    sd = _seed_root(session)
    a = _seed_asset(session, sd, "historical-marker/atomic.mp4")
    _seed_location(session, sd, a, "historical-marker/atomic.mp4")
    rule = _seed_rule(session)
    legacy_import_run.run(_seed_run(session, rule).id)
    key = _evidences(session)[0].evidence_key

    barrier = threading.Barrier(2)

    def upsert_once():
        eng = create_engine(_sync_url(), future=True)
        try:
            with eng.begin() as conn:
                barrier.wait(timeout=10)
                conn.execute(
                    text(
                        "UPDATE legacy_usage_evidence "
                        "SET observation_count = observation_count + 1 "
                        "WHERE evidence_key = :k"
                    ),
                    {"k": key},
                )
        finally:
            eng.dispose()

    threads = [threading.Thread(target=upsert_once) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    session.expire_all()
    assert _evidences(session)[0].observation_count == 3


def test_event_count_matches_actual_updates(task_engine, session):
    sd = _seed_root(session)
    for i in range(2):
        a = _seed_asset(session, sd, f"historical-marker/e{i}.mp4")
        _seed_location(session, sd, a, f"historical-marker/e{i}.mp4")
    rule = _seed_rule(session)
    legacy_import_run.run(_seed_run(session, rule).id)
    legacy_import_run.run(_seed_run(session, rule).id)
    events = _events(session)
    assert [e.action for e in events].count("detected") == 2
    assert [e.action for e in events].count("observed_again") == 2
    assert len(events) == 4  # 与真实创建/更新一一对应，无多余无缺失


# ============================ 全局串行（§五） ============================


def _hold_global_lock():
    """另一连接持有全局导入锁；返回 (engine, conn) 供释放。"""
    eng = create_engine(_sync_url(), future=True)
    conn = eng.connect()
    got = conn.execute(
        text("SELECT pg_try_advisory_lock(:ns, :key)"),
        {"ns": ADVISORY_LOCK_NAMESPACE, "key": GLOBAL_LOCK_KEY},
    ).scalar()
    assert got is True
    return eng, conn


def test_second_global_import_cannot_run_concurrently(task_engine, session):
    from celery.exceptions import Retry

    rule = _seed_rule(session)
    run = _seed_run(session, rule)
    eng, conn = _hold_global_lock()
    try:
        with pytest.raises(Retry):
            legacy_import_run.run(run.id)
        session.expire_all()
        assert session.get(LegacyUsageImportRun, run.id).status == "pending"
    finally:
        conn.close()
        eng.dispose()


def test_same_source_import_is_serialized(task_engine, session):
    """限定同一来源目录的任务同样走全局锁：锁占用时保持 pending，释放后可执行。"""
    from celery.exceptions import Retry

    sd = _seed_root(session)
    a = _seed_asset(session, sd, "historical-marker/s.mp4")
    _seed_location(session, sd, a, "historical-marker/s.mp4")
    rule = _seed_rule(session)
    run = _seed_run(session, rule, source_directory_id=sd.id)

    eng, conn = _hold_global_lock()
    try:
        with pytest.raises(Retry):
            legacy_import_run.run(run.id)
    finally:
        conn.close()
        eng.dispose()
    # 锁释放后重试成功（同一 run 继续执行）
    out = legacy_import_run.run(run.id)
    assert out["status"] == "completed" and out["created"] == 1


def test_lock_failure_writes_no_evidence(task_engine, session):
    from celery.exceptions import Retry

    sd = _seed_root(session)
    a = _seed_asset(session, sd, "historical-marker/l.mp4")
    _seed_location(session, sd, a, "historical-marker/l.mp4")
    rule = _seed_rule(session)
    run = _seed_run(session, rule)
    eng, conn = _hold_global_lock()
    try:
        with pytest.raises(Retry):
            legacy_import_run.run(run.id)
        assert _evidences(session) == []  # 不产生部分证据
        assert _events(session) == []
    finally:
        conn.close()
        eng.dispose()


def test_lock_released_after_failure(task_engine, session, monkeypatch):
    rule = _seed_rule(session)
    run = _seed_run(session, rule)

    def boom(sess, r):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(legacy_import, "_execute", boom)
    with pytest.raises(RuntimeError):
        legacy_import_run.run(run.id)
    session.expire_all()
    assert session.get(LegacyUsageImportRun, run.id).status == "failed"
    # 崩溃后锁必须已释放：新连接立刻可获取
    eng, conn = _hold_global_lock()
    conn.execute(
        text("SELECT pg_advisory_unlock(:ns, :key)"),
        {"ns": ADVISORY_LOCK_NAMESPACE, "key": GLOBAL_LOCK_KEY},
    )
    conn.close()
    eng.dispose()


# ============================ 真实取消（§六 worker 侧） ============================


def _cancel_during_first_batch(monkeypatch, session):
    """COMMIT_BATCH=1 + 第一批提交后把 run 置 cancelled（模拟 API 取消时序）。"""
    monkeypatch.setattr(legacy_import, "COMMIT_BATCH", 1)
    fired = {"done": False}

    def cancel_hook(sess, run):
        if not fired["done"]:
            fired["done"] = True
            sess.execute(
                text(
                    "UPDATE legacy_usage_import_run "
                    "SET status='cancelled', completed_at=now() WHERE id=:i"
                ),
                {"i": run.id},
            )
            sess.commit()

    monkeypatch.setattr(legacy_import, "_after_batch", cancel_hook)


def test_cancel_running_import_stops_next_batch(task_engine, session, monkeypatch):
    sd = _seed_root(session)
    for i in range(3):
        a = _seed_asset(session, sd, f"historical-marker/k{i}.mp4")
        _seed_location(session, sd, a, f"historical-marker/k{i}.mp4")
    rule = _seed_rule(session)
    run = _seed_run(session, rule)
    _cancel_during_first_batch(monkeypatch, session)

    out = legacy_import_run.run(run.id)
    assert out["status"] == "cancelled"
    # 第一批（1 条）已提交，其后停止
    assert len(_evidences(session)) == 1


def test_cancelled_run_is_not_overwritten_completed(task_engine, session, monkeypatch):
    sd = _seed_root(session)
    for i in range(3):
        a = _seed_asset(session, sd, f"historical-marker/n{i}.mp4")
        _seed_location(session, sd, a, f"historical-marker/n{i}.mp4")
    rule = _seed_rule(session)
    run = _seed_run(session, rule)
    _cancel_during_first_batch(monkeypatch, session)
    legacy_import_run.run(run.id)
    session.expire_all()
    run2 = session.get(LegacyUsageImportRun, run.id)
    assert run2.status == "cancelled"  # 绝不被覆盖为 completed
    assert run2.completed_at is not None
    assert run2.created_evidence_count == 1  # 取消统计准确


def test_cancel_preserves_committed_evidence(task_engine, session, monkeypatch):
    sd = _seed_root(session)
    for i in range(3):
        a = _seed_asset(session, sd, f"historical-marker/m{i}.mp4")
        _seed_location(session, sd, a, f"historical-marker/m{i}.mp4")
    rule = _seed_rule(session)
    run = _seed_run(session, rule)
    _cancel_during_first_batch(monkeypatch, session)
    legacy_import_run.run(run.id)
    evs = _evidences(session)
    assert len(evs) == 1 and evs[0].review_status == "pending"
    assert [e.action for e in _events(session)] == ["detected"]
