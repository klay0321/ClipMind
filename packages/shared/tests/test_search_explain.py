"""Gate B 规则解释单测（纯逻辑）。"""

from __future__ import annotations

from clipmind_shared.search.explain import (
    MatchFacts,
    build_explanations,
    build_matched_reasons,
    build_risk_warnings,
    build_unmatched_requirements,
)


def test_matched_reasons_reflect_real_hits():
    facts = MatchFacts(
        exact_product_label="SKU SKU9",
        matched_scenes=["室内"],
        matched_actions=["充电"],
        matched_keywords=["充电器"],
        is_human_confirmed=True,
        excluded_risks_clear=["水印"],
    )
    reasons = build_matched_reasons(facts)
    assert "产品精确匹配：SKU SKU9" in reasons
    assert "场景匹配：室内" in reasons
    assert "动作匹配：充电" in reasons
    assert "关键词命中：充电器" in reasons
    assert "已人工确认" in reasons
    assert "风险已排除：水印" in reasons


def test_semantic_reason_only_when_truly_matched():
    yes = build_matched_reasons(MatchFacts(semantic_matched=True))
    assert "语义相似（向量召回）" in yes
    no = build_matched_reasons(MatchFacts(semantic_matched=False))
    assert "语义相似（向量召回）" not in no


def test_degraded_never_claims_semantic_match():
    """embedding 降级时绝不输出语义理由，且在不匹配项标注降级。"""
    facts = MatchFacts(semantic_matched=True, embedding_degraded=True)
    matched = build_matched_reasons(facts)
    unmatched = build_unmatched_requirements(facts)
    assert "语义相似（向量召回）" not in matched
    assert "embedding 降级，未参与语义匹配" in unmatched


def test_unmatched_requirements():
    facts = MatchFacts(
        product_mismatch="充电宝",
        unmatched_scenes=["户外"],
        unmatched_actions=["对比"],
        quality_requested=True,
        quality_unmet=True,
    )
    items = build_unmatched_requirements(facts)
    assert "产品不一致：要求 充电宝" in items
    assert "场景仅相似：户外" in items
    assert "动作不完整：对比" in items
    assert "质量不足" in items


def test_risk_warnings_from_real_tags():
    facts = MatchFacts(present_risks=["竞品", "水印"])
    warnings = build_risk_warnings(facts)
    assert warnings == ["风险提示：竞品", "风险提示：水印"]


def test_no_fabricated_fields_when_empty():
    matched, unmatched, risks = build_explanations(MatchFacts())
    assert matched == []
    assert unmatched == []
    assert risks == []
