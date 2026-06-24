"""AI Provider 抽象接口（适配器模式）。

PR-01 只定义接口边界与能力描述，不进行任何真实 API 调用、不放任何密钥。
PR-03 才实现具体 Provider（如小米 MiMo），并先做能力探测填充 ProviderCapabilities。

设计原则：
- 接口预留视觉/文本/向量/重排全部能力。
- 若实际 Provider 不支持某能力（如图片或 Embedding），由编排层据 capabilities 降级，
  绝不伪造视觉分析或向量结果。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class ProviderCapabilities(BaseModel):
    """Provider 能力描述，由能力探测填充（PR-03）。"""

    supports_images: bool = False
    supports_video: bool = False
    supports_structured_output: bool = False
    supports_embeddings: bool = False
    max_images_per_call: int = 0
    context_window: int = 0


class ProviderHealth(BaseModel):
    ok: bool
    detail: str = ""
    capabilities: ProviderCapabilities | None = None


@runtime_checkable
class AIProvider(Protocol):
    """AI 能力统一接口。具体实现见 PR-03。"""

    def health_check(self) -> ProviderHealth: ...

    def analyze_frames(self, frames: list[Any], prompt: str) -> dict[str, Any]: ...

    def analyze_video_clip(self, clip_path: str, prompt: str) -> dict[str, Any]: ...

    def parse_search_query(self, text: str) -> dict[str, Any]: ...

    def parse_script(self, text: str) -> list[dict[str, Any]]: ...

    def generate_embedding(self, text: str) -> list[float]: ...

    def rerank_candidates(
        self, query: str, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...


class NotConfiguredProvider:
    """未配置 AI Provider 时的占位实现。

    health_check 返回 ok=False；其余能力方法一律抛 NotImplementedError，
    确保 PR-01 不会伪造任何 AI 结果。
    """

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            ok=False,
            detail="AI provider 未配置（将在 PR-03 实现）",
            capabilities=ProviderCapabilities(),
        )

    def _not_implemented(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("AI 能力将在 PR-03 实现")

    analyze_frames = _not_implemented
    analyze_video_clip = _not_implemented
    parse_search_query = _not_implemented
    parse_script = _not_implemented
    generate_embedding = _not_implemented
    rerank_candidates = _not_implemented
