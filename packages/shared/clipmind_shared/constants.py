"""跨服务共享的常量：支持格式、Celery 任务名/队列名、扫描参数。"""

from __future__ import annotations

# 支持的视频扩展名（小写，不含点）
SUPPORTED_VIDEO_EXTENSIONS: tuple[str, ...] = ("mp4", "mov", "mkv", "avi", "webm")

# ----- Celery 任务名（稳定字符串，API 按名入队，避免 import worker 代码）-----
TASK_SCAN_SOURCE_DIRECTORY = "clipmind.scan_source_directory"
TASK_RESCAN_ASSET = "clipmind.rescan_asset"
# PR-02 拆镜头 / 派生文件
TASK_ANALYZE_SHOTS = "clipmind.analyze_shots"
TASK_EXPORT_SHOT_CLIP = "clipmind.export_shot_clip"
# 素材海报（FFmpeg 抽一帧，未分析素材也能有真实封面）
TASK_GENERATE_ASSET_POSTER = "clipmind.generate_asset_poster"

# ----- Celery 队列名 -----
# PR-01 worker 只消费 default + scan；media/ai/export 为后续 PR 预留（不运行）
QUEUE_DEFAULT = "default"
QUEUE_SCAN = "scan"
QUEUE_MEDIA = "media"      # PR-02 拆镜头/派生文件
QUEUE_AI = "ai"           # PR-03 AI 理解
QUEUE_EXPORT = "export"   # PR-05 导出

ALL_QUEUES: tuple[str, ...] = (
    QUEUE_DEFAULT,
    QUEUE_SCAN,
    QUEUE_MEDIA,
    QUEUE_AI,
    QUEUE_EXPORT,
)

# 扫描/探测逻辑版本：解析逻辑变更时递增，便于后续按版本重算
METADATA_VERSION = 1

# quick_hash 读取的头尾块大小（字节）
QUICK_HASH_CHUNK = 64 * 1024

# 扫描时批量提交阈值（每处理 N 个文件提交一次）
SCAN_COMMIT_BATCH = 200

# error_message 最大保存长度
ERROR_MESSAGE_MAX_LEN = 2000
