"""产品候选匹配（纯逻辑，确定性，可测）。

匹配顺序：SKU 精确 → 型号精确 → 标准名精确 → alias 精确 → 标准化包含/前缀 → 模糊。
所有结果**只是候选**：不写库、不自动绑定 confirmed_product_id；同名歧义返回多个候选。
稳定排序：按 (match_type 优先级, -score, product_id)。
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from clipmind_shared.review.normalize import normalize_name

# 匹配类型优先级（越靠前越优先）
MATCH_PRIORITY: tuple[str, ...] = ("sku", "model", "name", "alias", "contains", "fuzzy")
_BASE_SCORE = {"sku": 1.0, "model": 0.95, "name": 0.9, "alias": 0.85}
_FUZZY_MIN = 0.5  # 低于此不作为候选


@dataclass
class ProductLike:
    id: int
    name: str
    brand: str | None
    model: str | None
    sku: str | None
    normalized_name: str
    normalized_aliases: list[str]


@dataclass
class Candidate:
    product_id: int
    product_name: str
    brand: str | None
    model: str | None
    sku: str | None
    match_type: str
    match_score: float
    match_reason: str


def _ratio(a: str, b: str) -> float:
    return round(SequenceMatcher(None, a, b).ratio(), 4)


def _best_match(qn: str, p: ProductLike) -> tuple[str, float, str] | None:
    if p.sku and normalize_name(p.sku) == qn:
        return ("sku", _BASE_SCORE["sku"], f"SKU 精确匹配 {p.sku}")
    if p.model and normalize_name(p.model) == qn:
        return ("model", _BASE_SCORE["model"], f"型号精确匹配 {p.model}")
    if p.normalized_name == qn:
        return ("name", _BASE_SCORE["name"], "产品标准名精确匹配")
    if qn in p.normalized_aliases:
        return ("alias", _BASE_SCORE["alias"], "别名精确匹配")
    # 包含/前缀
    if qn and (p.normalized_name.startswith(qn) or qn in p.normalized_name):
        score = round(0.6 * (len(qn) / max(len(p.normalized_name), 1)), 4)
        return ("contains", min(score, 0.79), "标准化包含/前缀匹配")
    for a in p.normalized_aliases:
        if qn and (a.startswith(qn) or qn in a):
            return ("contains", 0.55, "别名包含/前缀匹配")
    # 模糊
    cands = [p.normalized_name, *p.normalized_aliases]
    best = max((_ratio(qn, c) for c in cands), default=0.0)
    if best >= _FUZZY_MIN:
        return ("fuzzy", best, f"模糊匹配相似度 {best}")
    return None


def match_products(query_name: str | None, products: list[ProductLike]) -> list[Candidate]:
    qn = normalize_name(query_name)
    if not qn:
        return []
    out: list[Candidate] = []
    for p in products:
        m = _best_match(qn, p)
        if m is None:
            continue
        match_type, score, reason = m
        out.append(
            Candidate(
                product_id=p.id, product_name=p.name, brand=p.brand, model=p.model,
                sku=p.sku, match_type=match_type, match_score=score, match_reason=reason,
            )
        )
    out.sort(key=lambda c: (MATCH_PRIORITY.index(c.match_type), -c.match_score, c.product_id))
    return out
