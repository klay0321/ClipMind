"""Gate B 融合评分单测（纯逻辑）。"""

from __future__ import annotations

from datetime import datetime, timezone

from clipmind_shared.search.scoring import (
    Candidate,
    order_candidates,
    paginate,
    score_candidates,
)


def _c(shot_id: int, **kw) -> Candidate:
    return Candidate(shot_id=shot_id, **kw)


def test_rrf_orders_by_combined_rank():
    cands = [
        _c(1, semantic_score=0.9, lexical_score=0.2),
        _c(2, semantic_score=0.3, lexical_score=0.9),
        _c(3, semantic_score=0.95, lexical_score=0.95),
    ]
    out = score_candidates(cands, active_channels=["semantic", "lexical"])
    # shot 3 在两通道都靠前 → 综合第一
    assert out[0].shot_id == 3
    assert all(0.0 <= c.final_score <= 1.0 for c in out)


def test_missing_vector_not_zeroed():
    """无向量分的候选不应被判 0 分淘汰：仅凭词法仍可有正分并可排前。"""
    cands = [
        _c(1, lexical_score=0.95),                    # 仅词法
        _c(2, semantic_score=0.05, lexical_score=0.05),
    ]
    out = score_candidates(cands, active_channels=["semantic", "lexical"])
    top = next(c for c in out if c.shot_id == 1)
    assert top.final_score > 0.0
    assert out[0].shot_id == 1
    assert top.semantic_score is None  # 缺失保持 None，不伪造 0


def test_exact_product_gets_bonus():
    base = _c(1, product_score=0.8)
    exact = _c(2, product_score=0.8, exact_product=True)
    out = {c.shot_id: c for c in score_candidates([base, exact], active_channels=["product"])}
    assert out[2].final_score > out[1].final_score


def test_review_bonus_and_risk_penalty():
    plain = _c(1, lexical_score=0.5)
    human = _c(2, lexical_score=0.5, is_human_effective=True)
    risky = _c(3, lexical_score=0.5, has_unexcluded_risk=True)
    out = {c.shot_id: c for c in score_candidates([plain, human, risky], active_channels=["lexical"])}
    assert out[2].final_score > out[1].final_score          # 人工加权
    assert out[3].final_score < out[1].final_score          # 风险惩罚
    assert out[2].review_bonus > 0 and out[3].risk_penalty > 0


def test_stable_tiebreaker_human_then_created_then_id():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    # 三个候选 final 相同（无通道分），用 tie-breaker 决定顺序
    a = _c(10, created_at=t1)
    b = _c(11, is_human_effective=True, created_at=t1)
    c = _c(12, created_at=t0)
    out = order_candidates([a, b, c])
    # human 优先；非 human 中 created_at 早者优先；再按 shot_id
    assert [x.shot_id for x in out] == [11, 12, 10]


def test_pagination_no_dup_no_loss():
    cands = [_c(i, lexical_score=1.0 - i * 0.01) for i in range(1, 26)]
    ordered = score_candidates(cands, active_channels=["lexical"])
    p1 = paginate(ordered, 1, 10)
    p2 = paginate(ordered, 2, 10)
    p3 = paginate(ordered, 3, 10)
    ids = [c.shot_id for c in p1 + p2 + p3]
    assert len(ids) == 25
    assert len(set(ids)) == 25            # 无重复
    assert paginate(ordered, 99, 10) == []  # 越界为空，不丢不复


def test_risk_penalty_never_dominates_relevance():
    """真实事故回归：搜 TikTok 时含 TikTok 的镜头都带风险标签。
    风险只能作同分级微调，绝不能把强相关命中压到弱相关无风险镜头之后。"""
    target = _c(1, semantic_score=0.92, lexical_score=0.03, has_unexcluded_risk=True)
    noise = _c(2, semantic_score=0.88)
    out = score_candidates([target, noise], active_channels=["semantic", "lexical"])
    assert out[0].shot_id == 1
    assert out[0].risk_penalty > 0  # 风险仍被记录展示，只是不主宰排序


def test_multi_channel_hit_not_diluted_by_lexical_scale():
    """真实事故回归：词法 ts_rank（~0.03 量级）与语义余弦不可比。
    强语义命中同时被词法弱分召回时，不得被跨通道均值稀释到弱语义单通道之后。"""
    both = _c(1, semantic_score=0.91, lexical_score=0.03)   # 双通道命中（词法原始分低是量纲）
    vec_only = _c(2, semantic_score=0.885)                  # 仅语义、分数略低
    out = score_candidates([both, vec_only], active_channels=["semantic", "lexical"])
    assert out[0].shot_id == 1
