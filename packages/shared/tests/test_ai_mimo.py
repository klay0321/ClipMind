"""MiMoProvider 测试（PR-03A）：用 httpx.MockTransport，无真实网络。"""

from __future__ import annotations

import json

import httpx
import pytest

from clipmind_shared.ai import (
    FrameRef,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderTimeoutError,
    shot_analysis_json_schema,
    validate_shot_analysis,
)
from clipmind_shared.ai.providers.mimo import MiMoProvider

SCHEMA = shot_analysis_json_schema()


def _frames(tmp_path, n=1):
    refs = []
    for i in range(n):
        p = tmp_path / f"f{i}.webp"
        p.write_bytes(b"img" + str(i).encode())
        refs.append(FrameRef(path=str(p), sha256=f"h{i}"))
    return refs


def _provider(handler, **over):
    return MiMoProvider(
        base_url="https://api.test/v1", api_key="sk-test", model="mimo",
        transport=httpx.MockTransport(handler), **over,
    )


def _ok(content, usage=None):
    body = {"model": "mimo-v2.5", "choices": [{"message": {"content": content}}]}
    if usage:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def test_capabilities_and_health():
    p = MiMoProvider(base_url="u", api_key="k", model="m")
    assert p.capabilities().supports_images is True
    assert p.health().ok is True
    assert MiMoProvider(base_url="", api_key="", model="m").health().ok is False


def test_success_parses_and_counts_usage(tmp_path):
    payload = {"one_line": "特写", "confidence": 0.7}

    def handler(req):
        assert req.headers["authorization"].startswith("Bearer ")
        return _ok(json.dumps(payload), usage={"prompt_tokens": 50, "completion_tokens": 30})

    out = _provider(handler).analyze_frames(_frames(tmp_path, 2), prompt="sys", schema=SCHEMA)
    assert out.parsed["one_line"] == "特写"
    assert out.usage.input_tokens == 50
    assert out.usage.output_tokens == 30
    assert out.usage.input_images == 2
    validate_shot_analysis(out.parsed)


def test_strips_json_fences(tmp_path):
    def handler(req):
        return _ok('```json\n{"one_line":"x"}\n```')

    out = _provider(handler).analyze_frames(_frames(tmp_path), prompt="s", schema=SCHEMA)
    assert out.parsed["one_line"] == "x"


def test_auth_error(tmp_path):
    def handler(req):
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(ProviderAuthError):
        _provider(handler).analyze_frames(_frames(tmp_path), prompt="s", schema=SCHEMA)


def test_rate_limited_with_retry_after(tmp_path):
    def handler(req):
        return httpx.Response(429, headers={"retry-after": "2"}, json={})

    with pytest.raises(ProviderRateLimited) as ei:
        _provider(handler).analyze_frames(_frames(tmp_path), prompt="s", schema=SCHEMA)
    assert ei.value.retry_after == 2.0


def test_bad_json_response(tmp_path):
    def handler(req):
        return _ok("not json at all")

    with pytest.raises(ProviderBadResponse):
        _provider(handler).analyze_frames(_frames(tmp_path), prompt="s", schema=SCHEMA)


def test_timeout(tmp_path):
    def handler(req):
        raise httpx.TimeoutException("slow")

    with pytest.raises(ProviderTimeoutError):
        _provider(handler).analyze_frames(_frames(tmp_path), prompt="s", schema=SCHEMA)
