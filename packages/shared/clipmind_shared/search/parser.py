"""Gate B：查询解析器（确定性规则解析 + Fake + 工厂）。

三种实现（MiMo 见 ``parser_mimo.py``）：

- ``RuleBasedQueryParser``：完全确定性的规则解析，是所有 LLM 解析失败时的**降级兜底**；
  也是无 AI 配置时的默认解析器。
- ``FakeQueryParser``：确定性，CI/测试用于替身 LLM（标 ``parser_provider="fake"``），
  复用规则解析的抽取逻辑，输出稳定可断言。
- 工厂 ``get_query_parser``：按名装配 rulebased / fake / mimo。

规则解析只做**保守、可解释**的抽取（画幅、时长、否定、确认要求、关键词），不臆测产品/场景的
受控词表（那由 LLM 或结构化召回承担）。语义全文始终保留在 ``semantic_text``。
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from clipmind_shared.review.normalize import normalize_name
from clipmind_shared.search.query import AspectRatio, ParsedSearchQuery, ParserStatus


@runtime_checkable
class SearchQueryParser(Protocol):
    """查询解析器统一契约（同步；API 在 threadpool 中调用以不阻塞事件循环）。"""

    name: str

    def parse(self, query: str) -> ParsedSearchQuery: ...


# ---- 规则词表（确定性、可审计）----
# 画幅关键词 → 受控画幅
_ASPECT_KEYWORDS: tuple[tuple[str, AspectRatio], ...] = (
    ("16:9", AspectRatio.LANDSCAPE_16_9),
    ("9:16", AspectRatio.PORTRAIT_9_16),
    ("1:1", AspectRatio.SQUARE_1_1),
    ("4:3", AspectRatio.STANDARD_4_3),
    ("3:4", AspectRatio.PORTRAIT_3_4),
    ("21:9", AspectRatio.CINEMA_21_9),
    ("竖屏", AspectRatio.PORTRAIT_9_16),
    ("竖版", AspectRatio.PORTRAIT_9_16),
    ("竖屏视频", AspectRatio.PORTRAIT_9_16),
    ("vertical", AspectRatio.PORTRAIT_9_16),
    ("横屏", AspectRatio.LANDSCAPE_16_9),
    ("横版", AspectRatio.LANDSCAPE_16_9),
    ("landscape", AspectRatio.LANDSCAPE_16_9),
    ("方形", AspectRatio.SQUARE_1_1),
    ("正方形", AspectRatio.SQUARE_1_1),
    ("square", AspectRatio.SQUARE_1_1),
)

# 否定线索（其后/其前的词被视为负向）
_NEG_CUES = (
    "不要",
    "不含",
    "不带",
    "没有",
    "排除",
    "去掉",
    "除去",
    "避免",
    "不能有",
    "without",
    "exclude",
    "no ",
    "not ",
)

# 已知风险关键词（仅用于把否定词归入 excluded_risks；保守集合）
_RISK_KEYWORDS = ("竞品", "水印", "隐私", "违规", "风险", "logo", "商标", "竞争对手")

# 确认要求线索
_CONFIRMED_CUES = ("已确认", "人工确认", "审核通过", "confirmed", "已审核")

# 极短/停用词（不进 positive_terms）
_STOPWORDS = {
    "的",
    "了",
    "和",
    "与",
    "或",
    "镜头",
    "视频",
    "画面",
    "素材",
    "a",
    "an",
    "the",
    "of",
    "with",
    "and",
    "or",
    "video",
    "shot",
    "clip",
}

# 时长模式：返回 (min, max) 增量
_DUR_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(\d+(?:\.\d+)?)\s*秒以内", "max"),
    (r"不超过\s*(\d+(?:\.\d+)?)\s*秒", "max"),
    (r"少于\s*(\d+(?:\.\d+)?)\s*秒", "max"),
    (r"小于\s*(\d+(?:\.\d+)?)\s*秒", "max"),
    (r"超过\s*(\d+(?:\.\d+)?)\s*秒", "min"),
    (r"至少\s*(\d+(?:\.\d+)?)\s*秒", "min"),
    (r"大于\s*(\d+(?:\.\d+)?)\s*秒", "min"),
    (r"长于\s*(\d+(?:\.\d+)?)\s*秒", "min"),
    (r"under\s*(\d+(?:\.\d+)?)\s*s\b", "max"),
    (r"<\s*(\d+(?:\.\d+)?)\s*s\b", "max"),
    (r">\s*(\d+(?:\.\d+)?)\s*s\b", "min"),
    (r"over\s*(\d+(?:\.\d+)?)\s*s\b", "min"),
)
_DUR_MIN_PATTERNS = (
    (r"(\d+(?:\.\d+)?)\s*分钟以内", 60.0, "max"),
    (r"不超过\s*(\d+(?:\.\d+)?)\s*分钟", 60.0, "max"),
    (r"超过\s*(\d+(?:\.\d+)?)\s*分钟", 60.0, "min"),
    (r"至少\s*(\d+(?:\.\d+)?)\s*分钟", 60.0, "min"),
)


def _extract_aspects(text: str) -> list[AspectRatio]:
    low = text.lower()
    out: list[AspectRatio] = []
    for kw, ar in _ASPECT_KEYWORDS:
        if kw.lower() in low and ar not in out:
            out.append(ar)
    return out


def _extract_durations(text: str) -> tuple[float | None, float | None]:
    low = text.lower()
    dmin: float | None = None
    dmax: float | None = None
    for pat, factor, kind in _DUR_MIN_PATTERNS:
        m = re.search(pat, low)
        if m:
            val = float(m.group(1)) * factor
            if kind == "max":
                dmax = val if dmax is None else min(dmax, val)
            else:
                dmin = val if dmin is None else max(dmin, val)
    for pat, kind in _DUR_PATTERNS:
        m = re.search(pat, low)
        if m:
            val = float(m.group(1))
            if kind == "max":
                dmax = val if dmax is None else min(dmax, val)
            else:
                dmin = val if dmin is None else max(dmin, val)
    return dmin, dmax


def _extract_negations(text: str) -> list[str]:
    """抽取否定段后的词组（保守：取线索后到下一个标点/空白边界的短语）。"""
    negs: list[str] = []
    for cue in _NEG_CUES:
        idx = 0
        low = text.lower()
        cue_l = cue.lower()
        while True:
            pos = low.find(cue_l, idx)
            if pos < 0:
                break
            start = pos + len(cue_l)
            # 去掉线索后的前导分隔符，再取一段（到标点/连接词/结尾）
            tail = re.sub(r"^[\s，,。.；;、:：]+", "", text[start : start + 24])
            m = re.split(r"[，,。.；;、\s]|的|和|与|或", tail, maxsplit=1)
            term = (m[0] if m else "").strip()
            if term:
                negs.append(term)
            idx = start
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for n in negs:
        k = n.lower()
        if k not in seen:
            seen.add(k)
            out.append(n)
    return out


# 否定线索词本身（归一后）不应作为正向关键词
_CUE_TOKENS = {c.strip().lower() for c in _NEG_CUES} | {"不要", "排除", "去掉"}


def _tokenize_positive(normalized: str, negatives: list[str]) -> list[str]:
    """正向关键词：归一文本按空白切分，去停用词/否定词/线索词/极短。"""
    neg_l = {n.lower() for n in negatives}
    out: list[str] = []
    seen: set[str] = set()
    for tok in normalized.split():
        t = tok.strip()
        if not t or t in _STOPWORDS or t.lower() in neg_l or t.lower() in _CUE_TOKENS:
            continue
        # 纯 ASCII 单字符（如 'a'）跳过；CJK 单字保留（信息量更高）
        if len(t) == 1 and t.isascii():
            continue
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def _rule_extract(query: str, *, provider: str, model: str) -> ParsedSearchQuery:
    """规则抽取核心（RuleBased 与 Fake 共用）。"""
    original = (query or "").strip()
    normalized = normalize_name(original)
    aspects = _extract_aspects(original)
    dmin, dmax = _extract_durations(original)
    negatives = _extract_negations(original)
    excluded_risks = [n for n in negatives if any(rk in n for rk in _RISK_KEYWORDS)]
    confirmed = any(c in original.lower() for c in _CONFIRMED_CUES)
    positives = _tokenize_positive(normalized, negatives)

    return ParsedSearchQuery(
        original_query=original,
        normalized_query=normalized,
        positive_terms=positives,
        negative_terms=negatives,
        excluded_risks=excluded_risks,
        min_duration=dmin,
        max_duration=dmax,
        aspect_ratios=aspects,
        confirmed_only=confirmed,
        semantic_text=original or normalized,
        parser_provider=provider,
        parser_model=model,
        parser_status=ParserStatus.OK,
    )


class RuleBasedQueryParser:
    """确定性规则解析（降级兜底 / 无 AI 时默认）。"""

    name = "rulebased"

    def parse(self, query: str) -> ParsedSearchQuery:
        return _rule_extract(query, provider="rulebased", model="rulebased-v1")


class FakeQueryParser:
    """确定性替身解析（CI/测试模拟 LLM 路径，复用规则抽取）。"""

    name = "fake"

    def parse(self, query: str) -> ParsedSearchQuery:
        return _rule_extract(query, provider="fake", model="fake-parser-1")


def get_query_parser(
    name: str | None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 8.0,
    api_key_header: str = "",
) -> SearchQueryParser:
    """按名装配查询解析器。``mimo`` 惰性导入 httpx。未知/空 → 规则解析。"""
    key = (name or "").strip().lower()
    if key == "fake":
        return FakeQueryParser()
    if key == "mimo":
        from clipmind_shared.search.parser_mimo import MiMoQueryParser

        return MiMoQueryParser(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            api_key_header=api_key_header,
        )
    return RuleBasedQueryParser()
