"""PR-F：视觉嵌入 Provider 装配（fake / local）。

- fake：CI / 单测 / E2E 专用的确定性向量（clipmind_shared.ai.visual）；
  不得用于真实验收，/status 会如实返回 provider=fake。
- local：HTTP 调 embedder ``/visual-embeddings``（SigLIP，本地推理，图片
  不出内网）。实现自 VIS-AUTO 起收编入 clipmind_shared.ai.visual_http
  （worker 自动链共用同一客户端），本模块保留装配入口。
"""

from __future__ import annotations

from clipmind_shared.ai.visual import (
    FakeVisualProvider,
    VisualEmbeddingProvider,
    VisualProviderError,
)
from clipmind_shared.ai.visual_http import LocalVisualProvider

from app.config import Settings

__all__ = ["LocalVisualProvider", "get_visual_provider"]


def get_visual_provider(settings: Settings) -> VisualEmbeddingProvider:
    """按配置装配 provider；未知取值显式报错（不静默回退）。"""
    mode = (settings.visual_embedding_provider or "fake").strip().lower()
    if mode == "fake":
        return FakeVisualProvider()
    if mode == "local":
        return LocalVisualProvider(
            base_url=settings.visual_embedder_url,
            model_id=settings.visual_model_id,
            device=settings.visual_device,
            batch_size=settings.visual_batch_size,
        )
    raise VisualProviderError(f"未知 VISUAL_EMBEDDING_PROVIDER: {mode}")
