"""Gate B：规则派生的匹配解释（纯逻辑，可单测）。

匹配理由 / 不匹配项 / 风险提示**全部来自真实命中事实**（``MatchFacts``，由 ``search_service``
依据 SQL 召回结果与 DB 标签填充），绝不由 LLM 自由生成、绝不编造画面中不存在的对象、绝不写
营销式推荐文案。

关键约束：
- ``semantic_matched`` 为真**当且仅当**该镜头确实进入了向量召回（completed embedding + 版本一致）；
  embedding 降级时永不输出“语义相似”理由，而是在不匹配项标注“embedding 降级”。
- 风险提示来自 DB 中真实的 risk 标签 / 审核结果，不臆测。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MatchFacts:
    """单个候选镜头与查询条件比对后的**真实事实**。"""

    # ---- 命中（matched）----
    matched_products: list[str] = field(default_factory=list)
    exact_product_label: str | None = None      # 精确 SKU/型号命中的可读标签
    matched_scenes: list[str] = field(default_factory=list)
    matched_actions: list[str] = field(default_factory=list)
    matched_shot_types: list[str] = field(default_factory=list)
    matched_marketing: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    semantic_matched: bool = False              # 确实进入向量召回
    quality_requested: bool = False
    quality_satisfied: bool = False
    is_human_confirmed: bool = False
    excluded_risks_clear: list[str] = field(default_factory=list)  # 用户要求排除且确实不含

    # ---- 未命中（unmatched，软条件）----
    unmatched_scenes: list[str] = field(default_factory=list)
    unmatched_actions: list[str] = field(default_factory=list)
    unmatched_shot_types: list[str] = field(default_factory=list)
    unmatched_marketing: list[str] = field(default_factory=list)
    product_mismatch: str | None = None         # 要求产品但本镜头产品不一致/缺失
    quality_unmet: bool = False
    embedding_degraded: bool = False            # 索引降级 → 未参与语义匹配
    requires_human_confirmation: bool = False   # 命中需人工确认（描述匹配用）

    # ---- 风险提示（来自真实 risk 标签）----
    present_risks: list[str] = field(default_factory=list)


def _join(values: list[str], limit: int = 5) -> str:
    vals = values[:limit]
    suffix = "…" if len(values) > limit else ""
    return "、".join(vals) + suffix


def build_matched_reasons(facts: MatchFacts) -> list[str]:
    reasons: list[str] = []
    if facts.exact_product_label:
        reasons.append(f"产品精确匹配：{facts.exact_product_label}")
    elif facts.matched_products:
        reasons.append(f"产品匹配：{_join(facts.matched_products)}")
    if facts.matched_scenes:
        reasons.append(f"场景匹配：{_join(facts.matched_scenes)}")
    if facts.matched_actions:
        reasons.append(f"动作匹配：{_join(facts.matched_actions)}")
    if facts.matched_shot_types:
        reasons.append(f"镜头类型匹配：{_join(facts.matched_shot_types)}")
    if facts.matched_marketing:
        reasons.append(f"营销用途匹配：{_join(facts.matched_marketing)}")
    if facts.matched_keywords:
        reasons.append(f"关键词命中：{_join(facts.matched_keywords)}")
    # 语义理由严格门控：仅在真实进入向量召回且未降级时输出
    if facts.semantic_matched and not facts.embedding_degraded:
        reasons.append("语义相似（向量召回）")
    if facts.quality_requested and facts.quality_satisfied:
        reasons.append("质量满足要求")
    if facts.is_human_confirmed:
        reasons.append("已人工确认")
    if facts.excluded_risks_clear:
        reasons.append(f"风险已排除：{_join(facts.excluded_risks_clear)}")
    return reasons


def build_unmatched_requirements(facts: MatchFacts) -> list[str]:
    items: list[str] = []
    if facts.product_mismatch:
        items.append(f"产品不一致：要求 {facts.product_mismatch}")
    if facts.unmatched_scenes:
        items.append(f"场景仅相似：{_join(facts.unmatched_scenes)}")
    if facts.unmatched_actions:
        items.append(f"动作不完整：{_join(facts.unmatched_actions)}")
    if facts.unmatched_shot_types:
        items.append(f"镜头类型未匹配：{_join(facts.unmatched_shot_types)}")
    if facts.unmatched_marketing:
        items.append(f"营销用途未匹配：{_join(facts.unmatched_marketing)}")
    if facts.quality_requested and facts.quality_unmet:
        items.append("质量不足")
    if facts.requires_human_confirmation:
        items.append("缺少人工确认（建议复核）")
    if facts.embedding_degraded:
        items.append("embedding 降级，未参与语义匹配")
    return items


def build_risk_warnings(facts: MatchFacts) -> list[str]:
    return [f"风险提示：{r}" for r in facts.present_risks]


def build_explanations(facts: MatchFacts) -> tuple[list[str], list[str], list[str]]:
    """返回 (matched_reasons, unmatched_requirements, risk_warnings)。"""
    return (
        build_matched_reasons(facts),
        build_unmatched_requirements(facts),
        build_risk_warnings(facts),
    )
