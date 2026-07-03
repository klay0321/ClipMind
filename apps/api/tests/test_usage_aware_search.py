"""PR-E 使用感知检索测试（需要 TEST_DATABASE_URL；docs/USAGE_AWARE_SEARCH.md）。

锁定：
- 特征批量投影（去重成片=正式次数、occurrence 不重复、Shot/Asset 区分、
  legacy accepted only、proposed 只展示、历史 Shot 统计自身血缘、无 N+1）；
- 排序纯函数（default=0、cap、relevance guard、NaN/越权 422、确定 tie-break、
  legacy 显著弱于 confirmed、count=0 无惩罚、时间缺失无 recent 惩罚）；
- API：default 逐位 parity、prefer_unused 同 base 重排、hard filters、
  候选扩张与统计、Saved Search 兼容、旧请求兼容。
"""

from __future__ import annotations

import math
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    LegacyUsageEvidence,
    Shot,
    ShotSearchDocument,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AssetStatus,
    SearchDocumentStatus,
    SearchEmbeddingStatus,
    ShotStatus,
)
from fastapi import HTTPException
from sqlalchemy import text

from app.services.usage_feature_service import UsageFeatures, batch_features
from app.services.usage_ranking import (
    ADJUSTMENT_CAP,
    compute_adjustment,
    hard_filter_predicate,
    resolve_weights,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)

NOW = datetime(2026, 7, 3, tzinfo=UTC)


# ============================ 纯函数：权重 ============================


async def test_resolve_weights_presets_and_override():
    b = resolve_weights("balanced", None)
    s = resolve_weights("strong_unused", None)
    r = resolve_weights("relevance_first", None)
    assert s.weight_unused > b.weight_unused > r.weight_unused
    assert r.weight_legacy == 0.0
    w = resolve_weights("balanced", {"weight_unused": 0.15, "decay_days": 60})
    assert w.weight_unused == 0.15 and w.decay_days == 60
    # 越界 / NaN / Infinity / 未知字段 / legacy 上限 → 422
    for bad in (
        {"weight_unused": 0.5},
        {"weight_unused": float("nan")},
        {"weight_count": float("inf")},
        {"bogus": 0.1},
        {"weight_legacy": 0.1},   # legacy 权重上限 0.05（显著弱于正式）
        {"decay_days": 0},
    ):
        with pytest.raises(HTTPException) as exc:
            resolve_weights("balanced", bad)
        assert exc.value.status_code == 422
    with pytest.raises(HTTPException):
        resolve_weights("bogus_preset", None)


# ============================ 纯函数：调整 ============================


def _feat(**kw) -> UsageFeatures:
    f = UsageFeatures(shot_id=1, asset_id=1)
    for k, v in kw.items():
        setattr(f, k, v)
    return f


async def test_adjustment_default_mode_is_zero():
    f = _feat(shot_confirmed_usage_count=5, accepted_legacy_evidence_count=3)
    adj, reasons = compute_adjustment(
        f, weights=resolve_weights("strong_unused", None), mode="default",
        scope="combined", include_legacy_unknown=True, now=NOW,
    )
    assert adj == 0.0 and reasons == []


async def test_adjustment_signals_and_caps():
    w = resolve_weights("balanced", None)
    # 未使用 → 正奖励；无 count/recent 惩罚
    adj, reasons = compute_adjustment(
        _feat(), weights=w, mode="prefer_unused", scope="combined",
        include_legacy_unknown=True, now=NOW,
    )
    assert adj > 0
    assert [r.code for r in reasons] == ["shot_never_used"]
    # 高频 + 近期 → 负；count=0 无 count 惩罚已由上例证明
    used = _feat(
        shot_confirmed_usage_count=3,
        shot_last_confirmed_used_at=NOW - timedelta(days=2),
        asset_distinct_final_video_count=3,
    )
    adj2, reasons2 = compute_adjustment(
        used, weights=w, mode="prefer_unused", scope="combined",
        include_legacy_unknown=True, now=NOW,
    )
    assert adj2 < 0
    codes = {r.code for r in reasons2}
    assert {"shot_used_multiple_times", "shot_recently_used",
            "asset_reused_across_videos"} <= codes
    # 时间缺失 → 无 recent 惩罚
    no_time = _feat(shot_confirmed_usage_count=1)
    _, reasons3 = compute_adjustment(
        no_time, weights=w, mode="prefer_unused", scope="combined",
        include_legacy_unknown=True, now=NOW,
    )
    assert "shot_recently_used" not in {r.code for r in reasons3}
    # cap：极端权重 + 多信号也不超过 ±ADJUSTMENT_CAP
    wmax = resolve_weights("balanced", {
        "weight_count": 0.2, "weight_recent": 0.2, "weight_asset": 0.2,
    })
    heavy = _feat(
        shot_confirmed_usage_count=100,
        shot_last_confirmed_used_at=NOW,
        asset_distinct_final_video_count=100,
        accepted_legacy_evidence_count=1,
    )
    adj4, _ = compute_adjustment(
        heavy, weights=wmax, mode="prefer_unused", scope="combined",
        include_legacy_unknown=True, now=NOW,
    )
    assert adj4 == -ADJUSTMENT_CAP
    assert not math.isnan(adj4)


