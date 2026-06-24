"""路径安全校验（最高优先级安全约束）。

防御目标：
- 配置的素材目录必须位于允许的白名单根之下（防止读取任意宿主机路径）。
- 遍历时拼接的子路径不得跳出根目录（防止 `..` 目录穿越与软链逃逸）。

所有校验基于 `os.path.realpath`（解析软链与 `..`）后做前缀包含判断。
"""

from __future__ import annotations

import os
from collections.abc import Iterable


class PathSecurityError(Exception):
    """路径安全相关错误基类。"""


class PathNotAllowed(PathSecurityError):
    """目标路径不在任何白名单根之下。"""


class PathTraversal(PathSecurityError):
    """目标路径试图跳出根目录（目录穿越/软链逃逸）。"""


def is_within(child_real: str, root_real: str) -> bool:
    """判断 child_real 是否等于 root_real 或位于其下（均应为 realpath 结果）。"""
    if child_real == root_real:
        return True
    return child_real.startswith(root_real + os.sep)


def resolve_and_validate_root(mount_path: str, allowed_roots: Iterable[str]) -> str:
    """校验 mount_path 位于某个白名单根之下，返回其 realpath。

    Raises:
        PathNotAllowed: 不在任何白名单根之下。
    """
    real = os.path.realpath(mount_path)
    for root in allowed_roots:
        root_real = os.path.realpath(root)
        if is_within(real, root_real):
            return real
    raise PathNotAllowed(f"路径不在允许的白名单根之下: {mount_path}")


def safe_join_within_root(root_real: str, *parts: str) -> str:
    """在 root_real 下安全拼接子路径并校验包含，返回 realpath。

    用于遍历时把发现的相对路径还原为绝对路径并确认未跳出根目录
    （防止符号链接指向根目录之外）。

    Raises:
        PathTraversal: 拼接结果跳出 root_real。
    """
    candidate = os.path.realpath(os.path.join(root_real, *parts))
    if not is_within(candidate, root_real):
        raise PathTraversal(f"路径跳出根目录: {os.path.join(*parts)}")
    return candidate
