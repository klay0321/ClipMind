"""路径安全：白名单根校验、目录穿越与软链逃逸防护。"""

from clipmind_shared.security.paths import (
    PathNotAllowed,
    PathSecurityError,
    PathTraversal,
    is_within,
    resolve_and_validate_root,
    safe_join_within_root,
)

__all__ = [
    "PathSecurityError",
    "PathNotAllowed",
    "PathTraversal",
    "is_within",
    "resolve_and_validate_root",
    "safe_join_within_root",
]
