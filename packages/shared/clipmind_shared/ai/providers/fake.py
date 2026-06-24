"""FakeProvider：确定性的视觉分析 provider（测试 / CI / AI_PROVIDER=fake）。

不做任何网络调用，根据关键帧内容哈希确定性地产出**符合 Schema** 的结构化结果，
使端到端链路（含 docker-e2e）可在无真实 API 时稳定验证。可配置 supports_images=False
以模拟"无视觉能力"的降级路径（此时返回 degraded、parsed=None，绝不伪造视觉结果）。
"""

from __future__ import annotations

import hashlib
import json

from clipmind_shared.ai.provider import ProviderCapabilities, ProviderHealth
from clipmind_shared.ai.providers.base import (
    AnalyzeOutcome,
    FrameRef,
    Usage,
)
from clipmind_shared.ai.schema import ShotAnalysisResult

_SCENES = ["室内", "室外", "桌面", "户外", "工作室"]
_ACTIONS = ["展示", "开箱", "使用", "安装", "对比"]
_SHOT_TYPES = ["产品特写", "手部特写", "人物中景", "POV", "俯拍"]


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        *,
        model: str = "fake-vision-1",
        max_images: int = 8,
        supports_images: bool = True,
    ) -> None:
        self._model = model
        self._max_images = max_images
        self._supports_images = supports_images

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_images=self._supports_images,
            supports_video=False,
            supports_structured_output=True,
            supports_embeddings=False,
            max_images_per_call=self._max_images,
            context_window=8192,
        )

    def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True, detail="fake provider", capabilities=self.capabilities())

    def analyze_frames(
        self,
        frames: list[FrameRef],
        *,
        prompt: str,
        schema: dict,
        timeout: float = 30.0,
    ) -> AnalyzeOutcome:
        if not self._supports_images:
            return AnalyzeOutcome(
                parsed=None,
                raw_excerpt="",
                usage=Usage(input_images=0),
                model=self._model,
                degraded=True,
                degraded_reason="provider_no_image_support",
            )

        seed = "|".join((f.sha256 or f.path) for f in frames) or "empty"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        n = int(digest[:8], 16)

        result = ShotAnalysisResult(
            one_line=f"示例镜头分析 #{n % 1000}",
            detailed="FakeProvider 确定性结构化输出（用于测试/CI，不代表真实视觉分析）。",
            scene=_SCENES[n % len(_SCENES)],
            action=_ACTIONS[n % len(_ACTIONS)],
            shot_type=_SHOT_TYPES[n % len(_SHOT_TYPES)],
            confidence=round((n % 100) / 100.0, 2),
            needs_human_review=(n % 100) < 30,
            search_keywords=[f"kw{n % 10}", "fake"],
        )
        parsed = result.model_dump()
        used_images = min(len(frames), self._max_images)
        return AnalyzeOutcome(
            parsed=parsed,
            raw_excerpt=json.dumps(parsed, ensure_ascii=False)[:512],
            usage=Usage(input_tokens=100, output_tokens=120, input_images=used_images),
            model=self._model,
            http_status=200,
        )
