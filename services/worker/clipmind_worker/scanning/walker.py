"""目录遍历：递归发现支持的视频文件，做扩展名/排除过滤与软链逃逸防护。

安全：
- 不跟随软链目录（os.walk followlinks=False）。
- 每个文件用 safe_join_within_root 解析 realpath 并校验仍在根目录内，
  软链逃逸到根外的文件直接跳过。
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterator

from clipmind_shared.security import PathTraversal, safe_join_within_root


def _extension(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    return ext.lstrip(".").lower()


def _matches_exclude(rel_posix: str, patterns: list[str]) -> bool:
    base = rel_posix.rsplit("/", 1)[-1]
    return any(
        fnmatch.fnmatch(rel_posix, pat) or fnmatch.fnmatch(base, pat) for pat in patterns
    )


def iter_video_files(
    root_real: str,
    *,
    recursive: bool,
    include_extensions: list[str],
    exclude_patterns: list[str] | None = None,
) -> Iterator[tuple[str, str]]:
    """生成 (绝对真实路径, 原始相对路径) 二元组。"""
    include = {e.lower().lstrip(".") for e in include_extensions}
    excludes = list(exclude_patterns or [])

    if recursive:
        walker = os.walk(root_real, followlinks=False)
    else:
        top_files = [
            entry.name
            for entry in os.scandir(root_real)
            if not entry.is_dir(follow_symlinks=False)
        ]
        walker = iter([(root_real, [], top_files)])

    for dirpath, _dirnames, filenames in walker:
        for filename in filenames:
            if _extension(filename) not in include:
                continue
            abs_path = os.path.join(dirpath, filename)
            rel = os.path.relpath(abs_path, root_real)
            rel_posix = rel.replace("\\", "/")
            if _matches_exclude(rel_posix, excludes):
                continue
            try:
                real_abs = safe_join_within_root(root_real, rel)
            except PathTraversal:
                # 软链逃逸到根目录外，跳过
                continue
            if not os.path.isfile(real_abs):
                continue
            yield real_abs, rel
