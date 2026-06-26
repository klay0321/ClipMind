"""检索文档构建（PR-04）。

把"有效结果"（ShotAnalysisResult 形状的 dict：AI parsed_result 或人工 confirmed_result）
拼装为**稳定、可版本化、可哈希**的检索文档：

- ``text``：自然语言检索文档，保留原文/语言（中英混合），供 Embedding（passage）与展示；
- ``normalized_document``：归一化文本（NFKC+小写+标点折叠），供 pg_trgm 词法匹配；
- ``axes``：结构化轴（产品/场景/动作/...，去重保序），供解释性与调试；
- ``document_hash``：sha256(规范化 text + axes + result_schema_version + template_version)，
  内容/模板任一变化即变，用于幂等判定（配合嵌入身份共同决定是否重嵌）。

设计：仅纳入**可语义嵌入的内容字段**（描述/产品/场景/动作/卖点/文字等）；时长/画幅/审核
状态/来源目录等**结构化过滤维度**不进嵌入文本（避免噪声），由检索文档行的列与联接承载。
模板顺序固定、section 内去重保序——相同数据必得相同哈希。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from clipmind_shared.constants import SEARCH_DOCUMENT_TEMPLATE_VERSION
from clipmind_shared.review.normalize import normalize_name


@dataclass
class SearchDocumentContent:
    text: str = ""
    normalized_document: str = ""
    axes: dict[str, list[str]] = field(default_factory=dict)
    template_version: int = SEARCH_DOCUMENT_TEMPLATE_VERSION
    document_hash: str = ""


def _clean(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def _str_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        s = _clean(v)
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _add_terms(target: list[str], seen: set[str], values: Iterable[str]) -> None:
    for v in values:
        s = _clean(v)
        if s and s not in seen:
            seen.add(s)
            target.append(s)


def build_search_document(
    result: dict[str, Any] | None,
    *,
    product_terms: Iterable[str] = (),
    result_schema_version: int = 0,
) -> SearchDocumentContent:
    """从有效结果（+ 产品库补充词）构建检索文档。``result`` 为 None/空 → 空文档（稳定哈希）。

    ``result_schema_version`` 由调用方传入（AI/人工结果的 schema 版本），参与哈希，便于按
    schema 升级触发重建。
    """
    result = result or {}
    product = result.get("product")
    product = product if isinstance(product, dict) else {}

    # ---- 结构化轴（去重保序）----
    product_names: list[str] = []
    p_seen: set[str] = set()
    _add_terms(product_names, p_seen, [product.get("name", "")])
    _add_terms(product_names, p_seen, [product.get("model", "")])
    _add_terms(product_names, p_seen, product_terms)

    axes: dict[str, list[str]] = {
        "products": product_names,
        "scenes": _str_list([result.get("scene")]),
        "actions": _str_list([result.get("action")]),
        "shot_types": _str_list([result.get("shot_type")]),
        "subjects": _str_list([result.get("subject")]),
        "marketing": _str_list(result.get("marketing_use")),
        "selling_points": _str_list(result.get("selling_points")),
        "recommended_scenes": _str_list(result.get("recommended_scenes")),
        "visible_text": _str_list(result.get("visible_text")),
        "logo_brand": _str_list(result.get("logo_brand")),
        "keywords": _str_list(result.get("search_keywords")),
        "quality_issues": _str_list(result.get("quality_issues")),
        "risk_flags": _str_list(result.get("risk_flags")),
    }
    # 去掉空轴，保证哈希稳定（顺序由下方 sort_keys 决定）
    axes = {k: v for k, v in axes.items() if v}

    # ---- 自然语言文档（固定 section 顺序；无人造标签，最大化嵌入语义）----
    sections: list[str] = []

    def push(*parts: str) -> None:
        joined = " / ".join(p for p in parts if p)
        if joined:
            sections.append(joined)

    push(_clean(result.get("one_line")))
    push(_clean(result.get("detailed")))
    push(*axes.get("products", []))
    push(*axes.get("scenes", []), *axes.get("actions", []), *axes.get("shot_types", []))
    push(*axes.get("subjects", []))
    push(*axes.get("marketing", []))
    push(*axes.get("selling_points", []))
    push(*axes.get("recommended_scenes", []))
    push(*axes.get("visible_text", []))
    push(*axes.get("logo_brand", []))
    push(*axes.get("keywords", []))

    text = "\n".join(sections)
    normalized_document = normalize_name(text.replace("\n", " "))

    document_hash = compute_document_hash(
        text=text,
        axes=axes,
        result_schema_version=result_schema_version,
        template_version=SEARCH_DOCUMENT_TEMPLATE_VERSION,
    )
    return SearchDocumentContent(
        text=text,
        normalized_document=normalized_document,
        axes=axes,
        template_version=SEARCH_DOCUMENT_TEMPLATE_VERSION,
        document_hash=document_hash,
    )


def compute_document_hash(
    *,
    text: str,
    axes: dict[str, list[str]],
    result_schema_version: int,
    template_version: int,
) -> str:
    """稳定文档哈希（与字段顺序无关；含模板/结果 schema 版本）。"""
    payload = {
        "text": text,
        "axes": {k: list(v) for k, v in sorted(axes.items())},
        "result_schema_version": result_schema_version,
        "template_version": template_version,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
