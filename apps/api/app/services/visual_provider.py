"""PR-F：视觉嵌入 Provider 装配（fake / local）。

- fake：CI / 单测 / E2E 专用的确定性向量（clipmind_shared.ai.visual）；
  不得用于真实验收，/status 会如实返回 provider=fake。
- local：HTTP 调 embedder ``/visual-embeddings``（SigLIP，本地推理，图片
  不出内网）；初始化/推理失败抛 VisualProviderError（显式原因），绝不
  静默回退 fake 冒充真实识别。
"""

from __future__ import annotations

import base64

import httpx
from clipmind_shared.ai.visual import (
    FakeVisualProvider,
    VisualEmbeddingProvider,
    VisualProviderError,
    VisualProviderIdentity,
)

from app.config import Settings


class LocalVisualProvider:
    """embedder /visual-embeddings 的同步 HTTP 客户端（批处理由 batch_size 分片）。"""

    def __init__(self, *, base_url: str, model_id: str, device: str, batch_size: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._device = device
        self._batch = max(1, batch_size)
        self._dimension: int | None = None

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(images), self._batch):
            chunk = images[i : i + self._batch]
            payload = {"images": [base64.b64encode(b).decode("ascii") for b in chunk]}
            try:
                resp = httpx.post(
                    f"{self._base_url}/visual-embeddings", json=payload, timeout=300
                )
            except httpx.HTTPError as exc:
                raise VisualProviderError(f"embedder 不可达: {type(exc).__name__}") from exc
            if resp.status_code != 200:
                detail = ""
                try:
                    detail = str(resp.json().get("detail", ""))[:200]
                except Exception:  # noqa: BLE001
                    detail = resp.text[:200]
                raise VisualProviderError(f"视觉推理失败({resp.status_code}): {detail}")
            body = resp.json()
            self._dimension = int(body.get("dimension") or 0) or self._dimension
            out.extend([d["embedding"] for d in body["data"]])
        return out

    def ready(self) -> tuple[bool, str | None]:
        """不触发模型加载的就绪探测（/visual-ready）。"""
        try:
            resp = httpx.get(f"{self._base_url}/visual-ready", timeout=10)
            body = resp.json()
            if body.get("ready"):
                return True, None
            return False, body.get("error") or (
                "视觉模型加载中" if body.get("loading") else "视觉模型未加载（首次调用触发）"
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"embedder 不可达: {type(exc).__name__}"

    def identity(self) -> VisualProviderIdentity:
        return VisualProviderIdentity(
            provider="local",
            model_id=self._model_id,
            dimension=self._dimension or 768,
            device=self._device,
        )


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
