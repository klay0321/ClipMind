"""FakeEmbeddingProvider：确定性、内容相关的文本嵌入（测试/CI/降级验证）。

不联网、不依赖 torch。把文本分词后用多哈希散布到固定维向量并 L2 归一：
- 完全确定性：相同输入永远得到相同向量；
- 非恒定：向量随内容变化；
- 内容相关：共享 token 越多 → cosine 越高（使排序/匹配/E2E 测试有意义）；
- query 与 passage 落在同一空间（不依角色改变向量），故"查询命中其文档"成立。

仅供测试与降级，**不得宣称其检索质量等同真实语义模型**。
"""

from __future__ import annotations

import hashlib
import re

from clipmind_shared.ai.embedding import (
    PREFIX_SCHEME_NONE,
    EmbeddingCapabilities,
    EmbeddingHealth,
    EmbeddingIdentity,
    l2_normalize,
    make_embedding_version,
)

_HASHES_PER_TOKEN = 4
# 拉丁/数字按非词字符切；CJK 等按单字符切（与 normalize 后的文本配合，鲁棒处理中英混合）
_LATIN_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CJK = re.compile(r"[㐀-鿿぀-ヿ가-힯]")
# E5 前缀若混入则剥离，保证内容向量与角色无关
_E5_PREFIX = re.compile(r"^(query|passage):\s*")


def _tokens(text: str) -> list[str]:
    s = _E5_PREFIX.sub("", (text or "").strip().lower())
    toks = _LATIN_TOKEN.findall(s)
    toks.extend(_CJK.findall(s))
    return toks


class FakeEmbeddingProvider:
    name = "fake"

    def __init__(self, *, dimension: int = 384, model: str = "fake-embed-1") -> None:
        if dimension <= 0:
            raise ValueError("dimension 必须为正")
        self._dimension = dimension
        self._model = model

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self._dimension
        toks = _tokens(text) or ["∅"]  # 空文本用占位符，避免零向量
        for tok in toks:
            for k in range(_HASHES_PER_TOKEN):
                h = int(hashlib.sha256(f"{k}:{tok}".encode()).hexdigest(), 16)
                idx = h % self._dimension
                sign = 1.0 if (h >> 8) & 1 else -1.0
                v[idx] += sign
        return l2_normalize(v)

    def identity(self) -> EmbeddingIdentity:
        return EmbeddingIdentity(
            provider=self.name,
            model=self._model,
            model_revision="fake",
            dimension=self._dimension,
            prefix_scheme=PREFIX_SCHEME_NONE,
            embedding_version=make_embedding_version(
                provider=self.name,
                model=self._model,
                model_revision="fake",
                dimension=self._dimension,
                prefix_scheme=PREFIX_SCHEME_NONE,
            ),
        )

    def capabilities(self) -> EmbeddingCapabilities:
        return EmbeddingCapabilities(
            dimension=self._dimension,
            max_batch=256,
            max_input_chars=8192,
            supports_query_passage=True,
        )

    def health(self) -> EmbeddingHealth:
        return EmbeddingHealth(ok=True, detail="fake embedding provider", identity=self.identity())

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]
