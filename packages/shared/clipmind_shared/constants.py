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
# PR-03A AI 理解分析（ai 队列）
TASK_ANALYZE_ASSET_AI = "clipmind.analyze_asset_ai"
TASK_ANALYZE_SHOT_AI = "clipmind.analyze_shot_ai"
# PR-04 检索文档索引（search 队列）：单镜头/单素材重建 + sweeper 兜底 + 全量/失败回填
TASK_REBUILD_SHOT_SEARCH_DOC = "clipmind.rebuild_shot_search_doc"
TASK_REBUILD_ASSET_SEARCH_DOCS = "clipmind.rebuild_asset_search_docs"
TASK_SWEEP_SEARCH_DOCS = "clipmind.sweep_search_docs"
TASK_BACKFILL_SEARCH_DOCS = "clipmind.backfill_search_docs"
# PR-05 Gate B 脚本剪辑清单 CSV 导出（export 队列）
TASK_EXPORT_SCRIPT_CSV = "clipmind.export_script_csv"

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
