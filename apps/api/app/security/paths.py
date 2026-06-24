"""把共享路径安全校验绑定到应用配置的白名单根。"""

from __future__ import annotations

from clipmind_shared.security import resolve_and_validate_root

from app.config import get_settings


def validate_mount_path(mount_path: str) -> str:
    """校验 mount_path 位于白名单根之下，返回 realpath。

    Raises:
        clipmind_shared.security.PathNotAllowed: 不在白名单根之下。
    """
    settings = get_settings()
    return resolve_and_validate_root(mount_path, settings.allowed_roots_list)
