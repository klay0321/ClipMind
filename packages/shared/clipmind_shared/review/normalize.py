"""名称标准化（产品/别名/标签候选匹配前的归一）。

处理：全角半角(NFKC)、大小写、首尾与多余空格、连字符、常见标点。保留 CJK 与字母数字。
"""

from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+", re.UNICODE)


def normalize_name(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)  # 全角 → 半角等
    s = s.strip().lower()
    s = s.replace("-", " ").replace("_", " ")  # 连字符/下划线 → 空格
    s = _PUNCT.sub(" ", s)                      # 其它标点 → 空格（保留 \w 含 CJK）
    s = _SPACE.sub(" ", s).strip()
    return s
