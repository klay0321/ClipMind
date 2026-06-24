"""FakeProvider 与工厂测试（PR-03A）。"""

from __future__ import annotations

import pytest

from clipmind_shared.ai import (
    FakeProvider,
    FrameRef,
    NotConfiguredVisualProvider,
    ProviderNotConfigured,
    get_provider,
    shot_analysis_json_schema,
    validate_shot_analysis,
)

_SCHEMA = shot_analysis_json_schema()


def _frames(*hashes):
    return [FrameRef(path=f"/x/{h}.webp", sha256=h) for h in hashes]


def test_fake_capabilities_and_health():
    p = FakeProvider()
    caps = p.capabilities()
    assert caps.supports_images is True
    assert caps.supports_structured_output is True
    assert caps.supports_embeddings is False
    assert p.health().ok is True


def test_fake_analyze_returns_schema_valid_and_deterministic():
    p = FakeProvider()
    out1 = p.analyze_frames(_frames("h1", "h2"), prompt="p", schema=_SCHEMA)
    out2 = p.analyze_frames(_frames("h1", "h2"), prompt="p", schema=_SCHEMA)
    assert out1.degraded is False
    assert out1.parsed == out2.parsed  # 确定性
    assert out1.usage.input_images == 2
    # 必须可通过 Schema 校验
    validate_shot_analysis(out1.parsed)


def test_fake_varies_by_frames():
    p = FakeProvider()
    a = p.analyze_frames(_frames("h1"), prompt="p", schema=_SCHEMA)
    b = p.analyze_frames(_frames("h2"), prompt="p", schema=_SCHEMA)
    assert a.parsed != b.parsed


def test_fake_no_image_support_degrades_without_fabrication():
    p = FakeProvider(supports_images=False)
    out = p.analyze_frames(_frames("h1"), prompt="p", schema=_SCHEMA)
    assert out.degraded is True
    assert out.parsed is None
    assert out.degraded_reason == "provider_no_image_support"


def test_factory_fake_and_notconfigured():
    assert isinstance(get_provider("fake"), FakeProvider)
    nc = get_provider(None)
    assert isinstance(nc, NotConfiguredVisualProvider)
    assert nc.health().ok is False
    with pytest.raises(ProviderNotConfigured):
        nc.analyze_frames(_frames("h1"), prompt="p", schema=_SCHEMA)
