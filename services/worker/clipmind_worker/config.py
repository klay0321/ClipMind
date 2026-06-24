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
