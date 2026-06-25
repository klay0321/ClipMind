"""Embedding 工厂测试：fake / notconfigured / openai_compatible 装配与降级语义。"""

from __future__ import annotations

import pytest

from clipmind_shared.ai import (
    FakeEmbeddingProvider,
    NotConfiguredEmbeddingProvider,
    ProviderNotConfigured,
    get_embedding_provider,
)


def test_fake_provider_selected():
    p = get_embedding_provider("fake", dimension=384)
    assert isinstance(p, FakeEmbeddingProvider)
    assert len(p.embed_query("x")) == 384


def test_unconfigured_raises_not_fake():
    p = get_embedding_provider("", dimension=384)
    assert isinstance(p, NotConfiguredEmbeddingProvider)
    assert p.health().ok is False
    with pytest.raises(ProviderNotConfigured):
        p.embed_query("x")
    with pytest.raises(ProviderNotConfigured):
        p.embed_documents(["x"])


def test_openai_compatible_selected_without_network():
    p = get_embedding_provider(
        "openai_compatible", base_url="http://embedder:8100", model="m", dimension=384
    )
    assert p.name == "openai_compatible"
    assert p.identity().dimension == 384
    assert p.capabilities().dimension == 384


def test_dimension_passthrough_in_identity():
    assert get_embedding_provider("fake", dimension=384).identity().dimension == 384
