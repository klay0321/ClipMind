"""FakeEmbeddingProvider 测试：确定性、非恒定、维度、批序、内容相关、query/passage、身份。"""

from __future__ import annotations

import math

from clipmind_shared.ai import FakeEmbeddingProvider
from clipmind_shared.ai.embedding import l2_normalize


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_dimension_and_unit_norm():
    p = FakeEmbeddingProvider(dimension=384)
    v = p.embed_query("一段中文文本 with english")
    assert len(v) == 384
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6)


def test_deterministic_same_input():
    p = FakeEmbeddingProvider(dimension=384)
    assert p.embed_query("PowerGo 充电器") == p.embed_query("PowerGo 充电器")
    assert p.embed_documents(["a", "b"]) == p.embed_documents(["a", "b"])


def test_not_constant_across_inputs():
    p = FakeEmbeddingProvider(dimension=384)
    a = p.embed_query("猫在草地奔跑")
    b = p.embed_query("充电器桌面充电")
    assert a != b
    # 单条向量不是恒定值（并非所有维度相等）
    assert len(set(round(x, 6) for x in a)) > 1


def test_batch_order_matches_individual():
    p = FakeEmbeddingProvider(dimension=384)
    texts = ["第一段", "second", "第三 mixed"]
    batch = p.embed_documents(texts)
    assert batch == [p.embed_documents([t])[0] for t in texts]


def test_content_relatedness_cosine():
    p = FakeEmbeddingProvider(dimension=384)
    q = p.embed_query("猫 在 草地 上 奔跑")
    near = p.embed_documents(["猫 在 草地 上 快速 奔跑"])[0]
    far = p.embed_documents(["充电器 在 桌面 上 充电"])[0]
    assert _cos(q, near) > _cos(q, far)


def test_query_passage_same_space():
    # Fake 角色无关：同文本的 query 与 passage 向量一致（保证"查询命中其文档"）
    p = FakeEmbeddingProvider(dimension=384)
    assert p.embed_query("同样的文本") == p.embed_documents(["同样的文本"])[0]


def test_identity_stable_and_versioned():
    p = FakeEmbeddingProvider(dimension=384)
    idy = p.identity()
    assert idy.provider == "fake"
    assert idy.dimension == 384
    assert idy.embedding_version  # 非空
    assert p.identity().embedding_version == idy.embedding_version
    # 不同维度 → 不同版本（防混用）
    assert FakeEmbeddingProvider(dimension=256).identity().embedding_version != idy.embedding_version


def test_l2_normalize_zero_vector():
    assert l2_normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]
