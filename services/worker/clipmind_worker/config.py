"""Worker 配置（独立于 API，从环境变量/.env 读取）。"""

from __future__ import annotations

from functools import lru_cache

from clipmind_shared.constants import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_MODEL_REVISION,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    database_url: str = "postgresql+asyncpg://clipmind:clipmind@postgres:5432/clipmind"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    source_mount_path: str = "/app/source"
    # 白名单根：只读 NAS 源 + 网页上传可写区
    allowed_source_roots: str = "/app/source,/app/uploads"
    # 派生文件可写数据根（PR-02：拆镜头/关键帧/缩略图/代理/导出写入此处）
    data_dir: str = "/app/data"

    ffprobe_timeout: float = 30.0
    # 单次 ffmpeg 调用超时（拆镜头/转码比探测更耗时）
    ffmpeg_timeout: float = 300.0
    # PR-C：单次扫描内用于移动识别的 full SHA256 计算总字节预算。
    # 候选文件累计超过预算后不再当场算完整哈希，转 ambiguous 交人工/指纹任务处理，
    # 避免一次扫描长时间顺序读占满 NAS。
    scan_full_hash_budget_bytes: int = 16 * 1024 * 1024 * 1024
    # 写派生文件前要求 data_dir 至少剩余的空间（MiB）
    disk_min_free_mb: int = 500

    # PR-05 Gate B：全局分配中单 shot 默认最多分配段数（CSV 导出与 API 须取同值）
    script_match_max_reuse: int = 1

    # ---- 镜头检测参数（可被环境变量覆盖；为初始默认值，非写死业务规则）----
    shot_detector_type: str = "pyscenedetect"   # pyscenedetect | fixed
    scene_threshold: float = 27.0
    min_shot_duration: float = 1.0
    max_shot_duration: float = 12.0
    fallback_segment_duration: float = 5.0
    head_padding: float = 0.0
    tail_padding: float = 0.0

    # ---- 代理视频/关键帧参数 ----
    proxy_max_height: int = 720
    proxy_crf: int = 28
    proxy_preset: str = "veryfast"
    proxy_keep_audio: bool = True
    proxy_audio_bitrate: str = "96k"
    keyframe_max_width: int = 640
    thumbnail_max_width: int = 320
    # 关键帧条：沿镜头均匀采样的帧数（用于详情多帧预览）。0 表示仅主关键帧。
    aux_keyframes: int = 4

    # ---- PR-03A AI 理解分析（ai 队列）----
    # provider：""=未配置（NotConfigured，不调用任何 API）| fake（确定性，测试/CI）| mimo
    ai_provider: str = ""
    ai_base_url: str = ""
    ai_api_key: str = ""          # 仅本地 .env，绝不入库/日志/前端
    ai_model: str = ""
    ai_max_images: int = 8        # 单次调用最大关键帧数（不超过探测得到的能力）
    ai_timeout: float = 60.0      # 单次 AI 调用超时（秒）
    ai_retries: int = 2           # 失败/坏响应重试次数（指数退避）
    ai_prompt_version: str = "v1"
    # 鉴权头：空=Authorization Bearer；如 "api-key" 用自定义头（MiMo token-plan 端点）
    ai_api_key_header: str = ""
    ai_max_completion_tokens: int = 0  # >0 时随请求发送（0=不设）
    # 计价（每 1K token；MiMo 实价需探测，未知留 0 仅记 tokens 不估成本）
    ai_price_input_per_1k: float = 0.0
    ai_price_output_per_1k: float = 0.0
    # ---- P2a.1 视频输入打标 ----
    # frames=多关键帧（默认，兼容所有 provider）| video=整段代理视频（动作/时序更准；
    # provider 不支持或代理缺失/超限时自动回退关键帧，绝不因此失败）
    ai_input_mode: str = "frames"
    ai_video_fps: float = 2.0            # 视频抽帧率（0.1-10；越高越细也越贵）
    ai_video_max_mb: int = 45            # 代理视频超此大小回退关键帧（官方 base64 上限 50MB）

    # ---- AAP 自动分析管线（默认全部关闭，逐项显式开启）----
    # 扫描完成后自动为"无可用镜头且无活动运行"的视频入队拆镜头
    auto_analyze_on_scan: bool = False
    # 拆镜头完成后自动入队 AI 打标（受 ai_daily_budget 护栏约束）
    auto_ai_after_shots: bool = False
    # 单次扫描最多自动入队的拆镜头任务数（防一次性风暴）
    auto_analyze_max_per_scan: int = 200
    # AI 日预算（ai_call_log.est_cost 口径，UTC 日）；<=0 不限。仅限自动路径，手动不受限
    ai_daily_budget: float = 0.0
    # beat 定时扫描全部源目录的间隔（分钟）；<=0 禁用
    scan_interval_minutes: int = 0

    # ---- PR-04 Embedding（search 队列；MiMo 无 embedding，故走独立 provider）----
    # ""=未配置（检索文档仅构建文本、不嵌入，标 degraded）| fake（确定性，CI/测试）
    # | openai_compatible（本地 embedder 微服务或外部 OpenAI 兼容 /embeddings）
    embedding_provider: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""          # 仅本地 .env，绝不入库/日志/前端
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_model_revision: str = DEFAULT_EMBEDDING_MODEL_REVISION  # 默认不可变 commit
    # 须与 vector 列维度一致（换维度需迁移 + 全量重嵌）
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    embedding_timeout: float = 30.0
    embedding_max_batch: int = 64
    embedding_api_key_header: str = ""   # 留空=Authorization Bearer；或自定义头
    embedding_prefix_scheme: str = "e5"  # e5（query:/passage: 前缀）| none
    # fail-closed：未固定 revision（空/main/latest）时不嵌入（文档仍可词法/标签检索）
    embedding_require_pinned_revision: bool = True

    log_level: str = "INFO"

    @property
    def sync_database_url(self) -> str:
        """Worker 使用同步驱动（asyncpg -> psycopg）。"""
        return self.database_url.replace("+asyncpg", "+psycopg")

    @property
    def allowed_roots_list(self) -> list[str]:
        return [r.strip() for r in self.allowed_source_roots.split(",") if r.strip()]


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()
