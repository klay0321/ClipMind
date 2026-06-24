"""AI 视觉分析 provider 工厂（PR-03A）。

依据 provider 名装配具体实现；未配置时返回 NotConfiguredVisualProvider（health ok=False、
分析方法显式抛 ProviderNotConfigured），**绝不返回假数据**。MiMoProvider 惰性导入，避免
未用到时引入 httpx 等依赖。
"""

from __future__ import annotations

from clipmind_shared.ai.provider import ProviderCapabilities, ProviderHealth
from clipmind_shared.ai.providers.base import (
    AnalyzeOutcome,
    FrameRef,
    ProviderNotConfigured,
    VisualAnalysisProvider,
)
from clipmind_shared.ai.providers.fake import FakeProvider


class NotConfiguredVisualProvider:
    """未配置 AI provider 的占位实现。"""

    name = "notconfigured"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            ok=False, detail="AI provider 未配置（设置 AI_PROVIDER）", capabilities=ProviderCapabilities()
        )

    def analyze_frames(
        self,
        frames: list[FrameRef],
        *,
        prompt: str,
        schema: dict,
        timeout: float = 30.0,
    ) -> AnalyzeOutcome:
        raise ProviderNotConfigured("AI provider 未配置")


def get_provider(
    name: str | None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 30.0,
    max_images: int = 8,
    api_key_header: str = "",
    max_completion_tokens: int = 0,
) -> VisualAnalysisProvider:
    """按名装配视觉分析 provider。"""
    key = (name or "").strip().lower()
    if key == "fake":
        return FakeProvider(model=model or "fake-vision-1", max_images=max_images)
    if key == "mimo":
        # 惰性导入：仅在选用 mimo 时引入 httpx 依赖
        from clipmind_shared.ai.providers.mimo import MiMoProvider

        return MiMoProvider(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_images=max_images,
            api_key_header=api_key_header,
            max_completion_tokens=max_completion_tokens,
        )
    return NotConfiguredVisualProvider()
