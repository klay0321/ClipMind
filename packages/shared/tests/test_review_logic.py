"""PR-03B 有效结果/人工优先/stale/投影/标准化 纯逻辑测试。"""

from __future__ import annotations

from clipmind_shared.review import (
    effective_result,
    normalize_name,
    projected_tags,
    review_stale_reason,
)

AI = {"one_line": "AI 描述", "scene": "室内", "risk_flags": ["竞品"]}
HUMAN = {"one_line": "人工修正", "scene": "户外"}


# ---- normalize ----

def test_normalize_fullwidth_case_hyphen_punct():
    assert normalize_name("  ＨｅｙＧｅｎ-Pro!! ") == "heygen pro"
    assert normalize_name("PowerGo_X1") == "powergo x1"
    assert normalize_name("小米 MiMo") == "小米 mimo"
    assert normalize_name(None) == ""


# ---- effective_result（人工优先）----

def test_confirmed_uses_human():
    r = effective_result(AI, review_status="confirmed", confirmed_result=HUMAN)
    assert r.source == "human" and r.confirmed and r.searchable
    assert r.result == HUMAN


def test_modified_uses_human():
    r = effective_result(AI, review_status="modified", confirmed_result=HUMAN)
    assert r.source == "human" and r.result["one_line"] == "人工修正"


def test_unreviewed_uses_ai_temp():
    r = effective_result(AI, review_status="unreviewed", confirmed_result=None)
    assert r.source == "ai" and not r.confirmed and r.searchable
    assert r.result == AI


def test_pending_uses_ai_temp():
    r = effective_result(AI, review_status="pending_review", confirmed_result=None)
    assert r.source == "ai" and r.searchable


def test_no_review_defaults_ai():
    r = effective_result(AI, review_status=None, confirmed_result=None)
    assert r.source == "ai"


def test_rejected_not_searchable():
    r = effective_result(AI, review_status="rejected", confirmed_result=None)
    assert r.source == "rejected" and r.result is None and not r.searchable


def test_unable_not_searchable():
    r = effective_result(AI, review_status="unable", confirmed_result=None)
    assert r.source == "unable" and r.result is None and not r.searchable


def test_unreviewed_without_ai_is_none():
    r = effective_result(None, review_status="unreviewed", confirmed_result=None)
    assert r.source == "none" and r.result is None and not r.searchable


# ---- stale ----

def test_stale_generation_changed():
    assert review_stale_reason(
        review_generation=1, current_generation=2,
        review_fingerprint="a", current_fingerprint="a",
    ) == "generation_changed"


def test_stale_fingerprint_changed():
    assert review_stale_reason(
        review_generation=1, current_generation=1,
        review_fingerprint="a", current_fingerprint="b",
    ) == "fingerprint_changed"


def test_not_stale_when_same():
    assert review_stale_reason(
        review_generation=1, current_generation=1,
        review_fingerprint="a", current_fingerprint="a",
    ) is None


# ---- projection ----

def test_projected_tags_from_result():
    result = {
        "product": {"name": "充电器"},
        "scene": "桌面", "action": "展示", "shot_type": "产品特写",
        "marketing_use": ["卖点证明"], "quality_issues": ["模糊"],
        "risk_flags": ["竞品", "竞品"],  # 去重
    }
    tags = projected_tags(result)
    assert ("product", "充电器") in tags
    assert ("scene", "桌面") in tags
    assert ("risk", "竞品") in tags
    assert ("marketing", "卖点证明") in tags
    assert tags.count(("risk", "竞品")) == 1  # 去重


def test_projected_tags_empty():
    assert projected_tags(None) == []
    assert projected_tags({}) == []
