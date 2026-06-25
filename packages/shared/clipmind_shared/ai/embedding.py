"""Embedding Provider 抽象（PR-04）。

与视觉分析 ``VisualAnalysisProvider`` 平行：定义统一的文本嵌入接口，使业务层
（检索文档索引器、查询期向量化）只依赖抽象，不直接依赖任何模型/SDK。

实现见 ``providers/fake_embedding.py``（确定性，CI/单测/降级）与
``providers/openai_embedding.py``（OpenAI 兼容 /embeddings，本地 embedder 微服务或外部）。

设计要点：
- MiMo 无 embedding 能力，故 PR-04 走独立 ``EMBEDDING_PROVIDER``，不复用视觉 provider。
- **模型身份**（provider/model/revision/dimension/normalization/prefix）合成 ``embedding_version``；
  任一改变都强制全量重嵌——绝不混用不同模型/维度产生的向量。
- E5 系列模型要求查询加 ``query:`` 前缀、文档加 ``passage:`` 前缀，并对向量做 L2 归一以用
  cosine 检索。前缀策略由 provider 负责，业务层不重复加前缀。
"""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

# 复用视觉 provider 的异常分类（编排层据此重试/降级）
from clipmind_shared.ai.providers.base import (  # noqa: F401  (re-export for callers)
    ProviderAuthError,
    ProviderBadResponse,
    ProviderError,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderTimeoutError,
    ProviderUnavailable,
)

# ---- E5 使用规范与归一化策略（变更需递增对应版本号，强制重嵌）----
E5_QUERY_PREFIX = "query: "
E5_PASSAGE_PREFIX = "passage: "

PREFIX_SCHEME_E5 = "e5"      # query:/passage: 前缀（intfloat/multilingual-e5-*）
PREFIX_SCHEME_NONE = "none"  # 不加前缀

# 向量归一化版本：当前为 L2 单位化（cosine 检索要求）。变更归一化方式时递增。
NORMALIZATION_VERSION = "l2-v1"


class EmbeddingCapabilities(BaseModel):
    """Embedding provider 能力描述。"""

    dimension: int = 0
    max_batch: int = 0          # 单次 embed_documents 最大条数（0=未声明）
    max_input_chars: int = 0    # 单条文本最大字符数（0=未声明）
    supports_query_passage: bool = False  # 是否区分 query/passage（E5 风格）


class EmbeddingIdentity(BaseModel):
    """嵌入身份：参与检索文档幂等判定（任一字段变化→重嵌）。"""

    provider: str = ""
    model: str = ""
    model_revision: str = ""
    dimension: int = 0
    normalization_version: str = NORMALIZATION_VERSION
    prefix_scheme: str = PREFIX_SCHEME_NONE
    embedding_version: str = ""


class EmbeddingHealth(BaseModel):
    ok: bool
    detail: str = ""
    identity: EmbeddingIdentity | None = None


class EmbeddingDimensionMismatch(ProviderBadResponse):
    """返回向量维度与配置维度不一致（绝不静默裁剪/补齐，强制失败）。"""

    error_code = "embedding_dimension_mismatch"


def make_embedding_version(
    *,
    provider: str,
    model: str,
    model_revision: str,
    dimension: int,
    normalization_version: str = NORMALIZATION_VERSION,
    prefix_scheme: str = PREFIX_SCHEME_NONE,
) -> str:
    """合成稳定的嵌入版本串：任一要素变化都会改变结果，从而强制重嵌。"""
    rev = model_revision or "unpinned"
    return f"{provider}:{model}@{rev}:d{dimension}:{normalization_version}:{prefix_scheme}"


def l2_normalize(vec: list[float]) -> list[float]:
    """L2 单位化；零向量原样返回（避免除零）。"""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return list(vec)
    return [x / norm for x in vec]


def apply_e5_prefix(text: str, *, is_query: bool) -> str:
    """E5 前缀；若文本已含对应前缀则不重复添加。"""
    prefix = E5_QUERY_PREFIX if is_query else E5_PASSAGE_PREFIX
    return text if text.startswith(prefix) else f"{prefix}{text}"


@runtime_checkable
class EmbeddingProvider(Protocol):
    """文本嵌入 provider 统一契约。"""

    name: str

    def identity(self) -> EmbeddingIdentity: ...

    def capabilities(self) -> EmbeddingCapabilities: ...

    def health(self) -> EmbeddingHealth: ...

    def embed_query(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
