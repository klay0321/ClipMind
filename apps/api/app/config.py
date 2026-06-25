"""应用配置（pydantic-settings，从环境变量/.env 读取）。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # 数据库（API 使用 async 驱动）
    database_url: str = "postgresql+asyncpg://clipmind:clipmind@postgres:5432/clipmind"

    # Redis / Celery
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # 路径与安全
    allowed_source_roots: str = "/app/source,/app/uploads"  # 逗号分隔的白名单根
    source_mount_path: str = "/app/source"
    data_dir: str = "/app/data"

    # 网页上传：独立可写区（不写只读 NAS 源）
    upload_dir: str = "/app/uploads"
    upload_max_mb: int = 4096

    # FFprobe
    ffprobe_timeout: float = 30.0

    # Web / CORS
    web_origin: str = "http://localhost:3000"
    api_internal_url: str = "http://api:8000"

    # PR-03A AI（API 仅入队 + 读结果 + 回显健康；不在 API 进程调用 provider 网络）
    ai_provider: str = ""
    ai_base_url: str = ""
    ai_api_key: str = ""   # 仅判断是否已配置，绝不回显/记录
    ai_model: str = ""
    ai_max_images: int = 8

    # PR-03B：当前无登录体系，审核者用配置的本地标签（不伪造用户，PR-07 接入后平滑替换）
    review_default_reviewer: str = "local-reviewer"
    # 产品参考图上传约束
    product_image_max_mb: int = 10
    product_image_max_count: int = 20

    log_level: str = "INFO"

    @property
    def allowed_roots_list(self) -> list[str]:
        return [r.strip() for r in self.allowed_source_roots.split(",") if r.strip()]

    @property
    def sync_database_url(self) -> str:
        """供 Alembic 使用的同步连接串（asyncpg -> psycopg）。"""
        return self.database_url.replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
