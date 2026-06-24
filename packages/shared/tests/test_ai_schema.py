"""ShotAnalysisResult 结构化 Schema 校验测试（PR-03A）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clipmind_shared.ai.schema import (
    ShotAnalysisResult,
    shot_analysis_json_schema,
    validate_shot_analysis,
)


def test_empty_is_valid_with_defaults():
    r = ShotAnalysisResult()
    assert r.one_line == ""
    assert r.product.name == ""
    assert r.marketing_use == []
    assert r.confidence == 0.0
    assert r.needs_human_review is False


def test_full_dict_validates():
    data = {
        "one_line": "产品特写",
        "detailed": "桌面上的充电器特写",
        "product": {"name": "充电器", "model": "X1", "color": "白色", "state": "全新"},
        "scene": "桌面",
        "action": "展示",
        "shot_type": "产品特写",
        "marketing_use": ["卖点证明"],
        "selling_points": ["快充"],
        "risk_flags": [],
        "confidence": 0.82,
        "needs_human_review": True,
        "search_keywords": ["充电器", "快充"],
    }
    r = validate_shot_analysis(data)
    assert r.product.model == "X1"
    assert r.confidence == 0.82
    assert r.needs_human_review is True


def test_extra_keys_ignored():
    r = validate_shot_analysis({"one_line": "x", "unknown_field": 123})
    assert r.one_line == "x"
    assert not hasattr(r, "unknown_field")


@pytest.mark.parametrize("bad", [-0.1, 1.5, 2.0])
def test_confidence_out_of_range_rejected(bad):
    with pytest.raises(ValidationError):
        validate_shot_analysis({"confidence": bad})


def test_json_schema_exposes_fields():
    schema = shot_analysis_json_schema()
    props = schema["properties"]
    for key in ("one_line", "confidence", "risk_flags", "needs_human_review", "product"):
        assert key in props
