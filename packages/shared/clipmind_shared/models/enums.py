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


# ============================================================
# PR-02 拆镜头 / 派生文件相关枚举
# ============================================================


class ShotStatus(StrEnum):
    """Shot.status —— 单个镜头的派生状态。

    只有 READY 的镜头才对外可见、可预览/下载；其余为过程态或失败态，
    由下次分析在启动时回收。
    """

    PENDING = "pending"        # 已落库，派生文件尚未就绪
    PROCESSING = "processing"  # 文件生成/搬运中（对外隐藏）
    READY = "ready"            # 派生文件齐备，可对外
    FAILED = "failed"          # 该镜头派生失败


class MediaRunStatus(StrEnum):
    """MediaProcessingRun.status —— 单次镜头分析运行的状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExportStatus(StrEnum):
    """Export.status —— 单次片段导出的状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# 视为"活动中"的镜头分析运行状态（用于部分唯一索引与并发判断）
ACTIVE_MEDIA_RUN_STATUSES: tuple[MediaRunStatus, ...] = (
    MediaRunStatus.QUEUED,
    MediaRunStatus.RUNNING,
)

# MediaProcessingRun.current_step 的取值（仅作进度展示，存为字符串而非枚举类型）
STEP_PROBING = "probing"
STEP_DETECTING = "detecting"
STEP_DERIVING = "deriving"
STEP_FINALIZING = "finalizing"


# ============================================================
# PR-03A AI 分析相关枚举
# ============================================================


class AIRunStatus(StrEnum):
    """AIAnalysisRun.status —— 素材级 AI 分析运行的状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"      # 运行完成，但部分镜头失败/降级
    FAILED = "failed"
    CANCELLED = "cancelled"


class AIShotAnalysisStatus(StrEnum):
    """AIShotAnalysis.status —— 单镜头 AI 分析当前结果的状态。"""

    PENDING = "pending"
    COMPLETED = "completed"
    DEGRADED = "degraded"    # 能力不足（如无图）降级，未做完整视觉分析
    FAILED = "failed"
    SKIPPED = "skipped"      # 输入指纹命中缓存，跳过（不重复计费）


class AICallStatus(StrEnum):
    """AICallLog.status —— 单次外部 provider 调用的结果。"""

    SUCCESS = "success"
    RETRY = "retry"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    DEGRADED = "degraded"


# 视为"活动中"的 AI 分析运行状态（用于部分唯一索引与并发判断）
ACTIVE_AI_RUN_STATUSES: tuple[AIRunStatus, ...] = (
    AIRunStatus.QUEUED,
    AIRunStatus.RUNNING,
)
