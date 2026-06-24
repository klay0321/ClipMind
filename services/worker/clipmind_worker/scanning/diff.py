"""分层变化判定（纯函数，便于单元测试）。

第一层：用 size + mtime 判断是否未变（不读文件内容、不 probe）。
仅当新增 / size 或 mtime 变化 / 重新出现时，才需要计算 quick_hash + FFprobe。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

# mtime 比较容差（秒），规避亚秒精度/驱动截断带来的误判
MTIME_TOLERANCE_SECONDS = 1.0


class FileAction(StrEnum):
    NEW = "new"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    REAPPEARED = "reappeared"  # 原为 source_missing，现重新出现


def decide_action(
    *,
    exists: bool,
    is_source_missing: bool,
    stored_size: int | None,
    stored_mtime: datetime | None,
    new_size: int,
    new_mtime: datetime,
) -> FileAction:
    if not exists:
        return FileAction.NEW
    if is_source_missing:
        return FileAction.REAPPEARED
    if stored_size != new_size:
        return FileAction.MODIFIED
    if stored_mtime is None:
        return FileAction.MODIFIED
    if abs((stored_mtime - new_mtime).total_seconds()) >= MTIME_TOLERANCE_SECONDS:
        return FileAction.MODIFIED
    return FileAction.UNCHANGED


def needs_probe(action: FileAction) -> bool:
    """是否需要计算 quick_hash 并运行 FFprobe。"""
    return action != FileAction.UNCHANGED
