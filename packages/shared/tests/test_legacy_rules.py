"""PR-C Gate B 规则引擎纯函数测试（零 IO，锁定 docs/LEGACY_USAGE_EVIDENCE.md）。

安全语义：无任意正则（只有 4 个字符串算子）；NFKC + 分隔符统一 + casefold；
pattern 拒绝路径穿越；evidence_key 幂等锚不含 location id。
"""

from __future__ import annotations

import pytest
from clipmind_shared.legacy_rules import (
    MATCH_OPERATORS,
    MATCH_TARGETS,
    RuleSpec,
    RuleValidationError,
    compute_evidence_key,
    compute_snapshot_hash,
    evidence_type_for,
    frozen_rule_from_snapshot,
    match_rule,
    normalize_text,
    validate_pattern,
    validate_rule_config,
)


def _spec(**kw) -> RuleSpec:
    base = dict(
        rule_id=1,
        match_target="directory_segment",
        match_operator="equals",
        normalized_pattern=normalize_text("已使用标记"),
        case_sensitive=False,
    )
    base.update(kw)
    return RuleSpec(**base)


# ============================ 归一化 ============================


def test_normalize_nfkc_fullwidth_and_casefold():
    # 全角字母/数字 NFKC 折叠 + casefold
    assert normalize_text("ＡＢＣ１２３") == "abc123"
    assert normalize_text("Already-USED") == "already-used"


def test_normalize_unifies_separators():
    assert normalize_text("a\\b\\c.mp4") == "a/b/c.mp4"


def test_normalize_case_sensitive_keeps_case():
    assert normalize_text("MiXeD", case_sensitive=True) == "MiXeD"


# ============================ pattern 校验 ============================


def test_validate_pattern_rejects_empty_and_whitespace():
    for bad in ("", "   "):
        with pytest.raises(RuleValidationError):
            validate_pattern(bad)


def test_validate_pattern_rejects_too_long():
    with pytest.raises(RuleValidationError):
        validate_pattern("x" * 257)


def test_validate_pattern_rejects_traversal_and_nul():
    with pytest.raises(RuleValidationError):
        validate_pattern("a/../b")
    with pytest.raises(RuleValidationError):
        validate_pattern("bad\x00name")


def test_validate_rule_config_whitelists():
    with pytest.raises(RuleValidationError):
        validate_rule_config("regex", "equals", "x")
    with pytest.raises(RuleValidationError):
        validate_rule_config("filename", "matches_regex", "x")
    assert validate_rule_config("filename", "equals", " 已使用 ") == "已使用"
    # 白名单本身冻结：4 算子 5 目标
    assert len(MATCH_OPERATORS) == 4
    assert len(MATCH_TARGETS) == 5


def test_regex_metacharacters_are_literal():
    # 正则元字符按字面匹配——".*" 不做通配
    spec = _spec(
        match_target="filename",
        match_operator="contains",
        normalized_pattern=normalize_text(".*"),
    )
    assert match_rule("dir/abc.mp4", spec) == []
    assert len(match_rule("dir/a.*b.mp4", spec)) == 1


# ============================ 各 target 提取 ============================


def test_directory_segment_matches_any_level():
    spec = _spec(normalized_pattern=normalize_text("已使用"))
    hits = match_rule("产品A/已使用/clip.mp4", spec)
    assert len(hits) == 1
    assert hits[0].matched_component == "已使用"
    assert hits[0].evidence_type == "directory_marker"
    # 深层也命中
    assert len(match_rule("x/y/已使用/z/clip.mp4", spec)) == 1


def test_directory_segment_does_not_match_filename():
    spec = _spec(normalized_pattern=normalize_text("已使用"))
    assert match_rule("dir/已使用", spec) == []  # 最后一段是文件名


def test_filename_and_stem_and_extension():
    fn = _spec(match_target="filename", match_operator="ends_with",
               normalized_pattern=normalize_text("_used.mp4"))
    assert len(match_rule("a/b/clip_used.mp4", fn)) == 1

    stem = _spec(match_target="filename_stem", match_operator="ends_with",
                 normalized_pattern=normalize_text("_已用"))
    assert len(match_rule("a/clip_已用.mp4", stem)) == 1
    assert match_rule("a/clip_已用x.mp4", stem) == []

    ext = _spec(match_target="extension", match_operator="equals",
                normalized_pattern=normalize_text("mp4"))
    assert len(match_rule("a/clip.MP4", ext)) == 1  # casefold 后命中
    assert match_rule("a/clip", ext) == []  # 无扩展名


