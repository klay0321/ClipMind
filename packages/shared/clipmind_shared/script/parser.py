"""PR-05 Gate A：脚本拆段解析器（确定性规则拆段 + Fake + 工厂）。

三种实现（MiMo 见 ``parser_mimo.py``）：

- ``RuleBasedScriptParser``：完全确定性的规则拆段，是所有 LLM 解析失败时的**降级兜底**，
  也是无 AI 配置时的默认解析器。规则解析只做**保守、可解释**的抽取（按标点/空行拆段、
  时长、否定、风险排除），不臆测产品/场景/动作的受控词表（那由 LLM 承担）；画面需求直接
  取段落原文。
- ``FakeScriptParser``：确定性，CI/测试用替身 LLM（标 ``parser_provider="fake"``），复用规则
  拆段逻辑，输出稳定可断言，**绝不联网**。
- 工厂 ``get_script_parser``：按名装配 rulebased / fake / mimo。

与 Gate B 查询解析器的设计与降级语义保持一致。
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from clipmind_shared.models.enums import ScriptParseStatus
from clipmind_shared.script.schema import (
    MAX_SEGMENTS,
    ParsedScript,
    ParsedScriptSegment,
)
from clipmind_shared.search.parser import (
    _RISK_KEYWORDS,
    _extract_durations,
    _extract_negations,
)


@runtime_checkable
class ScriptParser(Protocol):
    """脚本解析器统一契约（同步；API 在 threadpool 中调用以不阻塞事件循环）。"""

    name: str

    def parse(self, text: str) -> ParsedScript: ...


# 句末标点（中英）；用于在过长段落内进一步切句
_SENTENCE_END = re.compile(r"[。！？!?；;]+")
# 段落分隔：一个或多个空行
_PARA_SPLIT = re.compile(r"\n\s*\n+")
# 是否含实义内容（任意 \w：字母/数字/CJK）；用于剔除纯标点/纯空白段
_HAS_CONTENT = re.compile(r"\w", re.UNICODE)
# split 安全上限（远高于 MAX_SEGMENTS，保证 >MAX_SEGMENTS 时 ParsedScript 能告警截断，
# 同时给定长输入一个有界上界，防御异常巨量段落）
_SPLIT_SAFETY_CAP = MAX_SEGMENTS * 4


def split_segments(text: str) -> list[str]:
    """把脚本拆为有序段落（确定性）。

    策略：先按空行分段；每段若仍较长（含多句），按句末标点细分；保序、剔除纯标点/纯空白与
    相邻完全重复。返回上限 ``_SPLIT_SAFETY_CAP``；真正的 ``MAX_SEGMENTS`` 截断与告警由
    ``ParsedScript`` 承担（>MAX_SEGMENTS 时会追加 truncate 警告）。
    """
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return []
    out: list[str] = []
    for para in _PARA_SPLIT.split(raw):
        para = para.strip()
        if not para:
            continue
        # 段落内若只有一行且不长，整体作为一段；否则按行 + 句末标点细分
        units: list[str] = []
        for line in para.split("\n"):
            line = line.strip()
            if not line:
                continue
            # 句末标点切句，保留标点
            parts = _SENTENCE_END.split(line)
            seps = _SENTENCE_END.findall(line)
            rebuilt: list[str] = []
            for i, p in enumerate(parts):
                p = p.strip()
                if not p:
                    continue
                rebuilt.append(p + (seps[i] if i < len(seps) else ""))
            units.extend(rebuilt if rebuilt else ([line] if line else []))
        for u in units:
            u = u.strip()
            # 仅保留含实义内容的段，剔除纯标点/纯空白；去相邻完全重复
            if u and _HAS_CONTENT.search(u) and (not out or out[-1] != u):
                out.append(u)
            if len(out) >= _SPLIT_SAFETY_CAP:
                return out
    return out


def _segment_from_text(idx: int, seg_text: str) -> ParsedScriptSegment:
    """规则抽取单段结构化需求（保守、可解释）。"""
    dmin, dmax = _extract_durations(seg_text)
    negatives = _extract_negations(seg_text)
    excluded_risks = [n for n in negatives if any(rk in n for rk in _RISK_KEYWORDS)]
    return ParsedScriptSegment(
        order_index=idx,
        text=seg_text,
        visual_requirement=seg_text,
        target_duration_min=dmin,
        target_duration_max=dmax,
        negative_terms=negatives,
        excluded_risks=excluded_risks,
    )


def _rule_parse(text: str, *, provider: str, model: str) -> ParsedScript:
    """规则拆段核心（RuleBased 与 Fake 共用）。"""
    segments = [
        _segment_from_text(i, s) for i, s in enumerate(split_segments(text))
    ]
    return ParsedScript(
        segments=segments,
        parser_provider=provider,
        parser_model=model,
        parser_status=ScriptParseStatus.OK,
    )


class RuleBasedScriptParser:
    """确定性规则拆段（降级兜底 / 无 AI 时默认）。"""

    name = "rulebased"

    def parse(self, text: str) -> ParsedScript:
        return _rule_parse(text, provider="rulebased", model="rulebased-script-v1")


class FakeScriptParser:
    """确定性替身解析（CI/测试模拟 LLM 路径，复用规则拆段，绝不联网）。"""

    name = "fake"

    def parse(self, text: str) -> ParsedScript:
        return _rule_parse(text, provider="fake", model="fake-script-1")


def get_script_parser(
    name: str | None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 12.0,
    api_key_header: str = "",
) -> ScriptParser:
    """按名装配脚本解析器。``mimo`` 惰性导入 httpx。未知/空 → 规则解析。"""
    key = (name or "").strip().lower()
    if key == "fake":
        return FakeScriptParser()
    if key == "mimo":
        from clipmind_shared.script.parser_mimo import MiMoScriptParser

        return MiMoScriptParser(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            api_key_header=api_key_header,
        )
    return RuleBasedScriptParser()
