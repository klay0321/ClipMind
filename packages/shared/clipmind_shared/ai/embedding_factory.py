"""Embedding provider 工厂（PR-04）。

按 ``EMBEDDING_PROVIDER`` 装配实现；未配置时返回 NotConfiguredEmbeddingProvider
（health ok=False、嵌入显式抛 ProviderNotConfigured），**绝不返回假向量**。
``openai_compatible`` 惰性导入 httpx，避免未用时引入依赖。
"""

from __future__ import annotations

from clipmind_shared.ai.embedding import (
    EmbeddingCapabilities,
    EmbeddingHealth,
    EmbeddingIdentity,
    EmbeddingProvider,
    ProviderNotConfigured,
)
from clipmind_shared.ai.providers.fake_embedding import FakeEmbeddingProvider

# 接受的 OpenAI 兼容别名（本地 embedder 微服务亦走此实现）
_OPENAI_ALIASES = {"openai", "openai_compatible", "openai-compatible", "http", "embedder"}


class NotConfiguredEmbeddingProvider:
    """未配置 Embedding provider 占位。"""

    name = "notconfigured"

    def __init__(self, *, dimension: int = 0) -> None:
        self._dimension = dimension

    def identity(self) -> EmbeddingIdentity:
        return EmbeddingIdentity(provider=self.name, dimension=self._dimension)

    def capabilities(self) -> EmbeddingCapabilities:
        return EmbeddingCapabilities(dimension=self._dimension)

    def health(self) -> EmbeddingHealth:
        return EmbeddingHealth(
            ok=False,
            detail="Embedding provider 未配置（设置 EMBEDDING_PROVIDER）",
            identity=self.identity(),
        )

    def embed_query(self, text: str) -> list[float]:
        raise ProviderNotConfigured("Embedding provider 未配置")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise ProviderNotConfigured("Embedding provider 未配置")


def get_embedding_provider(
    name: str | None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    dimension: int = 384,
    model_revision: str = "",
    timeout: float = 30.0,
    max_batch: int = 64,
    api_key_header: str = "",
    prefix_scheme: str = "e5",
    normalize: bool = True,
    require_pinned_revision: bool = True,
) -> EmbeddingProvider:
    """按名装配 embedding provider。"""
    key = (name or "").strip().lower()
    if key == "fake":
        return FakeEmbeddingProvider(dimension=dimension or 384, model=model or "fake-embed-1")
    if key in _OPENAI_ALIASES:
        # 惰性导入：仅在选用 HTTP provider 时引入 httpx 依赖
        from clipmind_shared.ai.providers.openai_embedding import (
            OpenAICompatibleEmbeddingProvider,
        )

        return OpenAICompatibleEmbeddingProvider(
            base_url=base_url,
            api_key=api_key,
            model=model,
            dimension=dimension,
            model_revision=model_revision,
            timeout=timeout,
            max_batch=max_batch,
            api_key_header=api_key_header,
            prefix_scheme=prefix_scheme,
            normalize=normalize,
            require_pinned_revision=require_pinned_revision,
        )
    return NotConfiguredEmbeddingProvider(dimension=dimension)
