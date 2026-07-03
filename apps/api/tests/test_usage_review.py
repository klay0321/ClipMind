"""PR-D 统一使用记录中心 API 测试（需要 TEST_DATABASE_URL）。

锁定 docs/USAGE_REVIEW_CENTER.md：
- 展示统一、事实分离：summary/list 只读投影，无混合"总使用次数"；
- typed bulk：混合类型 422、非法动作 422、逐条走原状态机 + 原事件审计、
  409→skipped / 404→failed 明细准确；
- 隔离：legacy 动作绝不改变 confirmed count 与 Shot summary；
- clue 补录：manual proposed 创建、绝不自动 confirmed、重复关系 409。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.legacy_rules import compute_evidence_key
from clipmind_shared.models import (
    Asset,
    FinalVideoUsage,
    FinalVideoUsageEvent,
    LegacyUsageEvidence,
    LegacyUsageEvidenceEvent,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import AssetStatus, ShotStatus
from sqlalchemy import func, select

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


# ============================ 工厂 ============================


async def _seed_root(session) -> SourceDirectory:
    sd = SourceDirectory(
        name=f"ur-{uuid.uuid4().hex[:8]}",
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
    a = Asset(
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
    session.add(a)
    await session.commit()
    await session.refresh(a)
    return a


async def _seed_shot(session, asset, seq=1) -> Shot:
    s = Shot(
        asset_id=asset.id,
        generation=1,
        sequence_no=seq,
        start_time=float(seq - 1),
        end_time=float(seq),
        duration=1.0,
        detector_type="fixed",
        status=ShotStatus.READY,
        keyframe_path=f"k/{asset.id}-{seq}.jpg",
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


async def _seed_fv(client, asset_id, title="成片") -> dict:
    r = await client.post("/api/final-videos", json={"asset_id": asset_id, "title": title})
    assert r.status_code == 201, r.text
    return r.json()


async def _seed_usage(client, fv_id, shot_id) -> dict:
    r = await client.post(
        f"/api/final-videos/{fv_id}/usages", json={"source_shot_id": shot_id}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _seed_rule(client, pattern="review-marker") -> dict:
    r = await client.post("/api/legacy-usage-rules", json={
        "name": f"规则-{uuid.uuid4().hex[:6]}",
        "match_target": "directory_segment",
        "match_operator": "equals",
        "pattern": pattern,
    })
    assert r.status_code == 201, r.text
    return r.json()


async def _seed_evidence(session, asset, rule, component="review-marker",
                         status="pending") -> LegacyUsageEvidence:
    ev = LegacyUsageEvidence(
        asset_id=asset.id,
        rule_id=rule["id"],
        evidence_key=compute_evidence_key(
            rule["snapshot_hash"], asset.id, "directory_segment", component
        ),
        rule_version=rule.get("version", 1),
        evidence_type="directory_marker",
        matched_target="directory_segment",
        matched_component=component,
        rule_snapshot={"rule_id": rule["id"], "name": "规则快照",
                       "snapshot_hash": rule["snapshot_hash"]},
        review_status=status,
    )
    session.add(ev)
    await session.commit()
    await session.refresh(ev)
    return ev


async def _stage(client, session, *, shots=2):
    """标准舞台：源素材(+shots) + 成片 + 2 proposed usage + 2 pending evidence。"""
    sd = await _seed_root(session)
    src = await _seed_asset(session, sd, "review-marker/src.mp4")
    fv_asset = await _seed_asset(session, sd, "finals/out.mp4")
    shot_rows = [await _seed_shot(session, src, seq=i + 1) for i in range(shots)]
    fv = await _seed_fv(client, fv_asset.id)
    # 只给前两个镜头建 usage（其余留给补录场景）
    usages = [await _seed_usage(client, fv["id"], s.id) for s in shot_rows[:2]]
    rule = await _seed_rule(client)
    evs = [
        await _seed_evidence(session, src, rule, component=f"review-marker-{i}")
        for i in range(2)
    ]
    return sd, src, fv, shot_rows, usages, rule, evs


async def _bulk(client, items, action, expect=200):
    r = await client.post("/api/usage-review/bulk", json={"items": items, "action": action})
    assert r.status_code == expect, r.text
    return r.json()


def _fref(u):
    return {"item_type": "final_video_usage", "item_id": u["id"]}


def _lref(e):
    return {"item_type": "legacy_usage_evidence", "item_id": e.id}


# ============================ Summary ============================


async def test_summary_separates_and_never_sums(client, session):
    _, _, _, _, usages, _, evs = await _stage(client, session)
    await client.post(f"/api/final-video-usages/{usages[0]['id']}/confirm")
    r = await client.get("/api/usage-review/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["formal"]["confirmed"] == 1
    assert body["formal"]["proposed"] == 1
    assert body["legacy"]["pending"] == 2
    assert body["needs_review_total"] == 1 + 2  # proposed + pending（工作量口径）
    assert "total_used_count" not in body  # 绝无混合总数


# ============================ 列表 / 筛选 ============================


async def test_list_defaults_and_item_shapes(client, session):
    _, src, fv, shot_rows, usages, rule, evs = await _stage(client, session)
    r = await client.get("/api/usage-review/items?review_group=needs_review&page=1&page_size=20")
    body = r.json()
    assert body["total"] == 4  # 2 proposed + 2 pending
    types = {(i["item_type"], i["item_id"]) for i in body["items"]}
    assert ("final_video_usage", usages[0]["id"]) in types
    assert ("legacy_usage_evidence", evs[0].id) in types
    formal = next(i for i in body["items"] if i["item_type"] == "final_video_usage")
    legacy = next(i for i in body["items"] if i["item_type"] == "legacy_usage_evidence")
    # formal 有 shot/fv；legacy 恒 null（不造占位对象）
    assert formal["shot_id"] is not None and formal["final_video_id"] == fv["id"]
    assert formal["source_strength"] == "manual_proposed_lineage"
    assert legacy["shot_id"] is None and legacy["final_video_id"] is None
    assert legacy["source_strength"] == "pending_legacy_evidence"
    assert "v1" in (legacy["source_label"] or "")
    assert set(formal["available_actions"]) == {"confirm", "reject"}
    assert set(legacy["available_actions"]) == {"accept", "reject", "mark_conflict"}


async def test_list_pagination_and_deterministic_sort(client, session):
    await _stage(client, session)
    r1 = await client.get("/api/usage-review/items?page=1&page_size=3")
    r2 = await client.get("/api/usage-review/items?page=2&page_size=3")
    b1, b2 = r1.json(), r2.json()
    assert b1["total"] == 4 and len(b1["items"]) == 3 and len(b2["items"]) == 1
    keys1 = [(i["item_type"], i["item_id"]) for i in b1["items"]]
    # 再次请求顺序完全一致（确定性）
    r1b = await client.get("/api/usage-review/items?page=1&page_size=3")
    assert [(i["item_type"], i["item_id"]) for i in r1b.json()["items"]] == keys1
    # 升序排序也可用
    r_asc = await client.get("/api/usage-review/items?page=1&page_size=10&sort=created_at")
    asc = [i["created_at"] for i in r_asc.json()["items"]]
    assert asc == sorted(asc)
    # 非法 sort 拒绝
    r_bad = await client.get("/api/usage-review/items?sort=random")
    assert r_bad.status_code == 422


async def test_list_type_group_strength_filters(client, session):
    _, _, _, _, usages, _, evs = await _stage(client, session)
    await client.post(f"/api/final-video-usages/{usages[0]['id']}/confirm")
    r = await client.get("/api/usage-review/items?item_type=final_video_usage")
    assert {i["item_type"] for i in r.json()["items"]} == {"final_video_usage"}
    r = await client.get("/api/usage-review/items?item_type=legacy_usage_evidence")
    assert {i["item_type"] for i in r.json()["items"]} == {"legacy_usage_evidence"}
    r = await client.get("/api/usage-review/items?source_strength=confirmed_lineage")
    body = r.json()
    assert body["total"] == 1 and body["items"][0]["review_status"] == "confirmed"
    r = await client.get("/api/usage-review/items?source_strength=manual_proposed_lineage")
    assert r.json()["total"] == 1
    r = await client.get("/api/usage-review/items?review_group=accepted_or_confirmed")
    assert r.json()["total"] == 1  # confirmed（无 accepted evidence）
    # 非法枚举 422
    assert (await client.get("/api/usage-review/items?item_type=bogus")).status_code == 422
    assert (await client.get("/api/usage-review/items?review_group=bogus")).status_code == 422
    assert (
        await client.get("/api/usage-review/items?source_strength=bogus")
    ).status_code == 422


async def test_list_asset_fv_source_dir_and_q_filters(client, session):
    sd, src, fv, _, usages, rule, evs = await _stage(client, session)
    r = await client.get(f"/api/usage-review/items?asset_id={src.id}")
    assert r.json()["total"] == 4  # 2 usage + 2 evidence 均绑该 asset
    # final_video_id 筛选天然排除 legacy（证据没有成片）
    r = await client.get(f"/api/usage-review/items?final_video_id={fv['id']}")
    body = r.json()
    assert body["total"] == 2
    assert {i["item_type"] for i in body["items"]} == {"final_video_usage"}
    r = await client.get(f"/api/usage-review/items?source_directory_id={sd.id}")
    assert r.json()["total"] == 4
    r = await client.get("/api/usage-review/items?q=src.mp4")
    assert r.json()["total"] == 4  # 按素材文件名两边都命中
    r = await client.get("/api/usage-review/items?q=不存在zzz")
    assert r.json()["total"] == 0


async def test_list_product_family_bridge_filter(client, session):
    """product_family_id 经兼容桥 legacy_product_id → asset.primary_product_id。"""
    from clipmind_shared.models import Product, ProductFamily

    sd, src, fv, shot_rows, usages, rule, evs = await _stage(client, session)
    pname = f"P-{uuid.uuid4().hex[:6]}"
    product = Product(name=pname, normalized_name=pname.lower())
    session.add(product)
    await session.commit()
    src.primary_product_id = product.id
    fcode = f"f-{uuid.uuid4().hex[:6]}"
    family = ProductFamily(
        code=fcode, normalized_code=fcode, name_zh=f"族-{fcode}",
        legacy_product_id=product.id,
    )
    session.add(family)
    await session.commit()
    await session.refresh(family)

    r = await client.get(f"/api/usage-review/items?product_family_id={family.id}")
    assert r.json()["total"] == 4
    # 不存在的 family → 空
    r = await client.get("/api/usage-review/items?product_family_id=999999")
    assert r.json()["total"] == 0


# ============================ 详情 ============================


async def test_item_detail_both_types(client, session):
    _, _, _, _, usages, _, evs = await _stage(client, session)
    r = await client.get(f"/api/usage-review/items/final_video_usage/{usages[0]['id']}")
    body = r.json()
    assert body["item"]["item_type"] == "final_video_usage"
    assert body["formal_usage"] is not None and body["legacy_evidence"] is None
    assert body["formal_usage"]["evidence_method"] == "manual"
    assert [e["action"] for e in body["events"]] == ["manual_add"]

    r = await client.get(f"/api/usage-review/items/legacy_usage_evidence/{evs[0].id}")
    body = r.json()
    assert body["legacy_evidence"] is not None and body["formal_usage"] is None
    assert body["item"]["shot_id"] is None
    assert (await client.get("/api/usage-review/items/final_video_usage/999999")).status_code == 404
    assert (await client.get("/api/usage-review/items/bogus/1")).status_code == 422


# ============================ typed bulk ============================


async def test_bulk_formal_confirm_reject_revoke_restore(client, session):
    _, src, _, shot_rows, usages, _, _ = await _stage(client, session)
    out = await _bulk(client, [_fref(u) for u in usages], "confirm")
    assert out["succeeded"] == 2 and out["skipped"] == 0
    ss = (await client.get(f"/api/shots/{shot_rows[0].id}/usage-summary")).json()
    assert ss["confirmed_usage_count"] == 1  # formal confirm 影响 Shot summary
    asum = (await client.get(f"/api/assets/{src.id}/usage-summary")).json()
    assert asum["confirmed_usage_count"] == 2

    out = await _bulk(client, [_fref(usages[0])], "revoke")
    assert out["succeeded"] == 1
    asum = (await client.get(f"/api/assets/{src.id}/usage-summary")).json()
    assert asum["confirmed_usage_count"] == 1  # revoke 立即重算

    out = await _bulk(client, [_fref(usages[0])], "restore_proposal")
    assert out["succeeded"] == 1
    out = await _bulk(client, [_fref(usages[0])], "reject")
    assert out["succeeded"] == 1


async def test_bulk_legacy_accept_reject_conflict_reset(client, session):
    _, src, _, _, _, rule, evs = await _stage(client, session)
    out = await _bulk(client, [_lref(e) for e in evs], "accept")
    assert out["succeeded"] == 2
    out = await _bulk(client, [_lref(evs[0])], "mark_conflict")
    assert out["succeeded"] == 1
    out = await _bulk(client, [_lref(evs[0])], "reset")
    assert out["succeeded"] == 1
    out = await _bulk(client, [_lref(evs[0])], "reject")
    assert out["succeeded"] == 1


async def test_bulk_mixed_type_and_invalid_action_rejected(client, session):
    _, _, _, _, usages, _, evs = await _stage(client, session)
    # 混合类型 422
    r = await client.post("/api/usage-review/bulk", json={
        "items": [_fref(usages[0]), _lref(evs[0])], "action": "confirm",
    })
    assert r.status_code == 422
    assert "混合" in r.json()["detail"]
    # action 与类型不匹配 422
    r = await client.post("/api/usage-review/bulk", json={
        "items": [_fref(usages[0])], "action": "accept",
    })
    assert r.status_code == 422
    r = await client.post("/api/usage-review/bulk", json={
        "items": [_lref(evs[0])], "action": "confirm",
    })
    assert r.status_code == 422
    # 超过 500 条 422（pydantic）
    r = await client.post("/api/usage-review/bulk", json={
        "items": [{"item_type": "final_video_usage", "item_id": i} for i in range(501)],
        "action": "confirm",
    })
    assert r.status_code == 422
    # 空列表 422
    r = await client.post("/api/usage-review/bulk", json={"items": [], "action": "confirm"})
    assert r.status_code == 422


async def test_bulk_partial_failure_and_idempotent_skip(client, session):
    _, _, _, _, usages, _, evs = await _stage(client, session)
    await _bulk(client, [_fref(usages[0])], "confirm")
    # 已 confirmed 再 confirm → skipped；不存在 → failed；正常 → succeeded
    out = await _bulk(
        client,
        [_fref(usages[0]), _fref(usages[1]), {"item_type": "final_video_usage", "item_id": 999999}],
        "confirm",
    )
    assert out["succeeded"] == 1 and out["skipped"] == 1 and out["failed"] == 1
    detail = {(r["item_id"]): r["outcome"] for r in out["results"]}
    assert detail[usages[0]["id"]] == "skipped"
    assert detail[usages[1]["id"]] == "succeeded"
    assert detail[999999] == "failed"
    # 已 accepted 再 accept → skipped（幂等策略统一）
    await _bulk(client, [_lref(evs[0])], "accept")
    out = await _bulk(client, [_lref(evs[0])], "accept")
    assert out["skipped"] == 1 and out["succeeded"] == 0


async def test_bulk_writes_original_domain_events(client, session):
    _, _, _, _, usages, _, evs = await _stage(client, session)
    fe_before = int(await session.scalar(select(func.count(FinalVideoUsageEvent.id))) or 0)
    le_before = int(
        await session.scalar(select(func.count(LegacyUsageEvidenceEvent.id))) or 0
    )
    await _bulk(client, [_fref(u) for u in usages], "confirm")
    await _bulk(client, [_lref(e) for e in evs], "accept")
    fe_after = int(await session.scalar(select(func.count(FinalVideoUsageEvent.id))) or 0)
    le_after = int(
        await session.scalar(select(func.count(LegacyUsageEvidenceEvent.id))) or 0
    )
    assert fe_after - fe_before == 2  # 每条 confirm 一个原领域事件
    assert le_after - le_before == 2


async def test_legacy_bulk_never_changes_confirmed_or_shot_summary(client, session):
    _, src, _, shot_rows, usages, _, evs = await _stage(client, session)
    await _bulk(client, [_fref(usages[0])], "confirm")
    usage_rows_before = int(await session.scalar(select(func.count(FinalVideoUsage.id))) or 0)
    shot_before = (await client.get(f"/api/shots/{shot_rows[0].id}/usage-summary")).json()
    asset_before = (await client.get(f"/api/assets/{src.id}/usage-summary")).json()

    await _bulk(client, [_lref(e) for e in evs], "accept")

    usage_rows_after = int(await session.scalar(select(func.count(FinalVideoUsage.id))) or 0)
    shot_after = (await client.get(f"/api/shots/{shot_rows[0].id}/usage-summary")).json()
    asset_after = (await client.get(f"/api/assets/{src.id}/usage-summary")).json()
    assert usage_rows_before == usage_rows_after
    assert shot_before == shot_after  # Shot 不继承 legacy
    for key in ("confirmed_usage_count", "used_shot_count", "distinct_final_video_count"):
        assert asset_before[key] == asset_after[key]
    assert asset_after["legacy_usage_state"] == "legacy_used_unknown"


# ============================ clue 补录 ============================


async def test_clue_creates_manual_proposed_not_confirmed(client, session):
    """从历史线索补录：manual proposed（绝不自动 confirmed）；重复关系 409。"""
    sd, src, fv, shot_rows, usages, rule, evs = await _stage(client, session, shots=3)
    free_shot = shot_rows[2]  # usages 只占了前两个
    r = await client.post(
        f"/api/final-videos/{fv['id']}/usages",
        json={"source_shot_id": free_shot.id,
              "evidence_summary": f"根据历史线索补录（证据 #{evs[0].id}）"},
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["status"] == "proposed"
    assert created["evidence_method"] == "manual"
    # confirmed count 不变
    ss = (await client.get(f"/api/shots/{free_shot.id}/usage-summary")).json()
    assert ss["confirmed_usage_count"] == 0
    # 证据保留且状态不变
    await session.refresh(evs[0])
    assert evs[0].review_status == "pending"
    # 明确 confirm 后 +1
    out = await _bulk(client, [_fref(created)], "confirm")
    assert out["succeeded"] == 1
    ss = (await client.get(f"/api/shots/{free_shot.id}/usage-summary")).json()
    assert ss["confirmed_usage_count"] == 1
    # 同一 FinalVideo+Shot 已有 Usage → 409（显示已有关系）
    r = await client.post(
        f"/api/final-videos/{fv['id']}/usages", json={"source_shot_id": free_shot.id}
    )
    assert r.status_code == 409


# ============================ 兼容 ============================


async def test_backward_compat_endpoints_intact(client, session):
    _, src, fv, _, _, rule, evs = await _stage(client, session)
    for path in (
        f"/api/final-videos/{fv['id']}/lineage",
        "/api/legacy-usage-evidence?page=1&page_size=5",
        "/api/legacy-usage-rules",
        f"/api/assets/{src.id}/usage-summary",
        f"/api/assets/{src.id}/legacy-usage-summary",
    ):
        r = await client.get(path)
        assert r.status_code == 200, path
