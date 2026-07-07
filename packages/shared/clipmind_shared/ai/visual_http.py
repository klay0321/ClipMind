"""LocalVisualProvider：embedder ``/visual-embeddings`` 的同步 HTTP 客户端。

VIS-AUTO 起收编入 shared（API 实验链与 worker 自动链共用）；参数全部注入，
不依赖任一进程的 Settings。推理在 embedder 服务内完成（SigLIP，本地推理，
图片不出内网）；失败抛 VisualProviderError（显式原因），绝不静默回退 fake。
"""

from __future__ import annotations

import base64

import httpx

from clipmind_shared.ai.visual import VisualProviderError, VisualProviderIdentity


class LocalVisualProvider:
    """按 batch_size 分片调用 embedder；就绪探测不触发模型加载。"""

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
