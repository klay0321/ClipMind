"""Embedder 微服务配置（环境变量/.env）。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbedderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # 模型身份。默认固定为不可变 commit SHA（公开模型，非敏感）。本服务不依赖 clipmind_shared，
    # 故此处硬编码；必须与 clipmind_shared.constants.DEFAULT_EMBEDDING_MODEL_REVISION 一致
    # （由 test_revision_consistency 强制）。换模型/维度/revision 须全量重嵌。
    embedder_model: str = "intfloat/multilingual-e5-small"
    embedder_model_revision: str = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    embedder_dimension: int = 384
    embedder_device: str = "cpu"

    # 限制
    embedder_max_batch: int = 64
    embedder_max_input_chars: int = 8192

    # 模型缓存目录（独立 Docker volume；支持离线缓存启动）
    embedder_cache_dir: str = "/models"
    # 本服务不加 E5 前缀、不归一化（由调用端 provider 负责）
    embedder_normalize: bool = False

    log_level: str = "INFO"


@lru_cache
def get_settings() -> EmbedderSettings:
    return EmbedderSettings()
