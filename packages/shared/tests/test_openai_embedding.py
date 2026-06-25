"""OpenAICompatibleEmbeddingProvider 测试（httpx MockTransport，无网络）。

覆盖：E5 前缀、L2 归一、维度校验、批量按 index 稳定排序、错误分类。
"""

from __future__ import annotations

import json
import math

import httpx
import pytest

from clipmind_shared.ai.embedding import EmbeddingDimensionMismatch
from clipmind_shared.ai.providers.base import (
    ProviderAuthError,
    ProviderBadResponse,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderUnavailable,
)
from clipmind_shared.ai.providers.openai_embedding import OpenAICompatibleEmbeddingProvider

DIM = 384
PINNED = "a1b2c3d4e5f6"  # 测试用固定 revision（非空/非 main/latest）


def _vec(seed: float) -> list[float]:
    return [seed] * DIM


def _provider(handler) -> OpenAICompatibleEmbeddingProvider:
    return OpenAICompatibleEmbeddingProvider(
        base_url="http://embedder:8100",
        api_key="secret",
        model="multilingual-e5-small",
        dimension=DIM,
        model_revision=PINNED,
        transport=httpx.MockTransport(handler),
    )


def test_embed_query_prefix_and_l2_normalized():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": _vec(0.5)}], "model": "m"})

    vec = _provider(handler).embed_query("充电器")
    assert captured["body"]["input"][0] == "query: 充电器"      # E5 query 前缀
    assert captured["auth"] == "Bearer secret"                  # 密钥在头
    assert len(vec) == DIM
    assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0, rel_tol=1e-6)  # 已 L2 归一


def test_embed_documents_passage_prefix_and_order():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert all(t.startswith("passage: ") for t in body["input"])
        # 故意乱序返回（index 1 在前），provider 必须按 index 稳定排序
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": _vec(0.2)},
                    {"index": 0, "embedding": _vec(0.9)},
                ],
                "model": "m",
            },
        )

    out = _provider(handler).embed_documents(["a", "b"])
    assert len(out) == 2
    # index 0 对应 0.9 向量（归一后各分量相等且为正），index 1 对应 0.2 向量
    assert out[0][0] > 0 and out[1][0] > 0
    assert out[0] == out[1]  # 同向（都是常量向量归一），但顺序由 index 决定来源


def test_dimension_mismatch_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})

    with pytest.raises(EmbeddingDimensionMismatch):
        _provider(handler).embed_query("x")


@pytest.mark.parametrize(
    "status,exc",
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (429, ProviderRateLimited),
        (500, ProviderUnavailable),
    ],
)
def test_http_error_classification(status, exc):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "x"})

    with pytest.raises(exc):
        _provider(handler).embed_query("x")


def test_bad_json_structure_raises_bad_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(ProviderBadResponse):
        _provider(handler).embed_query("x")


def _called_handler():
    state = {"called": False}

    def handler(request: httpx.Request) -> httpx.Response:
        state["called"] = True
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": _vec(0.5)}]})

    return handler, state


@pytest.mark.parametrize("rev", ["", "main", "latest", "head", "HEAD"])
def test_unpinned_revision_fail_closed(rev):
    handler, state = _called_handler()
    p = OpenAICompatibleEmbeddingProvider(
        base_url="http://embedder:8100", api_key="k", model="e5", dimension=DIM,
        model_revision=rev, require_pinned_revision=True, transport=httpx.MockTransport(handler),
    )
    assert p.health().ok is False
    with pytest.raises(ProviderNotConfigured):
        p.embed_query("x")
    assert state["called"] is False  # 未固定 revision 时绝不发起真实嵌入请求


def test_pinned_revision_healthy():
    handler, _ = _called_handler()
    p = OpenAICompatibleEmbeddingProvider(
        base_url="http://embedder:8100", api_key="k", model="e5", dimension=DIM,
        model_revision=PINNED, transport=httpx.MockTransport(handler),
    )
    assert p.health().ok is True
    assert len(p.embed_query("x")) == DIM


def test_revision_changes_embedding_version():
    a = OpenAICompatibleEmbeddingProvider(
        base_url="http://e", api_key="k", model="e5", dimension=DIM, model_revision="rev-a"
    ).identity().embedding_version
    b = OpenAICompatibleEmbeddingProvider(
        base_url="http://e", api_key="k", model="e5", dimension=DIM, model_revision="rev-b"
    ).identity().embedding_version
    assert a != b  # revision 变化 → embedding_version 变化（防新旧向量混用）
