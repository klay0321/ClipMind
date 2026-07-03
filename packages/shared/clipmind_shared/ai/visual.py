"""PR-F Gate A：视觉嵌入 Provider 协议与确定性假实现（实验能力）。

冻结边界：模型候选 ≠ 产品确认；高相似度 ≠ 自动绑定；Top-1 ≠ 识别事实。
本模块不写任何产品归属，只产出向量。真实推理由 LocalVisualProvider
（apps/api，HTTP → embedder /visual-embeddings）承担；FakeVisualProvider
仅供单元测试 / API E2E / Playwright / CI 使用，不得用于真实验收，也不得
在 UI 中伪装成真实模型。
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Protocol

FAKE_VISUAL_DIMENSION = 32
FAKE_VISUAL_MODEL_ID = "fake-visual-deterministic-v1"


@dataclass(frozen=True)
class VisualProviderIdentity:
    provider: str            # fake | local
    model_id: str
    dimension: int
    device: str


class VisualEmbeddingProvider(Protocol):
    """图片 → L2 归一化向量。实现负责全部预处理（解码/缩放/归一化/batch）。

    失败必须抛异常并带明确原因（解码失败绝不产生零向量；缩略图失败不得
    误判为产品不匹配）。同图片同模型重复计算结果必须逐位稳定。
    """

    def embed_images(self, images: list[bytes]) -> list[list[float]]: ...

    def identity(self) -> VisualProviderIdentity: ...


class VisualProviderError(RuntimeError):
    """视觉 Provider 失败（含明确原因；调用方映射为 model_unavailable/4xx）。"""


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class FakeVisualProvider:
    """确定性假视觉嵌入：sha256(图片字节) 展开为固定维度向量后 L2 归一化。

    性质（供测试依赖）：同字节 → 同向量；不同字节 → 几乎必然不同向量；
    字节流中的 ``FAKE:<family-token>:`` 标记控制相似族——含同一 token 的
    图片向量相同（余弦 ≈ 1），不同 token ≈ 正交。标记可在字节流任意位置
    （E2E 可把 token 嵌在合法 PNG 的尾部，图片仍可被真实解码器解析），
    便于构造可预期的候选/混淆/未知场景。
    """

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        if not images:
            return []
        out: list[list[float]] = []
        for raw in images:
            if not raw:
                raise VisualProviderError("空图片字节")
            seed_src = raw
            marker = raw.find(b"FAKE:")
            if marker != -1:
                # FAKE:<token>: token 决定向量（模拟同产品多角度相似）
                parts = raw[marker:].split(b":", 2)
                if len(parts) >= 2 and parts[1]:
                    seed_src = b"FAKE:" + parts[1]
            digest = hashlib.sha256(seed_src).digest()
            vec = [(digest[i % 32] - 127.5) / 127.5 for i in range(FAKE_VISUAL_DIMENSION)]
            out.append(_l2_normalize(vec))
        return out

    def identity(self) -> VisualProviderIdentity:
        return VisualProviderIdentity(
            provider="fake",
            model_id=FAKE_VISUAL_MODEL_ID,
            dimension=FAKE_VISUAL_DIMENSION,
            device="cpu",
        )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """两个已 L2 归一化向量的余弦相似度（点积；防御性夹取 [-1,1]）。"""
    s = sum(x * y for x, y in zip(a, b, strict=True))
    return max(-1.0, min(1.0, s))