async def test_adjustment_scope_and_legacy_isolation():
    w = resolve_weights("balanced", None)
    f = _feat(
        shot_confirmed_usage_count=2,
        asset_distinct_final_video_count=4,
        accepted_legacy_evidence_count=1,
    )
    # scope=shot：无 asset 惩罚；scope=asset：无 shot count/recent 惩罚
    _, rs_shot = compute_adjustment(
        f, weights=w, mode="prefer_unused", scope="shot",
        include_legacy_unknown=True, now=NOW,
    )
    assert "asset_reused_across_videos" not in {r.code for r in rs_shot}
    _, rs_asset = compute_adjustment(
        f, weights=w, mode="prefer_unused", scope="asset",
        include_legacy_unknown=True, now=NOW,
    )
    codes_asset = {r.code for r in rs_asset}
    assert "asset_reused_across_videos" in codes_asset
    assert "shot_used_multiple_times" not in codes_asset
    # legacy：惩罚存在但显著弱于 count 惩罚；include_legacy_unknown=False → 无
    _, rs = compute_adjustment(
        f, weights=w, mode="prefer_unused", scope="combined",
        include_legacy_unknown=True, now=NOW,
    )
    legacy = next(r for r in rs if r.code == "legacy_used_unknown_hint")
    count = next(r for r in rs if r.code == "shot_used_multiple_times")
    assert abs(legacy.adjustment) < abs(count.adjustment)
    assert abs(legacy.adjustment) <= 0.05
    _, rs_no = compute_adjustment(
        f, weights=w, mode="prefer_unused", scope="combined",
        include_legacy_unknown=False, now=NOW,
    )
    assert "legacy_used_unknown_hint" not in {r.code for r in rs_no}


async def test_hard_filter_predicate_semantics():
    keep_never = hard_filter_predicate(
        mode="only_never_confirmed", max_confirmed_usage_count=None,
        min_days_since_last_use=None, exclude_recently_used_days=None, now=NOW,
    )
    assert keep_never(_feat()) is True
    assert keep_never(_feat(shot_confirmed_usage_count=1)) is False
    # accepted legacy ≠ confirmed → 不被 only_never_confirmed 排除
    assert keep_never(_feat(accepted_legacy_evidence_count=3)) is True

    keep_max = hard_filter_predicate(
        mode="exclude_high_frequency", max_confirmed_usage_count=2,
        min_days_since_last_use=None, exclude_recently_used_days=None, now=NOW,
    )
    assert keep_max(_feat(shot_confirmed_usage_count=2)) is True
    assert keep_max(_feat(shot_confirmed_usage_count=3)) is False

    keep_recent = hard_filter_predicate(
        mode="prefer_unused", max_confirmed_usage_count=None,
        min_days_since_last_use=30, exclude_recently_used_days=60, now=NOW,
    )
    # 双阈值取更严格（60 天）；从未使用视为满足
    assert keep_recent(_feat()) is True
    assert keep_recent(
        _feat(shot_last_confirmed_used_at=NOW - timedelta(days=45),
              shot_confirmed_usage_count=1)
    ) is False
    assert keep_recent(
        _feat(shot_last_confirmed_used_at=NOW - timedelta(days=90),
              shot_confirmed_usage_count=1)
    ) is True


# ============================ 特征投影（DB） ============================


