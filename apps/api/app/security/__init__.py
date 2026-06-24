"""API 层路径安全封装（绑定应用配置的白名单根）。"""

from app.security.paths import validate_mount_path

__all__ = ["validate_mount_path"]
