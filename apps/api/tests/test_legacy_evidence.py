"""PR-C Gate B 历史使用证据 API 测试（需要 TEST_DATABASE_URL）。

锁定 docs/LEGACY_USAGE_EVIDENCE.md 的隔离铁律：
- 证据 accept 绝不创建 FinalVideoUsage、绝不改变 confirmed_usage_count；
- preview 零写入；规则修改不重解释历史证据（快照冻结）；
- 审核状态机 + 事件 append-only 同事务；批量只作用于显式 id 列表。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.legacy_rules import compute_evidence_key
from clipmind_shared.models import (
    Asset,
    AssetLocation,
    FinalVideo,
    FinalVideoUsage,
    LegacyUsageEvidence,
    LegacyUsageEvidenceEvent,
    LegacyUsageImportRun,
    LegacyUsageRule,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import AssetStatus, ShotStatus
from sqlalchemy import func, select

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


# ============================ 数据工厂 ============================


async def _seed_root(session, name=None) -> SourceDirectory:
    sd = SourceDirectory(
        name=name or f"lu-{uuid.uuid4().hex[:8]}",
        mount_path="/app/source",
        include_extensions=["mp4"],
        exclude_patterns=[],
        recursive=True,
        read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    return sd


async def _seed_asset(session, sd, rel="clip.mp4") -> Asset:
    asset = Asset(
        source_directory_id=sd.id,
        relative_path=rel,
        normalized_relative_path=rel.lower(),
        filename=rel.rsplit("/", 1)[-1],
        extension="mp4",
        file_size=1,
        duration=10.0,
        status=AssetStatus.INDEXED,
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


async def _seed_location(session, sd, asset, rel, status="present",
                         primary=None) -> AssetLocation:
    loc = AssetLocation(
        asset_id=asset.id,
        source_root_id=sd.id,
        relative_path=rel,
        normalized_path=rel.lower(),
        location_status=status,
        is_primary=(status == "present") if primary is None else primary,
    )
    session.add(loc)
    await session.commit()
    await session.refresh(loc)
    return loc


async def _seed_shot(session, asset, seq=1) -> Shot:
    shot = Shot(
        asset_id=asset.id,
        generation=1,
        sequence_no=seq,
        start_time=0.0,
        end_time=2.0,
        duration=2.0,
        detector_type="fixed",
        status=ShotStatus.READY,
        keyframe_path=f"k/{asset.id}-{seq}.jpg",
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    return shot


async def _create_rule(client, *, pattern="historical-marker", target="directory_segment",
                       operator="equals", name=None, expect=201, **extra) -> dict:
    r = await client.post(
        "/api/legacy-usage-rules",
        json={
            "name": name or f"规则-{uuid.uuid4().hex[:6]}",
            "match_target": target,
            "match_operator": operator,
            "pattern": pattern,
            **extra,
        },
    )
    assert r.status_code == expect, r.text
    return r.json()


async def _seed_evidence(session, asset, rule, *, component="historical-marker",
                         target="directory_segment", location_id=None,
                         status="pending") -> LegacyUsageEvidence:
    """模拟 worker 导入产物（API 测试不跑 Celery）；rule 为 API 返回 dict。"""
    ev = LegacyUsageEvidence(
        asset_id=asset.id,
        asset_location_id=location_id,
        rule_id=rule["id"],
        evidence_key=compute_evidence_key(
            rule["snapshot_hash"], asset.id, target, component
        ),
        rule_version=rule.get("version", 1),
        evidence_type="directory_marker" if target == "directory_segment" else "filename_marker",
        matched_target=target,
        matched_component=component,
        rule_snapshot={"rule_id": rule["id"], "pattern": component,
                       "snapshot_hash": rule["snapshot_hash"]},
        review_status=status,
    )
    session.add(ev)
    await session.commit()
    await session.refresh(ev)
    return ev


async def _table_counts(session) -> tuple[int, int, int, int]:
    out = []
    for model in (LegacyUsageRule, LegacyUsageImportRun, LegacyUsageEvidence,
                  LegacyUsageEvidenceEvent):
        out.append(int(await session.scalar(select(func.count(model.id))) or 0))
    return tuple(out)


# ============================ 规则 CRUD ============================


async def test_rule_create_normalizes_and_validates(client):
    rule = await _create_rule(client, pattern=" ＡＢＣ已用 ")
    # strip + NFKC + casefold 存入 normalized（原 pattern 保留 strip 后原样）
    assert rule["pattern"] == "ＡＢＣ已用"
    assert rule["enabled"] is True
    # 白名单校验（服务层 422）
    await _create_rule(client, target="regex", expect=422)
    await _create_rule(client, operator="matches_regex", expect=422)
    await _create_rule(client, pattern="a/../b", expect=422)
    # pydantic 长度校验
    r = await client.post(
        "/api/legacy-usage-rules",
        json={"name": "x", "match_target": "filename", "match_operator": "equals",
              "pattern": "x" * 300},
    )
    assert r.status_code == 422


async def test_rule_lifecycle_enable_archive_restore(client):
    rule = await _create_rule(client)
    rid = rule["id"]
    r = await client.post(f"/api/legacy-usage-rules/{rid}/disable")
    assert r.status_code == 200 and r.json()["enabled"] is False
    r = await client.post(f"/api/legacy-usage-rules/{rid}/enable")
    assert r.status_code == 200 and r.json()["enabled"] is True
    # 归档：停用 + 默认列表不显示 + 禁改
    r = await client.post(f"/api/legacy-usage-rules/{rid}/archive")
    assert r.status_code == 200
    assert r.json()["archived_at"] is not None and r.json()["enabled"] is False
    r = await client.get("/api/legacy-usage-rules")
    assert all(item["id"] != rid for item in r.json()["items"])
    r = await client.get("/api/legacy-usage-rules?include_archived=true")
    assert any(item["id"] == rid for item in r.json()["items"])
    r = await client.patch(f"/api/legacy-usage-rules/{rid}", json={"name": "改名"})
    assert r.status_code == 409
    r = await client.post(f"/api/legacy-usage-rules/{rid}/restore")
    assert r.status_code == 200 and r.json()["archived_at"] is None
    # 404 兜底
    assert (await client.get("/api/legacy-usage-rules/999999")).status_code == 404


async def test_rule_update_recomputes_normalized_but_freezes_history(client, session):
    sd = await _seed_root(session)
    asset = await _seed_asset(session, sd, "historical-marker/a.mp4")
    rule = await _create_rule(client, pattern="historical-marker")
    ev = await _seed_evidence(session, asset, rule)
    old_snapshot = dict(ev.rule_snapshot)

    r = await client.patch(
        f"/api/legacy-usage-rules/{rule['id']}", json={"pattern": "NEW-MARK"}
    )
    assert r.status_code == 200
    assert r.json()["pattern"] == "NEW-MARK"
    # 既有证据快照与匹配事实不被重解释
    await session.refresh(ev)
    assert ev.rule_snapshot == old_snapshot
    assert ev.matched_component == "historical-marker"


async def test_archive_rule_keeps_evidence(client, session):
    sd = await _seed_root(session)
    asset = await _seed_asset(session, sd, "historical-marker/k.mp4")
    rule = await _create_rule(client)
    await _seed_evidence(session, asset, rule)
    r = await client.post(f"/api/legacy-usage-rules/{rule['id']}/archive")
    assert r.status_code == 200
    count = await session.scalar(select(func.count(LegacyUsageEvidence.id)))
    assert count == 1  # 归档不删证据


# ============================ 预览（零写入） ============================


async def test_preview_zero_write_and_counts(client, session):
    sd = await _seed_root(session)
    a1 = await _seed_asset(session, sd, "historical-marker/a.mp4")
    a2 = await _seed_asset(session, sd, "clean/b.mp4")
    await _seed_location(session, sd, a1, "historical-marker/a.mp4")
    await _seed_location(session, sd, a2, "clean/b.mp4")
    rule = await _create_rule(client, pattern="historical-marker")

    before = await _table_counts(session)
    r = await client.post("/api/legacy-usage-imports/preview", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scanned_location_count"] == 2
    assert body["matched_location_count"] == 1
    assert body["matched_asset_count"] == 1
    assert body["would_create_count"] == 1
    assert body["existing_evidence_count"] == 0
    assert body["by_location_status"] == {"present": 1}
    assert len(body["samples"]) == 1
    assert body["samples"][0]["already_exists"] is False
    # 除规则外四表全部零变化（规则是测试自建的）
    after = await _table_counts(session)
    assert after == before

    # 幂等对照：已有证据时 preview 标注 already_exists
    await _seed_evidence(session, a1, rule)
    r = await client.post("/api/legacy-usage-imports/preview", json={})
    body = r.json()
    assert body["would_create_count"] == 0
    assert body["existing_evidence_count"] == 1
    assert body["samples"][0]["already_exists"] is True


async def test_preview_scopes_by_rule_and_source_dir(client, session):
    sd1 = await _seed_root(session)
    sd2 = await _seed_root(session)
    a1 = await _seed_asset(session, sd1, "historical-marker/a.mp4")
    a2 = await _seed_asset(session, sd2, "historical-marker/b.mp4")
    await _seed_location(session, sd1, a1, "historical-marker/a.mp4")
    await _seed_location(session, sd2, a2, "historical-marker/b.mp4")
    rule = await _create_rule(client, pattern="historical-marker")
    # 限定 sd1
    r = await client.post(
        "/api/legacy-usage-imports/preview", json={"source_directory_id": sd1.id}
    )
    assert r.json()["matched_asset_count"] == 1
    # 限定不相关规则 id → 无启用规则可用
    other = await _create_rule(client, pattern="elsewhere")
    r = await client.post(
        "/api/legacy-usage-imports/preview", json={"rule_ids": [other["id"]]}
    )
    assert r.json()["matched_asset_count"] == 0
    _ = rule


# ============================ 导入运行（dispatch/cancel） ============================


async def test_import_run_dispatch_and_snapshot(client, session):
    sd = await _seed_root(session)
    asset = await _seed_asset(session, sd, "historical-marker/a.mp4")
    await _seed_location(session, sd, asset, "historical-marker/a.mp4")
    # 没有启用规则 → 409
    r = await client.post("/api/legacy-usage-imports", json={})
    assert r.status_code == 409
    rule = await _create_rule(client, pattern="historical-marker")

    r = await client.post("/api/legacy-usage-imports", json={"actor_label": "tester"})
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "pending"
    assert run["dry_run"] is False
    # 快照冻结 + 入队 task id（conftest monkeypatch）
    db_run = await session.get(LegacyUsageImportRun, run["id"])
    assert db_run.celery_task_id == f"lutask-{run['id']}"
    assert db_run.rule_snapshot[0]["pattern"] == "historical-marker"
    assert db_run.rule_snapshot[0]["rule_id"] == rule["id"]

    # 列表 + 详情 + 取消
    r = await client.get("/api/legacy-usage-imports")
    assert r.json()["total"] >= 1
    r = await client.post(f"/api/legacy-usage-imports/{run['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    r = await client.post(f"/api/legacy-usage-imports/{run['id']}/cancel")
    assert r.status_code == 409
    assert (await client.get("/api/legacy-usage-imports/999999")).status_code == 404


# ============================ 审核工作流 ============================


async def test_review_transitions_and_events(client, session):
    sd = await _seed_root(session)
    asset = await _seed_asset(session, sd, "historical-marker/a.mp4")
    rule = await _create_rule(client)
    ev = await _seed_evidence(session, asset, rule)

    # accept 携带操作人与备注
    r = await client.post(
        f"/api/legacy-usage-evidence/{ev.id}/accept",
        json={"actor_label": "审核员A", "note": "确认目录语义"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["review_status"] == "accepted"
    assert body["actor_label"] == "审核员A"
    assert body["reviewed_at"] is not None
    # accepted 不能再 accept/reject
    assert (await client.post(f"/api/legacy-usage-evidence/{ev.id}/accept")).status_code == 409
    assert (await client.post(f"/api/legacy-usage-evidence/{ev.id}/reject")).status_code == 409
    # reset → pending → reject → conflict → reset
    r = await client.post(f"/api/legacy-usage-evidence/{ev.id}/reset")
    assert r.json()["review_status"] == "pending"
    assert r.json()["reviewed_at"] is None
    r = await client.post(f"/api/legacy-usage-evidence/{ev.id}/reject")
    assert r.json()["review_status"] == "rejected"
    r = await client.post(f"/api/legacy-usage-evidence/{ev.id}/mark-conflict")
    assert r.json()["review_status"] == "conflict"
    # pending 不能 reset
    r = await client.post(f"/api/legacy-usage-evidence/{ev.id}/reset")
    assert r.json()["review_status"] == "pending"
    assert (await client.post(f"/api/legacy-usage-evidence/{ev.id}/reset")).status_code == 409

    # 事件 append-only：完整轨迹按序保留
    r = await client.get(f"/api/legacy-usage-evidence/{ev.id}/events")
    actions = [e["action"] for e in r.json()["items"]]
    assert actions == [
        "accepted", "reset_to_pending", "rejected", "marked_conflict", "reset_to_pending",
    ]
    assert (await client.get("/api/legacy-usage-evidence/999999")).status_code == 404


async def test_review_event_same_transaction(client, session):
    """状态变化与事件同事务：事件数与动作一一对应，无孤儿状态。"""
    sd = await _seed_root(session)
    asset = await _seed_asset(session, sd, "historical-marker/x.mp4")
    rule = await _create_rule(client)
    ev = await _seed_evidence(session, asset, rule)
    await client.post(f"/api/legacy-usage-evidence/{ev.id}/accept")
    n_events = await session.scalar(
        select(func.count(LegacyUsageEvidenceEvent.id)).where(
            LegacyUsageEvidenceEvent.evidence_id == ev.id
        )
    )
    await session.refresh(ev)
    assert ev.review_status == "accepted"
    assert n_events == 1


async def test_bulk_review_explicit_ids_and_skip(client, session):
    sd = await _seed_root(session)
    asset = await _seed_asset(session, sd, "historical-marker/a.mp4")
    rule = await _create_rule(client)
    e1 = await _seed_evidence(session, asset, rule, component="m1")
    e2 = await _seed_evidence(session, asset, rule, component="m2")
    e3 = await _seed_evidence(session, asset, rule, component="m3", status="rejected")

    r = await client.post(
        "/api/legacy-usage-evidence/bulk-accept",
        json={"evidence_ids": [e1.id, e2.id, e3.id, 999999], "actor_label": "批量员"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["succeeded"] == 2
    assert body["skipped"] == 1 and body["skipped_ids"] == [e3.id]  # 非 pending 跳过
    assert body["failed"] == 1  # 不存在的 id
    # 事件动作为 bulk_accepted
    r = await client.get(f"/api/legacy-usage-evidence/{e1.id}/events")
    assert r.json()["items"][-1]["action"] == "bulk_accepted"
    # 空列表被 pydantic 拒绝
    r = await client.post("/api/legacy-usage-evidence/bulk-reject", json={"evidence_ids": []})
    assert r.status_code == 422


async def test_evidence_list_filters(client, session):
    sd = await _seed_root(session)
    a1 = await _seed_asset(session, sd, "historical-marker/a.mp4")
    a2 = await _seed_asset(session, sd, "historical-marker/b.mp4")
    r1 = await _create_rule(client)
    r2 = await _create_rule(client)
    await _seed_evidence(session, a1, r1, component="c1")
    await _seed_evidence(session, a1, r2, component="c2", status="accepted")
    await _seed_evidence(session, a2, r1, component="c3")

    r = await client.get("/api/legacy-usage-evidence?page=1&page_size=20")
    assert r.json()["total"] == 3
    r = await client.get("/api/legacy-usage-evidence?review_status=pending")
    assert r.json()["total"] == 2
    r = await client.get(f"/api/legacy-usage-evidence?asset_id={a1.id}")
    assert r.json()["total"] == 2
    r = await client.get(f"/api/legacy-usage-evidence?rule_id={r1['id']}")
    assert r.json()["total"] == 2
    r = await client.get(
        f"/api/legacy-usage-evidence?asset_id={a1.id}&review_status=accepted"
    )
    assert r.json()["total"] == 1


# ============================ 隔离铁律：绝不影响正式血缘 ============================


async def test_accept_never_creates_usage_or_changes_confirmed_counts(client, session):
    """核心锁定：accept 前后 FinalVideoUsage 行数与 confirmed 统计完全不变。"""
    sd = await _seed_root(session)
    src = await _seed_asset(session, sd, "historical-marker/src.mp4")
    shot = await _seed_shot(session, src)
    fv_asset = await _seed_asset(session, sd, "finals/out.mp4")
    fv = FinalVideo(asset_id=fv_asset.id, title="正式成片", status="completed")
    session.add(fv)
    await session.commit()
    await session.refresh(fv)
    usage = FinalVideoUsage(
        final_video_id=fv.id,
        source_shot_id=shot.id,
        source_asset_id=src.id,
        source_shot_generation=1,
        status="confirmed",
        evidence_method="manual",
        confirmed_at=utcnow(),
    )
    session.add(usage)
    await session.commit()

    rule = await _create_rule(client)
    ev = await _seed_evidence(session, src, rule)

    async def _confirmed_state():
        usage_rows = int(
            await session.scalar(select(func.count(FinalVideoUsage.id))) or 0
        )
        shot_summary = (await client.get(f"/api/shots/{shot.id}/usage-summary")).json()
        asset_summary = (await client.get(f"/api/assets/{src.id}/usage-summary")).json()
        return usage_rows, shot_summary["confirmed_usage_count"], asset_summary[
            "confirmed_usage_count"
        ], asset_summary["used_shot_count"], asset_summary["distinct_final_video_count"]

    before = await _confirmed_state()
    assert before[0] == 1 and before[1] == 1 and before[2] == 1

    r = await client.post(f"/api/legacy-usage-evidence/{ev.id}/accept")
    assert r.status_code == 200

    after = await _confirmed_state()
    assert after == before  # 一个数字都不许变

    # 证据视图的对照列只是展示，同样不影响
    body = (await client.get(f"/api/legacy-usage-evidence/{ev.id}")).json()
    assert body["confirmed_usage_count"] == 1
    assert body["has_final_video_usage"] is True


async def test_no_final_video_usage_row_references_evidence(client, session):
    """结构性隔离：legacy 表与 final_video_usage 零外键关联（accept 后无新行）。"""
    sd = await _seed_root(session)
    asset = await _seed_asset(session, sd, "historical-marker/only.mp4")
    rule = await _create_rule(client)
    ev = await _seed_evidence(session, asset, rule)
    before = int(await session.scalar(select(func.count(FinalVideoUsage.id))) or 0)
    await client.post(f"/api/legacy-usage-evidence/{ev.id}/accept")
    after = int(await session.scalar(select(func.count(FinalVideoUsage.id))) or 0)
    assert before == after == 0
    # asset summary：历史状态为 used_unknown，但 confirmed 仍为 0 / 无成片
    summary = (await client.get(f"/api/assets/{asset.id}/usage-summary")).json()
    assert summary["confirmed_usage_count"] == 0
    assert summary["distinct_final_video_count"] == 0
    assert summary["legacy_usage_state"] == "legacy_used_unknown"
    assert summary["usage_count_known"] is False
    assert summary["final_video_known"] is False


# ============================ Asset 汇总与派生状态 ============================


async def test_asset_usage_summary_legacy_fields_and_priority(client, session):
    sd = await _seed_root(session)
    asset = await _seed_asset(session, sd, "historical-marker/p.mp4")
    rule = await _create_rule(client)

    # 无证据
    summary = (await client.get(f"/api/assets/{asset.id}/usage-summary")).json()
    assert summary["legacy_usage_state"] == "no_legacy_evidence"
    assert summary["accepted_legacy_evidence_count"] == 0

    # pending
    e1 = await _seed_evidence(session, asset, rule, component="m1")
    summary = (await client.get(f"/api/assets/{asset.id}/usage-summary")).json()
    assert summary["legacy_usage_state"] == "legacy_evidence_pending"
    assert summary["pending_legacy_evidence_count"] == 1

    # rejected（全部驳回）
    await client.post(f"/api/legacy-usage-evidence/{e1.id}/reject")
    summary = (await client.get(f"/api/assets/{asset.id}/usage-summary")).json()
    assert summary["legacy_usage_state"] == "legacy_evidence_rejected"

    # accepted 优先于 pending/rejected
    e2 = await _seed_evidence(session, asset, rule, component="m2")
    await client.post(f"/api/legacy-usage-evidence/{e2.id}/accept")
    summary = (await client.get(f"/api/assets/{asset.id}/usage-summary")).json()
    assert summary["legacy_usage_state"] == "legacy_used_unknown"

    # conflict 最高优先级
    e3 = await _seed_evidence(session, asset, rule, component="m3")
    await client.post(f"/api/legacy-usage-evidence/{e3.id}/mark-conflict")
    summary = (await client.get(f"/api/assets/{asset.id}/usage-summary")).json()
    assert summary["legacy_usage_state"] == "legacy_evidence_conflict"
    assert summary["conflict_legacy_evidence_count"] == 1


async def test_asset_legacy_summary_endpoint(client, session):
    sd = await _seed_root(session)
    asset = await _seed_asset(session, sd, "historical-marker/q.mp4")
    loc = await _seed_location(session, sd, asset, "historical-marker/q.mp4")
    rule = await _create_rule(client)
    await _seed_evidence(session, asset, rule, location_id=loc.id)

    r = await client.get(f"/api/assets/{asset.id}/legacy-usage-summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["legacy_usage_state"] == "legacy_evidence_pending"
    assert body["pending_count"] == 1
    assert len(body["evidences"]) == 1
    e = body["evidences"][0]
    assert e["asset_filename"] == "q.mp4"
    assert e["location_relative_path"] == "historical-marker/q.mp4"
    assert e["rule_name"] == rule["name"]
    assert (await client.get("/api/assets/999999/legacy-usage-summary")).status_code == 404


async def test_shot_summary_not_affected_by_evidence(client, session):
    """Shot usage-summary 不继承 Asset 证据（不均摊）。"""
    sd = await _seed_root(session)
    asset = await _seed_asset(session, sd, "historical-marker/s.mp4")
    shot = await _seed_shot(session, asset)
    rule = await _create_rule(client)
    ev = await _seed_evidence(session, asset, rule)
    await client.post(f"/api/legacy-usage-evidence/{ev.id}/accept")
    summary = (await client.get(f"/api/shots/{shot.id}/usage-summary")).json()
    assert summary["confirmed_usage_count"] == 0
    assert summary["final_videos"] == []


# ============================ 规则版本策略（§三） ============================


async def test_rule_semantic_update_increments_version(client):
    rule = await _create_rule(client, pattern="historical-marker")
    assert rule["version"] == 1
    h1 = rule["snapshot_hash"]
    assert h1 and len(h1) == 64

    # 每个语义字段变化都 +1 且 hash 变
    r = await client.patch(f"/api/legacy-usage-rules/{rule['id']}",
                           json={"pattern": "other"})
    assert r.json()["version"] == 2 and r.json()["snapshot_hash"] != h1
    r = await client.patch(f"/api/legacy-usage-rules/{rule['id']}",
                           json={"match_operator": "contains"})
    assert r.json()["version"] == 3
    r = await client.patch(f"/api/legacy-usage-rules/{rule['id']}",
                           json={"case_sensitive": True})
    assert r.json()["version"] == 4
    r = await client.patch(f"/api/legacy-usage-rules/{rule['id']}",
                           json={"include_historical_locations": False})
    assert r.json()["version"] == 5

    # 语义改回等价 → 版本继续 +1，但 hash 复原（幂等锚回到原证据）
    r = await client.patch(
        f"/api/legacy-usage-rules/{rule['id']}",
        json={"pattern": "historical-marker", "match_operator": "equals",
              "case_sensitive": False, "include_historical_locations": True},
    )
    body = r.json()
    assert body["version"] == 6
    assert body["snapshot_hash"] == h1


async def test_rule_display_only_update_version_policy(client):
    """展示字段（name/description/priority）与启停/归档/恢复不增加版本。"""
    rule = await _create_rule(client)
    rid, h1 = rule["id"], rule["snapshot_hash"]
    r = await client.patch(f"/api/legacy-usage-rules/{rid}",
                           json={"name": "新名字", "description": "新描述", "priority": 5})
    assert r.json()["version"] == 1 and r.json()["snapshot_hash"] == h1
    await client.post(f"/api/legacy-usage-rules/{rid}/disable")
    await client.post(f"/api/legacy-usage-rules/{rid}/enable")
    await client.post(f"/api/legacy-usage-rules/{rid}/archive")
    r = await client.post(f"/api/legacy-usage-rules/{rid}/restore")
    assert r.json()["version"] == 1 and r.json()["snapshot_hash"] == h1


# ============================ 取消（§六 API 侧） ============================


async def test_cancel_pending_import(client, session):
    sd = await _seed_root(session)
    asset = await _seed_asset(session, sd, "historical-marker/cp.mp4")
    await _seed_location(session, sd, asset, "historical-marker/cp.mp4")
    await _create_rule(client)
    run = (await client.post("/api/legacy-usage-imports", json={})).json()
    assert run["status"] == "pending"
    r = await client.post(f"/api/legacy-usage-imports/{run['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert r.json()["completed_at"] is not None
    # 重复取消 → 明确 409（幂等拒绝）
    r = await client.post(f"/api/legacy-usage-imports/{run['id']}/cancel")
    assert r.status_code == 409


async def test_cancel_completed_run_rejected(client, session):
    sd = await _seed_root(session)
    asset = await _seed_asset(session, sd, "historical-marker/cc.mp4")
    await _seed_location(session, sd, asset, "historical-marker/cc.mp4")
    await _create_rule(client)
    run = (await client.post("/api/legacy-usage-imports", json={})).json()
    from clipmind_shared.models import LegacyUsageImportRun as _Run
    db_run = await session.get(_Run, run["id"])
    db_run.status = "completed"
    db_run.completed_at = utcnow()
    await session.commit()
    r = await client.post(f"/api/legacy-usage-imports/{run['id']}/cancel")
    assert r.status_code == 409
    # failed 同样拒绝
    db_run.status = "failed"
    await session.commit()
    r = await client.post(f"/api/legacy-usage-imports/{run['id']}/cancel")
    assert r.status_code == 409


# ============================ 统计口径 distinct（§七） ============================


async def test_matched_location_count_is_distinct(client, session):
    """同一路径中出现两次相同目录段：1 个位置只计 1 次（证据也只 1 条）。"""
    sd = await _seed_root(session)
    a = await _seed_asset(session, sd, "historical-marker/sub/historical-marker/f.mp4")
    await _seed_location(session, sd, a, "historical-marker/sub/historical-marker/f.mp4")
    await _create_rule(client, pattern="historical-marker")
    body = (await client.post("/api/legacy-usage-imports/preview", json={})).json()
    assert body["matched_location_count"] == 1
    assert body["matched_asset_count"] == 1
    assert body["would_create_count"] == 1


async def test_multiple_rules_same_location_count_once(client, session):
    """一个位置被两条规则命中：位置计 1 次；证据按规则语义各 1 条。"""
    sd = await _seed_root(session)
    a = await _seed_asset(session, sd, "historical-marker/f.used-tag.mp4")
    await _seed_location(session, sd, a, "historical-marker/f.used-tag.mp4")
    r1 = await _create_rule(client, pattern="historical-marker")
    r2 = await _create_rule(client, target="filename", operator="contains",
                            pattern=".used-tag")
    body = (await client.post(
        "/api/legacy-usage-imports/preview",
        json={"rule_ids": [r1["id"], r2["id"]]},
    )).json()
    assert body["matched_location_count"] == 1  # distinct 位置
    assert body["matched_asset_count"] == 1
    assert body["would_create_count"] == 2      # 两条规则各自的匹配事实
    assert body["by_rule"] == {str(r1["id"]): 1, str(r2["id"]): 1}


async def test_multiple_hits_same_location_count_once(client, session):
    """一条规则在同一位置产生多个 hit（不同片段）：位置仍只计 1 次。"""
    sd = await _seed_root(session)
    a = await _seed_asset(session, sd, "marker-a/marker-b/f.mp4")
    await _seed_location(session, sd, a, "marker-a/marker-b/f.mp4")
    rule = await _create_rule(client, operator="starts_with", pattern="marker-")
    body = (await client.post(
        "/api/legacy-usage-imports/preview", json={"rule_ids": [rule["id"]]}
    )).json()
    assert body["matched_location_count"] == 1
    assert body["would_create_count"] == 2  # marker-a / marker-b 两个匹配事实
    assert body["by_rule"] == {str(rule["id"]): 1}


async def test_existing_evidence_count_is_distinct(client, session):
    """existing_evidence_count = 本次命中的不同既有 Evidence 数（非观察次数）。"""
    sd = await _seed_root(session)
    a = await _seed_asset(session, sd, "historical-marker/f1.mp4")
    await _seed_location(session, sd, a, "historical-marker/f1.mp4")
    # 同一 Asset 第二个位置命中同一目录段 → 同一匹配事实（同 key）
    await _seed_location(session, sd, a, "sub/historical-marker/f2.mp4", primary=False)
    rule = await _create_rule(client, pattern="historical-marker")
    await _seed_evidence(session, a, rule)  # 既有证据（同 key）
    body = (await client.post(
        "/api/legacy-usage-imports/preview", json={"rule_ids": [rule["id"]]}
    )).json()
    assert body["matched_location_count"] == 2  # 两个不同位置
    assert body["existing_evidence_count"] == 1  # 但只命中 1 条既有证据
    assert body["would_create_count"] == 0
