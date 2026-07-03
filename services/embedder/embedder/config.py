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

    # PR-F 视觉嵌入（实验）：惰性加载——只有首个 /visual-embeddings 请求才
    # 下载/加载权重（CI 与纯文本部署永不触发）。权重落 cache_dir 卷，不进镜像。
    visual_model: str = "google/siglip-base-patch16-224"  # Apache-2.0
    visual_model_revision: str = ""  # 可选固定 revision
    visual_dimension: int = 768
    visual_device: str = "cpu"
    visual_max_batch: int = 8
    visual_max_image_bytes: int = 20 * 1024 * 1024

    log_level: str = "INFO"


@lru_cache
def get_settings() -> EmbedderSettings:
    return EmbedderSettings()