async def _seed_root(session) -> SourceDirectory:
    sd = SourceDirectory(
        name=f"ue-{uuid.uuid4().hex[:8]}", mount_path="/app/source",
        include_extensions=["mp4"], exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    return sd


async def _seed_asset(session, sd, rel="a.mp4") -> Asset:
    a = Asset(
        source_directory_id=sd.id, relative_path=rel,
        normalized_relative_path=rel.lower(), filename=rel.rsplit("/", 1)[-1],
        extension="mp4", file_size=1, duration=10.0, status=AssetStatus.INDEXED,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(a)
    await session.commit()
    await session.refresh(a)
    return a


async def _seed_shot(session, asset, seq=1, retired=False) -> Shot:
    s = Shot(
        asset_id=asset.id, generation=1, sequence_no=seq,
        start_time=float(seq - 1), end_time=float(seq), duration=1.0,
        detector_type="fixed", status=ShotStatus.READY,
        keyframe_path=f"k/{asset.id}-{seq}.jpg",
        retired_at=utcnow() if retired else None,
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


async def _seed_fv(client, asset_id, title) -> dict:
    r = await client.post("/api/final-videos", json={"asset_id": asset_id, "title": title})
    assert r.status_code == 201, r.text
    return r.json()


async def _confirm_usage(client, fv_id, shot_id) -> dict:
    r = await client.post(f"/api/final-videos/{fv_id}/usages", json={"source_shot_id": shot_id})
    assert r.status_code == 201, r.text
    u = r.json()
    r = await client.post(f"/api/final-video-usages/{u['id']}/confirm")
    assert r.status_code == 200, r.text
    return r.json()


async def test_batch_projection_semantics(client, session):
    sd = await _seed_root(session)
    src = await _seed_asset(session, sd, "u-src.mp4")
    other = await _seed_asset(session, sd, "u-fv1.mp4")
    other2 = await _seed_asset(session, sd, "u-fv2.mp4")
    s1 = await _seed_shot(session, src, 1)   # 2 个成片使用
    s2 = await _seed_shot(session, src, 2)   # 未使用（但同 asset 有使用）
    s3 = await _seed_shot(session, src, 3)   # 先建血缘再 retire（历史 Shot 保留血缘）
    fv1 = await _seed_fv(client, other.id, "成片1")
    fv2 = await _seed_fv(client, other2.id, "成片2")
    u1 = await _confirm_usage(client, fv1["id"], s1.id)
    await _confirm_usage(client, fv2["id"], s1.id)
    await _confirm_usage(client, fv2["id"], s3.id)
    # 建完血缘后 retire s3（代次保留语义：历史 Shot 血缘仍统计自身）
    await session.execute(
        text("UPDATE shot SET retired_at = now() WHERE id = :sid"), {"sid": s3.id}
    )
    await session.commit()
    # 多 occurrence 不增加次数
    r = await client.post(
        f"/api/final-video-usages/{u1['id']}/occurrences",
        json={"source_start_ms": 0, "source_end_ms": 500,
              "final_start_ms": 0, "final_end_ms": 500},
    )
    assert r.status_code == 201, r.text
    # proposed（仅展示）
    s4 = await _seed_shot(session, src, 4)
    r = await client.post(f"/api/final-videos/{fv1['id']}/usages", json={"source_shot_id": s4.id})
    assert r.status_code == 201
    # legacy：accepted 1 条 + pending 1 条（pending 不参与）
    from clipmind_shared.legacy_rules import compute_evidence_key
    rule = await client.post("/api/legacy-usage-rules", json={
        "name": f"r-{uuid.uuid4().hex[:6]}", "match_target": "directory_segment",
        "match_operator": "equals", "pattern": "ue-marker",
    })
    rj = rule.json()
    for comp, status in (("m1", "accepted"), ("m2", "pending")):
        session.add(LegacyUsageEvidence(
            asset_id=src.id, rule_id=rj["id"],
            evidence_key=compute_evidence_key(
                rj["snapshot_hash"], src.id, "directory_segment", comp
            ),
            rule_version=1, evidence_type="directory_marker",
            matched_target="directory_segment", matched_component=comp,
            rule_snapshot={}, review_status=status,
        ))
    await session.commit()

    feats = await batch_features(session, [s1.id, s2.id, s3.id, s4.id, 999999])
    f1, f2, f3, f4 = feats[s1.id], feats[s2.id], feats[s3.id], feats[s4.id]
    # s1：2 个去重成片；occurrence 不重复计数
    assert f1.shot_confirmed_usage_count == 2
    assert f1.shot_distinct_final_video_count == 2
    assert f1.shot_last_confirmed_used_at is not None
    assert f1.usage_state == "confirmed_used"
    # s2：Shot 未使用但 Asset 有使用（区分！）+ accepted legacy → legacy_used_unknown
    assert f2.shot_confirmed_usage_count == 0
    assert f2.asset_distinct_final_video_count == 2
    assert f2.asset_used_shot_count == 2  # s1 + s3
    assert f2.accepted_legacy_evidence_count == 1  # pending 不计
    assert f2.usage_state == "legacy_used_unknown"
    # s3：历史 Shot 的血缘仍统计自身
    assert f3.shot_confirmed_usage_count == 1
    # s4：proposed 只进 pending_formal_count
    assert f4.shot_confirmed_usage_count == 0
    assert f4.pending_formal_count == 1
    # s4 与 src 同 asset（asset 带 accepted legacy）→ 状态为 legacy_used_unknown
    assert f4.usage_state in ("usage_needs_review", "legacy_used_unknown")
    # asset 当前代次镜头数不含 retired
    assert f1.asset_total_current_shot_count == 3  # s1/s2/s4（s3 retired）
    # 未知 shot → 零值
    assert feats[999999].shot_confirmed_usage_count == 0
    assert feats[999999].usage_state == "never_confirmed_used"


# ============================ API：parity 与模式 ============================


async def _seed_search_docs(session, shots, token: str):
    """让镜头进入词法召回：写 search document（相同文本 → 相同 base 分）。"""
    for s in shots:
        session.add(ShotSearchDocument(
            shot_id=s.id,
            shot_generation=s.generation,
            asset_id=s.asset_id,
            document_status=SearchDocumentStatus.INDEXED,
            embedding_status=SearchEmbeddingStatus.DEGRADED,
            is_searchable=True,
            search_document=f"{token} 演示镜头 场景",
            normalized_document=f"{token} 演示镜头 场景",
            embedding=None,
        ))
    await session.commit()


async def _stage_search(client, session):
    """同 asset 4 镜头（词法同文本→同 base）：0/1/2 次使用 + 1 近期使用。"""
    sd = await _seed_root(session)
    src = await _seed_asset(session, sd, "ue-search.mp4")
    fva = await _seed_asset(session, sd, "ue-f1.mp4")
    fvb = await _seed_asset(session, sd, "ue-f2.mp4")
    shots = [await _seed_shot(session, src, i + 1) for i in range(4)]
    token = f"urank{uuid.uuid4().hex[:6]}"
    await _seed_search_docs(session, shots, token)
    fv1 = await _seed_fv(client, fva.id, "基准成片1")
    fv2 = await _seed_fv(client, fvb.id, "基准成片2")
    # shot2: 1 次（180 天前）；shot3: 2 次（30 天前）；shot4: 1 次（1 天前）；shot1: 0 次
    await _confirm_usage(client, fv1["id"], shots[1].id)
    await _confirm_usage(client, fv1["id"], shots[2].id)
    await _confirm_usage(client, fv2["id"], shots[2].id)
    await _confirm_usage(client, fv2["id"], shots[3].id)
    for shot, days in ((shots[1], 180), (shots[2], 30), (shots[3], 1)):
        await session.execute(text(
            "UPDATE final_video_usage SET confirmed_at = now() - (:d || ' days')::interval "
            "WHERE source_shot_id = :sid"
        ), {"d": str(days), "sid": shot.id})
    await session.commit()
    return token, shots


async def _search(client, body, expect=200):
    r = await client.post("/api/search/shots", json=body)
    assert r.status_code == expect, r.text
    return r.json()


async def test_default_exact_parity_and_backward_compat(client, session):
    token, shots = await _stage_search(client, session)
    base_req = {"query": token, "search_mode": "lexical", "page": 1, "page_size": 10}
    old = await _search(client, base_req)  # 旧客户端：不带任何 usage 字段
    with_default = await _search(client, {
        **base_req, "usage_mode": "default", "usage_preset": "strong_unused",
        "usage_scope": "shot",
    })
    assert [i["shot_id"] for i in old["items"]] == [i["shot_id"] for i in with_default["items"]]
    assert [i["score"] for i in old["items"]] == [i["score"] for i in with_default["items"]]
    # default：调整恒 0；base==final==score
    for it in with_default["items"]:
        assert it["usage_adjustment"] == 0.0
        assert it["final_score"] == it["base_score"]
    # 旧请求响应含 usage 展示（additive；老客户端忽略即可）
    assert old["items"][0]["usage"] is not None
    # include_usage_explanation=false → 省略 usage 块
    lean = await _search(client, {**base_req, "include_usage_explanation": False})
    assert lean["items"][0]["usage"] is None
    assert [i["shot_id"] for i in lean["items"]] == [i["shot_id"] for i in old["items"]]


async def test_prefer_unused_reorders_equal_relevance(client, session):
    token, shots = await _stage_search(client, session)
    res = await _search(client, {
        "query": token, "search_mode": "lexical", "page": 1, "page_size": 10,
        "usage_mode": "prefer_unused",
    })
    ids = [i["shot_id"] for i in res["items"]]
    # 同 base：未使用 shot1 必须排最前；次数最多的 shot3(2 次) 沉底方向
    assert ids[0] == shots[0].id
    pos = {sid: idx for idx, sid in enumerate(ids)}
    assert pos[shots[0].id] < pos[shots[3].id]  # 未使用 < 近期使用
    assert pos[shots[1].id] < pos[shots[2].id]  # 180 天前 1 次 < 2 次
    unused = next(i for i in res["items"] if i["shot_id"] == shots[0].id)
    assert unused["usage_adjustment"] > 0
    assert any(r["code"] == "shot_never_used" for r in unused["usage_reasons"])
    used = next(i for i in res["items"] if i["shot_id"] == shots[2].id)
    assert used["usage_adjustment"] < 0
    # relevance guard：所有调整受 cap 约束
    for it in res["items"]:
        assert abs(it["usage_adjustment"]) <= ADJUSTMENT_CAP + 1e-9


async def test_hard_filters_and_stats(client, session):
    token, shots = await _stage_search(client, session)
    only = await _search(client, {
        "query": token, "search_mode": "lexical", "page": 1, "page_size": 10,
        "usage_mode": "only_never_confirmed",
    })
    assert [i["shot_id"] for i in only["items"]] == [shots[0].id]
    assert only["usage_stats"]["filtered_count"] == 3
    assert only["usage_stats"]["returned_count"] == 1
    maxr = await _search(client, {
        "query": token, "search_mode": "lexical", "page": 1, "page_size": 10,
        "usage_mode": "exclude_high_frequency", "max_confirmed_usage_count": 1,
    })
    assert shots[2].id not in [i["shot_id"] for i in maxr["items"]]  # 2 次被排除
    recent = await _search(client, {
        "query": token, "search_mode": "lexical", "page": 1, "page_size": 10,
        "usage_mode": "prefer_unused", "exclude_recently_used_days": 60,
    })
    ids = [i["shot_id"] for i in recent["items"]]
    assert shots[3].id not in ids and shots[2].id not in ids  # 1/30 天 < 60
    assert shots[0].id in ids and shots[1].id in ids          # 未使用 + 180 天


async def test_candidate_expansion_prevents_starvation(client, session, monkeypatch):
    """前 K 全部被过滤时扩张候选池，不错误返回空。"""
    from app import config as app_config
    token, shots = await _stage_search(client, session)
    # 候选池压到 2：only_never_confirmed 下前 2 候选可能全 confirmed → 需扩张找到 shot1
    monkeypatch.setattr(app_config.get_settings(), "search_candidate_pool", 2)
    # page_size=2 → 初始池=2（4 个同文本镜头只进 2 个候选）→ 过滤后不足且 truncated → 扩张
    res = await _search(client, {
        "query": token, "search_mode": "lexical", "page": 1, "page_size": 2,
        "usage_mode": "only_never_confirmed",
    })
    assert [i["shot_id"] for i in res["items"]] == [shots[0].id]
    assert res["usage_stats"]["expansion_rounds"] >= 1


async def test_usage_param_validation(client, session):
    token, _ = await _stage_search(client, session)
    base = {"query": token, "page": 1, "page_size": 5}
    await _search(client, {**base, "usage_mode": "bogus"}, expect=422)
    await _search(client, {**base, "usage_scope": "bogus"}, expect=422)
    await _search(client, {**base, "usage_mode": "exclude_high_frequency"}, expect=422)
    await _search(client, {**base, "usage_preset": "bogus"}, expect=422)
    await _search(client, {**base, "usage_weights": {"weight_unused": 99}}, expect=422)
    await _search(client, {**base, "usage_weights": {"bogus": 0.1}}, expect=422)


async def test_saved_search_roundtrip_with_usage(client, session):
    token, _ = await _stage_search(client, session)
    r = await client.post("/api/saved-searches", json={
        "name": f"未使用优先-{uuid.uuid4().hex[:4]}",
        "search_kind": "shot_search",
        "query": {
            "query": token, "usage_mode": "prefer_unused",
            "exclude_recently_used_days": 30, "usage_preset": "strong_unused",
            "page": 1, "page_size": 10,
        },
    })
    assert r.status_code == 201, r.text
    saved = r.json()
    got = (await client.get(f"/api/saved-searches/{saved['id']}")).json()
    assert got["query"]["usage_mode"] == "prefer_unused"
    assert got["query"]["exclude_recently_used_days"] == 30
    assert got["query"]["usage_preset"] == "strong_unused"
    assert "page" not in got["query"]
    # 老 Saved Search（无 usage 字段）加载不失效
    r2 = await client.post("/api/saved-searches", json={
        "name": f"旧式-{uuid.uuid4().hex[:4]}",
        "search_kind": "shot_search",
        "query": {"query": token, "page": 1, "page_size": 10},
    })
    assert r2.status_code == 201
