"""相对路径规范化工具。

数据库存储两份路径：
- relative_path：扫描得到的原始相对路径（保留展示）。
- normalized_relative_path：规范化形式（POSIX 分隔符 + Unicode NFC），
  用于唯一约束与查找，避免 Windows 反斜杠 / 大小写以外的 Unicode 形态差异。
"""

from __future__ import annotations

import posixpath
import unicodedata


def normalize_relative_path(relative_path: str) -> str:
    """把相对路径规范化为稳定形式用于唯一约束/查找。

    - 反斜杠转正斜杠
    - 去除首尾多余的斜杠
    - 折叠 . 与多余分隔符
    - Unicode NFC 规范化
    """
    p = relative_path.replace("\\", "/").strip("/")
    # posixpath.normpath 折叠 "a//b"、"a/./b"；保留普通相对路径
    p = posixpath.normpath(p) if p else ""
    if p == ".":
        p = ""
    return unicodedata.normalize("NFC", p)
