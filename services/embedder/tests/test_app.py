"""Embedder 服务端点测试（不加载真实模型；torch 惰性导入，CI 后端环境即可运行）。

覆盖：/health 存活；模型未就绪 → /ready、/embeddings 返回 503；注入桩模型后 happy-path、
维度=384、批量上限、空输入、**model 参数不可用于选择模型**（绝不触发任意模型下载）。
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

import embedder.app as appmod


class _StubModel:
    """桩编码器：返回确定性 384 维向量（不联网、不依赖 torch）。"""

    def encode(self, inputs, normalize_embeddings=False, convert_to_numpy=True):  # noqa: ANN001
        return np.array([[float((i + 1) % 7)] * 384 for i in range(len(inputs))], dtype=float)


@pytest.fixture
def client():
    return TestClient(appmod.app)


@pytest.fixture
def reset_state():
    saved = dict(appmod._state)
    yield
    appmod._state.clear()
    appmod._state.update(saved)


def test_health_alive(client, reset_state):
    appmod._state.update(model=None, ready=False, error=None)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["ready"] is False  # health 存活不代表模型已加载


def test_ready_503_when_not_loaded(client, reset_state):
    appmod._state.update(model=None, ready=False, error=None)
    assert client.get("/ready").status_code == 503


def test_embeddings_503_when_not_ready(client, reset_state):
    appmod._state.update(model=None, ready=False, error=None)
    assert client.post("/embeddings", json={"input": "x"}).status_code == 503


def test_embeddings_happy_dim_384(client, reset_state):
    appmod._state.update(model=_StubModel(), ready=True, error=None)
    r = client.post("/embeddings", json={"input": ["第一段", "second"]})
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 2
    assert all(len(d["embedding"]) == 384 for d in body["data"])
    assert [d["index"] for d in body["data"]] == [0, 1]


def test_model_param_cannot_select_model(client, reset_state):
    appmod._state.update(model=_StubModel(), ready=True, error=None)
    r = client.post("/embeddings", json={"input": "x", "model": "evil/other-model"})
    assert r.status_code == 200
    # 响应回显的是服务端配置模型，绝非客户端传入的任意模型
    assert r.json()["model"] == appmod.get_settings().embedder_model
    assert r.json()["model"] != "evil/other-model"


def test_empty_input_400(client, reset_state):
    appmod._state.update(model=_StubModel(), ready=True, error=None)
    assert client.post("/embeddings", json={"input": []}).status_code == 400


def test_batch_over_limit_400(client, reset_state):
    appmod._state.update(model=_StubModel(), ready=True, error=None)
    n = appmod.get_settings().embedder_max_batch + 1
    assert client.post("/embeddings", json={"input": ["x"] * n}).status_code == 400
