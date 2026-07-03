"""PR-E.1 检索排序确定性回归（需要 TEST_DATABASE_URL；.local/pr-e1 审计的锁定测试）。

锁定：同分（主动制造，不靠随机碰撞）时各通道 / 融合 / 分页 / 扩张 / Saved Search
重放的顺序完全确定，tie-break 收尾于 shot_id；重复执行 20 次逐位一致；
分页与一次性 top_k 等价（无重复无遗漏）。不改变任何分数公式与筛选语义。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Asset, Shot, ShotSearchDocument, SourceDirectory
from clipmind_shared.models.enums import (
    AssetStatus,
    SearchDocumentStatus,
    SearchEmbeddingStatus,
    SearchKind,
    ShotStatus,
)
from clipmind_shared.search.scoring import Candidate, order_candidates, score_candidates
from sqlalchemy import text

from app.services import search_service
from app.services.query_serde import serialize_query

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)

REPEAT = 20
EMB_VERSION = "det-test-v1"


# ============================ seed helpers ============================


async def _seed_root(session) -> SourceDirectory:
    sd = SourceDirectory(
        name=f"det-{uuid.uuid4().hex[:8]}", mount_path="/app/source",
        include_extensions=["mp4"], exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    return sd


async def _seed_asset(session, sd, rel) -> Asset:
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


async def _seed_shot(session, asset, seq) -> Shot:
    s = Shot(
        asset_id=asset.id, generation=1, sequence_no=seq,
        start_time=float(seq - 1), end_time=float(seq), duration=1.0,
        detector_type="fixed", status=ShotStatus.READY,
        keyframe_path=f"k/{asset.id}-{seq}.jpg",
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


async def _seed_doc(session, shot, text_, *, embedding=None):
    session.add(ShotSearchDocument(
        shot_id=shot.id,
        shot_generation=shot.generation,
        asset_id=shot.asset_id,
        document_status=SearchDocumentStatus.INDEXED,
        embedding_status=(
            SearchEmbeddingStatus.COMPLETED if embedding is not None
            else SearchEmbeddingStatus.DEGRADED
        ),
        is_searchable=True,
        search_document=text_,
        normalized_document=text_,
        embedding=embedding,
        embedding_version=EMB_VERSION if embedding is not None else "",
    ))
    await session.commit()


async def _equalize_created_at(session, shots):
    """把 created_at 抹平到同一时刻——否则 created_at 已是全序 tie-break，
    测不到 shot_id 兜底。"""
    fixed = datetime(2026, 1, 1, 12, 0, 0)
    await session.execute(
        text("UPDATE shot SET created_at = :ts WHERE id = ANY(:ids)"),
        {"ts": fixed, "ids": [s.id for s in shots]},
    )
    await session.commit()


async def _stage_equal_lexical(client, session, n=4):
    """n 个镜头：同文本（同 ts_rank）、同 created_at、无 usage 差异 → 完全同分。"""
    sd = await _seed_root(session)
    src = await _seed_asset(session, sd, f"det-{uuid.uuid4().hex[:6]}.mp4")
    shots = [await _seed_shot(session, src, i + 1) for i in range(n)]
    token = f"dettok{uuid.uuid4().hex[:6]}"
    for s in shots:
        await _seed_doc(session, s, f"{token} 中性镜头 演示")
    await _equalize_created_at(session, shots)
    return token, shots


async def _search(client, body):
    r = await client.post("/api/search/shots", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(res) -> list[int]:
    return [i["shot_id"] for i in res["items"]]


# ============================ 通道级 ============================


async def test_lexical_equal_score_order_is_stable(client, session):
    token, shots = await _stage_equal_lexical(client, session)
    body = {"query": token, "search_mode": "lexical", "page": 1, "page_size": 10}
    first = _ids(await _search(client, body))
    assert set(first) == {s.id for s in shots}
    for _ in range(REPEAT - 1):
        assert _ids(await _search(client, body)) == first
    # 同分 → shot_id 升序兜底
    assert first == sorted(first)


async def test_vector_equal_score_order_is_stable(client, session):
    sd = await _seed_root(session)
    src = await _seed_asset(session, sd, f"det-v-{uuid.uuid4().hex[:6]}.mp4")
    shots = [await _seed_shot(session, src, i + 1) for i in range(4)]
    vec = [0.1] * 384  # 相同向量 → 对任意查询向量距离完全相同
    for s in shots:
        await _seed_doc(session, s, "向量确定性 演示", embedding=vec)
    qvec = [0.2] * 384
    runs = []
    for _ in range(REPEAT):
        rows = await search_service._channel_vector(
            session, search_service._Merged(), qvec, EMB_VERSION, 50
        )
        runs.append([sid for sid, _score in rows if sid in {s.id for s in shots}])
    assert all(r == runs[0] for r in runs)
    assert runs[0] == sorted(s.id for s in shots)  # distance 同 → shot_id 升序


async def test_hybrid_equal_score_order_is_stable(client, session):
    token, shots = await _stage_equal_lexical(client, session)
    body = {"query": token, "search_mode": "hybrid", "page": 1, "page_size": 10}
    first = _ids(await _search(client, body))
    assert set(first) == {s.id for s in shots}
    for _ in range(REPEAT - 1):
        assert _ids(await _search(client, body)) == first


# ============================ 融合纯函数 ============================


def _cand(sid: int, lex: float | None = None, tag: float | None = None) -> Candidate:
    c = Candidate(shot_id=sid)
    if lex is not None:
        c.lexical_score = lex
    if tag is not None:
        c.tag_score = tag
    return c


def test_channel_merge_order_does_not_change_result():
    """候选插入顺序（模拟通道完成顺序差异）不得影响融合输出顺序。"""
    def build(order):
        cands = [_cand(sid, lex=0.5, tag=0.5) for sid in order]
        return [c.shot_id for c in score_candidates(cands, active_channels=["lexical", "tag"])]

    a = build([3, 1, 2, 4])
    b = build([4, 2, 1, 3])
    c = build([1, 2, 3, 4])
    assert a == b == c == [1, 2, 3, 4]  # 全同分 → shot_id 升序


def test_lru_adjustment_stable_within_day():
    """days 量化到整天：同一天内不同请求时刻的 lru/recent 调整完全一致
    （否则连续小数天使临界同分对随每次请求翻转——PR-E.1 实测复现的抖动源）。"""
    from datetime import UTC, timedelta

    from app.services.usage_feature_service import UsageFeatures
    from app.services.usage_ranking import compute_adjustment, resolve_weights

    f = UsageFeatures(
        shot_id=1, shot_confirmed_usage_count=1,
        shot_last_confirmed_used_at=datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC),
    )
    w = resolve_weights("balanced", None)
    t0 = datetime(2026, 7, 3, 13, 0, 0, tzinfo=UTC)
    adjustments = {
        compute_adjustment(
            f, weights=w, mode="least_recently_used", scope="shot",
            include_legacy_unknown=True, now=t0 + timedelta(seconds=s),
        )[0]
        for s in (0, 1, 40, 600, 3600)
    }
    assert len(adjustments) == 1  # 同一天内恒定
    days = f.days_since_last_confirmed_use(t0)
    assert days == float(int(days))  # 整数天


def test_tie_break_uses_shot_id():
    """order_candidates 在 final/quality/review/created_at 全部并列时以 shot_id 收尾。"""
    ts = datetime(2026, 1, 1)
    cands = []
    for sid in (42, 7, 19):
        c = Candidate(shot_id=sid)
        c.final_score = 0.5
        c.quality_score = 0.5
        c.created_at = ts
        cands.append(c)
    assert [c.shot_id for c in order_candidates(cands)] == [7, 19, 42]


# ============================ 端到端重复 ============================


async def test_default_search_repeated_20_times_same_order(client, session):
    token, _shots = await _stage_equal_lexical(client, session, n=6)
    body = {"query": token, "search_mode": "lexical", "page": 1, "page_size": 10}
    first = _ids(await _search(client, body))
    for _ in range(REPEAT - 1):
        assert _ids(await _search(client, body)) == first


async def test_usage_search_repeated_20_times_same_order(client, session):
    token, shots = await _stage_equal_lexical(client, session)
    # 制造 usage 差异：shot2 确认 1 次（其余同分）
    fva = await _seed_asset(session, (await _seed_root(session)), "det-fv.mp4")
    r = await client.post("/api/final-videos", json={"asset_id": fva.id, "title": "det成片"})
    assert r.status_code == 201
    fv = r.json()
    r = await client.post(
        f"/api/final-videos/{fv['id']}/usages", json={"source_shot_id": shots[1].id}
    )
    assert r.status_code == 201
    r = await client.post(f"/api/final-video-usages/{r.json()['id']}/confirm")
    assert r.status_code == 200
    body = {"query": token, "search_mode": "lexical", "page": 1, "page_size": 10,
            "usage_mode": "prefer_unused"}
    first = _ids(await _search(client, body))
    assert first.index(shots[1].id) == len(first) - 1  # 已使用者沉底（其余同分）
    for _ in range(REPEAT - 1):
        assert _ids(await _search(client, body)) == first


async def test_candidate_expansion_is_deterministic(client, session, monkeypatch):
    token, shots = await _stage_equal_lexical(client, session, n=4)
    from app import config as app_config
    settings = app_config.get_settings()
    monkeypatch.setattr(settings, "search_candidate_pool", 2)
    body = {"query": token, "search_mode": "lexical", "page": 1, "page_size": 2,
            "usage_mode": "only_never_confirmed"}
    first = await _search(client, body)
    for _ in range(REPEAT - 1):
        cur = await _search(client, body)
        assert _ids(cur) == _ids(first)
        assert cur["usage_stats"]["expansion_rounds"] == first["usage_stats"]["expansion_rounds"]


async def test_pagination_has_no_duplicates_or_gaps(client, session):
    token, shots = await _stage_equal_lexical(client, session, n=6)
    base = {"query": token, "search_mode": "lexical"}
    p1 = _ids(await _search(client, {**base, "page": 1, "page_size": 3}))
    p2 = _ids(await _search(client, {**base, "page": 2, "page_size": 3}))
    top6 = _ids(await _search(client, {**base, "page": 1, "page_size": 6}))
    combined = p1 + p2
    assert combined == top6  # 分页拼接 == 一次性 top_k（同一排序键）
    assert len(set(combined)) == len(combined)  # 无重复
    assert set(combined) == {s.id for s in shots}  # 无遗漏


async def test_saved_search_replay_same_order(client, session):
    token, _shots = await _stage_equal_lexical(client, session)
    body = {"query": token, "search_mode": "lexical", "page": 1, "page_size": 10,
            "usage_mode": "prefer_unused"}
    first = _ids(await _search(client, body))
    # 走 Saved Search 的序列化/反序列化再重放（与 /api/saved-searches 同一 serde；
    # serde 去分页，运行时补回——与前端 loadSaved 行为一致）
    replay = serialize_query(SearchKind.SHOT_SEARCH, body)
    replay.update({"page": 1, "page_size": 10})
    for _ in range(REPEAT - 1):
        assert _ids(await _search(client, dict(replay))) == first
