"""Worker 配置（独立于 API，从环境变量/.env 读取）。"""

from __future__ import annotations

from functools import lru_cache

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
    # 写派生文件前要求 data_dir 至少剩余的空间（MiB）
    disk_min_free_mb: int = 500

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
