"""检索文档构建测试：内容覆盖、稳定哈希、空结果、产品补充词、模板/schema 版本。"""

from __future__ import annotations

from clipmind_shared.constants import SEARCH_DOCUMENT_TEMPLATE_VERSION
from clipmind_shared.search import build_search_document, compute_document_hash

RESULT = {
    "one_line": "桌面充电演示",
    "detailed": "充电器放在桌面上为手机充电",
    "product": {"name": "PowerGo", "model": "P1", "color": "白", "state": "充电中"},
    "scene": "桌面",
    "action": "充电",
    "shot_type": "产品特写",
    "subject": "手",
    "marketing_use": ["使用演示"],
    "selling_points": ["快充"],
    "visible_text": ["PowerGo"],
    "logo_brand": ["PowerGo"],
    "quality_issues": [],
    "risk_flags": [],
    "search_keywords": ["充电", "桌面"],
    "recommended_scenes": ["居家"],
}


def test_content_covers_semantic_fields():
    c = build_search_document(RESULT)
    assert "桌面充电演示" in c.text
    assert "PowerGo" in c.text
    assert "使用演示" in c.text
    assert c.axes["products"] == ["PowerGo", "P1"]
    assert c.axes["scenes"] == ["桌面"]
    assert c.axes["actions"] == ["充电"]
    assert c.template_version == SEARCH_DOCUMENT_TEMPLATE_VERSION
    assert c.document_hash


def test_normalized_document_is_folded():
    c = build_search_document({"one_line": "PowerGo  Charger", "detailed": ""})
    # normalize：小写 + 空格折叠
    assert "powergo charger" in c.normalized_document


def test_hash_deterministic_and_content_sensitive():
    a = build_search_document(RESULT).document_hash
    b = build_search_document(RESULT).document_hash
    assert a == b
    changed = dict(RESULT, scene="户外")
    assert build_search_document(changed).document_hash != a


def test_empty_result_stable_hash():
    c1 = build_search_document(None)
    c2 = build_search_document({})
    assert c1.text == ""
    assert c1.axes == {}
    assert c1.document_hash == c2.document_hash


def test_product_terms_folded():
    c = build_search_document(RESULT, product_terms=["PowerGo Pro", "SKU123"])
    assert "PowerGo Pro" in c.axes["products"]
    assert "SKU123" in c.axes["products"]
    assert "SKU123" in c.text


def test_schema_version_changes_hash():
    h1 = build_search_document(RESULT, result_schema_version=1).document_hash
    h2 = build_search_document(RESULT, result_schema_version=2).document_hash
    assert h1 != h2


def test_compute_hash_order_independent():
    h1 = compute_document_hash(
        text="t", axes={"a": ["1"], "b": ["2"]}, result_schema_version=1, template_version=1
    )
    h2 = compute_document_hash(
        text="t", axes={"b": ["2"], "a": ["1"]}, result_schema_version=1, template_version=1
    )
    assert h1 == h2
