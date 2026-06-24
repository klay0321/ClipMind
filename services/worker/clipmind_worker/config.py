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
    allowed_source_roots: str = "/app/source"
    ffprobe_timeout: float = 30.0
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
