"""目录扫描子模块：遍历、指纹、变化判定、字段填充。"""

from clipmind_worker.scanning.apply import apply_probe_to_asset, clear_probe_fields
from clipmind_worker.scanning.diff import FileAction, decide_action
from clipmind_worker.scanning.fingerprint import compute_quick_hash
from clipmind_worker.scanning.walker import iter_video_files

__all__ = [
    "iter_video_files",
    "compute_quick_hash",
    "FileAction",
    "decide_action",
    "apply_probe_to_asset",
    "clear_probe_fields",
]
