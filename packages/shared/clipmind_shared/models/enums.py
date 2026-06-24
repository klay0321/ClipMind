"""领域枚举。

枚举一次性建全（前向兼容），PR-01 只使用其中部分值；
PG 枚举后续追加 value 较麻烦，故先定义完整集合。
"""

from __future__ import annotations

from enum import StrEnum


class AssetStatus(StrEnum):
    """素材处理状态。"""

    # ---- PR-01 实际使用 ----
    DISCOVERED = "discovered"        # 已发现，待探测
    INDEXED = "indexed"              # FFprobe 成功，已索引
    ERROR = "error"                  # 探测失败
    SOURCE_MISSING = "source_missing"  # 源文件缺失

    # ---- 后续 PR 预留 ----
    PENDING = "pending"
    PROCESSING = "processing"
    SHOT_SPLIT = "shot_split"
    AI_ANALYZING = "ai_analyzing"
    PENDING_REVIEW = "pending_review"
    SEARCHABLE = "searchable"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ScanStatus(StrEnum):
    """SourceDirectory.scan_status —— 目录维度的扫描状态。"""

    NEVER_SCANNED = "never_scanned"
    QUEUED = "queued"
    SCANNING = "scanning"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanRunStatus(StrEnum):
    """ScanRun.status —— 单次扫描运行的状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 视为"活动中"的扫描运行状态（用于部分唯一索引与并发判断）
ACTIVE_SCAN_RUN_STATUSES: tuple[ScanRunStatus, ...] = (
    ScanRunStatus.QUEUED,
    ScanRunStatus.RUNNING,
)
