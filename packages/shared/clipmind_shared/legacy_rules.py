"""PR-C Gate B 历史路径规则匹配（纯函数，零 IO，docs/LEGACY_USAGE_EVIDENCE.md）。

安全设计：
- **不支持任意正则**——只有 equals/contains/starts_with/ends_with 四个字符串
  算子（无回溯引擎，无 ReDoS 面）；
- 输入只来源于 AssetLocation.relative_path（root 下安全相对路径），本模块
  不做任何文件系统访问；
- 归一化管线：Unicode NFKC → 分隔符统一 `/` →（大小写无关时）casefold；
- pattern 校验：非空、≤256、不含路径穿越成分（`..`）与 NUL；
- evidence_key = sha256(rule_id|asset_id|match_target|归一化匹配片段)：
  同规则 + 同 Asset + 同匹配事实唯一（幂等锚，不含 location id——
  同一事实出现在多个位置只算一条，观察数累加）。
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass

MATCH_TARGETS = ("directory_segment", "filename", "filename_stem", "extension", "relative_path")
MATCH_OPERATORS = ("equals", "contains", "starts_with", "ends_with")
PATTERN_MAX = 256
COMPONENT_MAX = 256


class RuleValidationError(ValueError):
    """规则配置非法（pattern/target/operator）。"""


def normalize_text(value: str, *, case_sensitive: bool = False) -> str:
    """NFKC 归一化 + 分隔符统一 + （默认）casefold。"""
    v = unicodedata.normalize("NFKC", value).replace("\\", "/")
    return v if case_sensitive else v.casefold()


def validate_pattern(pattern: str) -> str:
    """校验并返回 strip 后的原始 pattern（归一化形态另行计算）。"""
    p = (pattern or "").strip()
    if not p:
        raise RuleValidationError("pattern 不能为空")
    if len(p) > PATTERN_MAX:
        raise RuleValidationError(f"pattern 过长（≤{PATTERN_MAX}）")
    if "\x00" in p or ".." in p.replace("\\", "/").split("/"):
        raise RuleValidationError("pattern 不允许包含路径穿越成分")
    return p


def validate_rule_config(match_target: str, match_operator: str, pattern: str) -> str:
    if match_target not in MATCH_TARGETS:
        raise RuleValidationError(f"不支持的 match_target: {match_target}")
    if match_operator not in MATCH_OPERATORS:
        raise RuleValidationError(f"不支持的 match_operator: {match_operator}")
    return validate_pattern(pattern)


@dataclass(frozen=True)
class RuleSpec:
    """匹配用的规则快照（与 ORM 解耦，preview/import 共用）。"""

    rule_id: int
    match_target: str
    match_operator: str
    normalized_pattern: str
    case_sensitive: bool = False


@dataclass(frozen=True)
class MatchHit:
    rule_id: int
    match_target: str
    matched_component: str  # 归一化后的匹配片段（截断 ≤256）
    evidence_type: str      # directory_marker / filename_marker


def _extract_candidates(norm_path: str, target: str) -> list[str]:
    """按 target 从归一化相对路径提取待匹配对象列表。"""
    parts = [p for p in norm_path.split("/") if p]
    if not parts:
        return []
    filename = parts[-1]
    if target == "directory_segment":
        return parts[:-1]
    if target == "filename":
        return [filename]
    if target == "filename_stem":
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        return [stem]
    if target == "extension":
        return [filename.rsplit(".", 1)[1]] if "." in filename else []
    if target == "relative_path":
        return [norm_path]
    return []


def _op_match(value: str, op: str, pattern: str) -> bool:
    if op == "equals":
        return value == pattern
    if op == "contains":
        return pattern in value
    if op == "starts_with":
        return value.startswith(pattern)
    if op == "ends_with":
        return value.endswith(pattern)
    return False


def evidence_type_for(target: str) -> str:
    return "directory_marker" if target == "directory_segment" else "filename_marker"


def match_rule(relative_path: str, rule: RuleSpec) -> list[MatchHit]:
    """对单条相对路径应用单条规则，返回命中列表（同一片段值去重）。"""
    norm = normalize_text(relative_path, case_sensitive=rule.case_sensitive)
    hits: list[MatchHit] = []
    seen: set[str] = set()
    for candidate in _extract_candidates(norm, rule.match_target):
        if _op_match(candidate, rule.match_operator, rule.normalized_pattern):
            component = candidate[:COMPONENT_MAX]
            if component in seen:
                continue
            seen.add(component)
            hits.append(
                MatchHit(
                    rule_id=rule.rule_id,
                    match_target=rule.match_target,
                    matched_component=component,
                    evidence_type=evidence_type_for(rule.match_target),
                )
            )
    return hits


def compute_evidence_key(rule_id: int, asset_id: int, match_target: str, component: str) -> str:
    raw = f"{rule_id}|{asset_id}|{match_target}|{component}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