def test_relative_path_contains():
    spec = _spec(match_target="relative_path", match_operator="contains",
                 normalized_pattern=normalize_text("已使用/"))
    assert len(match_rule("产品/已使用/clip.mp4", spec)) == 1


# ============================ 算子 ============================


def test_operators_semantics():
    base = dict(match_target="filename", normalized_pattern=normalize_text("used"))
    eq = _spec(match_operator="equals", **base)
    ct = _spec(match_operator="contains", **base)
    sw = _spec(match_operator="starts_with", **base)
    ew = _spec(match_operator="ends_with", **base)
    path = "d/used"
    assert len(match_rule(path, eq)) == 1
    assert len(match_rule("d/xusedx", ct)) == 1 and match_rule("d/xusedx", eq) == []
    assert len(match_rule("d/usedx", sw)) == 1 and match_rule("d/xused", sw) == []
    assert len(match_rule("d/xused", ew)) == 1 and match_rule("d/usedx", ew) == []


def test_case_sensitive_mode():
    spec = _spec(
        match_target="filename",
        normalized_pattern=normalize_text("USED", case_sensitive=True),
        case_sensitive=True,
    )
    assert match_rule("d/used", spec) == []
    assert len(match_rule("d/USED", spec)) == 1


def test_fullwidth_marker_matches_halfwidth_pattern():
    # 全角括号/字母目录名 NFKC 后与半角 pattern 一致
    spec = _spec(normalized_pattern=normalize_text("(used)"))
    assert len(match_rule("a/（used）/f.mp4", spec)) == 1


# ============================ 去重与 key ============================


def test_same_component_deduped_within_path():
    spec = _spec(normalized_pattern=normalize_text("已使用"))
    hits = match_rule("已使用/子目录/已使用/clip.mp4", spec)
    assert len(hits) == 1  # 同一片段值只算一次


def _hash(**kw) -> str:
    base = dict(
        rule_id=1, match_target="directory_segment", match_operator="equals",
        normalized_pattern="已使用", case_sensitive=False, source_directory_id=None,
        include_present_locations=True, include_missing_locations=True,
        include_historical_locations=True,
    )
    base.update(kw)
    return compute_snapshot_hash(**base)


def test_snapshot_hash_semantic_fields_only():
    h = _hash()
    assert len(h) == 64
    assert h == _hash()  # 排序稳定、可重现
    # 任一语义字段变化 → hash 变
    assert h != _hash(rule_id=2)
    assert h != _hash(match_operator="contains")
    assert h != _hash(normalized_pattern="其他")
    assert h != _hash(case_sensitive=True)
    assert h != _hash(source_directory_id=3)
    assert h != _hash(include_historical_locations=False)
    # 语义改回等价 → hash 复原（幂等回到原证据）
    assert _hash(normalized_pattern="x") != h
    assert _hash() == h


def test_frozen_rule_from_snapshot_validates():
    snap = {
        "rule_id": 1, "rule_version": 2, "match_target": "directory_segment",
        "match_operator": "equals", "normalized_pattern": "已使用",
        "case_sensitive": False, "source_directory_id": None,
        "include_present_locations": True, "include_missing_locations": True,
        "include_historical_locations": False, "snapshot_hash": _hash(
            include_historical_locations=False),
    }
    fr = frozen_rule_from_snapshot(snap)
    assert fr.rule_version == 2
    assert fr.location_statuses() == {"present", "missing"}
    assert fr.spec.normalized_pattern == "已使用"
    # 缺字段 → 校验错误
    bad = dict(snap)
    del bad["snapshot_hash"]
    with pytest.raises(RuleValidationError):
        frozen_rule_from_snapshot(bad)
    # hash 与语义字段不符（篡改/漂移）→ 校验错误
    tampered = dict(snap)
    tampered["normalized_pattern"] = "其他"
    with pytest.raises(RuleValidationError):
        frozen_rule_from_snapshot(tampered)


def test_evidence_key_stable_and_distinct():
    h1, h2 = _hash(), _hash(rule_id=2)
    k1 = compute_evidence_key(h1, 10, "directory_segment", "已使用")
    assert k1 == compute_evidence_key(h1, 10, "directory_segment", "已使用")
    assert len(k1) == 64
    assert k1 != compute_evidence_key(h2, 10, "directory_segment", "已使用")  # 语义/规则不同
    assert k1 != compute_evidence_key(h1, 11, "directory_segment", "已使用")  # 素材不同
    assert k1 != compute_evidence_key(h1, 10, "filename", "已使用")  # target 不同


def test_evidence_type_mapping():
    assert evidence_type_for("directory_segment") == "directory_marker"
    for t in ("filename", "filename_stem", "extension", "relative_path"):
        assert evidence_type_for(t) == "filename_marker"
