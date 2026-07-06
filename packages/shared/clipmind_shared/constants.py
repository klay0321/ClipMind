"""跨服务共享的常量：支持格式、Celery 任务名/队列名、扫描参数。"""

from __future__ import annotations

# 支持的视频扩展名（小写，不含点）
SUPPORTED_VIDEO_EXTENSIONS: tuple[str, ...] = ("mp4", "mov", "mkv", "avi", "webm")
# PM：支持的图片扩展名（普通产品图等图片素材走 Asset 管线；media_kind=image，
# 无拆镜头/代理派生；ffprobe 对图片返回 video 流+宽高、duration 为空）
SUPPORTED_IMAGE_EXTENSIONS: tuple[str, ...] = ("jpg", "jpeg", "png", "webp")
SUPPORTED_MEDIA_EXTENSIONS: tuple[str, ...] = (
    SUPPORTED_VIDEO_EXTENSIONS + SUPPORTED_IMAGE_EXTENSIONS
)

# ----- PM 产品素材正式关系（product_media_link；人工确认=正式事实）-----
# 关系类型：primary 至多一个（DB 部分唯一），related 多条（多产品同框）
PRODUCT_LINK_ROLES: tuple[str, ...] = ("primary", "related")
# 关系来源（String+白名单，免迁移扩展）。候选（视觉/文件名/文本）只有经人工
# 确认才落库；visual_suggestion_confirmed 仅接受 local provider（fake 禁止）。
PRODUCT_LINK_ORIGINS: tuple[str, ...] = (
    "manual",
    "bulk_manual",
    "path_or_filename_confirmed",
    "visual_suggestion_confirmed",
    "text_suggestion_confirmed",
    "migration_or_legacy",
)

# ----- Celery 任务名（稳定字符串，API 按名入队，避免 import worker 代码）-----
TASK_SCAN_SOURCE_DIRECTORY = "clipmind.scan_source_directory"
TASK_RESCAN_ASSET = "clipmind.rescan_asset"
# AAP：beat 定时扫描全部源目录（scan 队列）
TASK_SCHEDULED_SCAN_ALL = "clipmind.scheduled_scan_all"
# PR-02 拆镜头 / 派生文件
TASK_ANALYZE_SHOTS = "clipmind.analyze_shots"
TASK_EXPORT_SHOT_CLIP = "clipmind.export_shot_clip"
# 素材海报（FFmpeg 抽一帧，未分析素材也能有真实封面）
TASK_GENERATE_ASSET_POSTER = "clipmind.generate_asset_poster"
# PR-03A AI 理解分析（ai 队列）
TASK_ANALYZE_ASSET_AI = "clipmind.analyze_asset_ai"
TASK_ANALYZE_SHOT_AI = "clipmind.analyze_shot_ai"
# PR-04 检索文档索引（search 队列）：单镜头/单素材重建 + sweeper 兜底 + 全量/失败回填
TASK_REBUILD_SHOT_SEARCH_DOC = "clipmind.rebuild_shot_search_doc"
TASK_REBUILD_ASSET_SEARCH_DOCS = "clipmind.rebuild_asset_search_docs"
TASK_SWEEP_SEARCH_DOCS = "clipmind.sweep_search_docs"
TASK_BACKFILL_SEARCH_DOCS = "clipmind.backfill_search_docs"
# PR-05 Gate B 脚本剪辑清单导出（export 队列）；PR-06B 起按 export_format 多格式输出
TASK_EXPORT_SCRIPT_CSV = "clipmind.export_script_csv"
# PR-06B 多镜头打包导出（media 队列：裁剪各 clip → 打包 ZIP）
TASK_EXPORT_BUNDLE = "clipmind.export_bundle"
# PR-C 分级指纹计算（scan 队列：顺序读 NAS，批量任务内部串行限并发）
TASK_FINGERPRINT_JOB = "clipmind.fingerprint_job"
# PR-C Gate B 历史证据导入（default 队列：只读 AssetLocation，零文件 IO）
TASK_LEGACY_IMPORT = "clipmind.legacy_usage_import"

# ----- Celery 队列名 -----
# PR-01 worker 只消费 default + scan；media/ai/export 为后续 PR 预留（不运行）
QUEUE_DEFAULT = "default"
QUEUE_SCAN = "scan"
QUEUE_MEDIA = "media"      # PR-02 拆镜头/派生文件
QUEUE_AI = "ai"           # PR-03 AI 理解
QUEUE_SEARCH = "search"   # PR-04 检索文档索引/嵌入
QUEUE_EXPORT = "export"   # PR-05 导出

ALL_QUEUES: tuple[str, ...] = (
    QUEUE_DEFAULT,
    QUEUE_SCAN,
    QUEUE_MEDIA,
    QUEUE_AI,
    QUEUE_SEARCH,
    QUEUE_EXPORT,
)

# 扫描/探测逻辑版本：解析逻辑变更时递增，便于后续按版本重算
METADATA_VERSION = 1

# AI 结构化输出 Schema 版本：Schema 变更时递增（参与输入指纹，便于按版本重算）
AI_SCHEMA_VERSION = 1

# PR-04 检索文档模板版本：检索文档拼装规则/字段集变更时递增（参与文档哈希，强制重嵌）
SEARCH_DOCUMENT_TEMPLATE_VERSION = 1

# PR-05 脚本拆段结构化 Schema 版本：段落结构化字段集变更时递增（存于 script_project）
SCRIPT_PARSE_SCHEMA_VERSION = 1

# PR-04 默认 Embedding 模型与**不可变 revision**（公开模型 commit，非敏感信息）。
# 单一事实来源：API/worker settings 默认引用此处；embedder 服务（不依赖本包）须保持同值，
# 由 test_revision_consistency 强制一致。换模型/维度/revision 须全量重嵌。
DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_EMBEDDING_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
DEFAULT_EMBEDDING_DIMENSION = 384

# quick_hash 读取的头尾块大小（字节）
QUICK_HASH_CHUNK = 64 * 1024

# 扫描时批量提交阈值（每处理 N 个文件提交一次）
SCAN_COMMIT_BATCH = 200

# error_message 最大保存长度
ERROR_MESSAGE_MAX_LEN = 2000
