"""输入指纹测试（PR-03A）：确定性 + 输入敏感。"""

from __future__ import annotations

from clipmind_shared.ai.fingerprint import compute_fingerprint, hash_bytes


def _fp(**over):
    base = dict(
        frame_hashes=["a", "b"],
        provider="mimo",
        model="m1",
        prompt_version="v1",
        schema_version=1,
        params={"max_images": 8},
    )
    base.update(over)
    return compute_fingerprint(**base)


def test_deterministic():
    assert _fp() == _fp()


def test_changes_on_frame_change():
    assert _fp() != _fp(frame_hashes=["a", "c"])


def test_changes_on_model_or_prompt_or_schema():
    assert _fp() != _fp(model="m2")
    assert _fp() != _fp(prompt_version="v2")
    assert _fp() != _fp(schema_version=2)


def test_param_key_order_irrelevant():
    a = _fp(params={"x": 1, "y": 2})
    b = _fp(params={"y": 2, "x": 1})
    assert a == b


def test_hash_bytes_stable():
    assert hash_bytes(b"abc") == hash_bytes(b"abc")
    assert hash_bytes(b"abc") != hash_bytes(b"abd")
