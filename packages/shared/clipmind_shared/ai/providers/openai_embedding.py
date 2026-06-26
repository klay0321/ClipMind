"""OpenAICompatibleEmbeddingProvider：OpenAI 兼容 ``/embeddings`` 端点（PR-04）。

调用本地 embedder 微服务（services/embedder）或任意 OpenAI 兼容外部端点。本进程不加载
torch / sentence-transformers —— 仅发 HTTP。E5 前缀与 L2 归一在此统一处理，embedder
服务不重复加前缀。

错误分类对齐 MiMoProvider：401/403→Auth、429→RateLimited、408/超时→Timeout、5xx→
Unavailable、2xx 不可解析/维度不符→BadResponse。**密钥仅置请求头，绝不写日志/库/返回。**
"""

from __future__ import annotations

import httpx

from clipmind_shared.ai.embedding import (
    PREFIX_SCHEME_E5,
    EmbeddingCapabilities,
    EmbeddingDimensionMismatch,
    EmbeddingHealth,
    EmbeddingIdentity,
    apply_e5_prefix,
    l2_normalize,
    make_embedding_version,
)
from clipmind_shared.ai.providers.base import (
    ProviderAuthError,
    ProviderBadResponse,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderTimeoutError,
    ProviderUnavailable,
)

# 视为"未固定"的 revision（不可用于生产；强制 fail-closed 降级）
_UNPINNED_REVISIONS = {"", "main", "latest", "head", "HEAD"}


class OpenAICompatibleEmbeddingProvider:
    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
        dimension: int,
        model_revision: str = "",
        timeout: float = 30.0,
        max_batch: int = 64,
        max_input_chars: int = 8192,
        prefix_scheme: str = PREFIX_SCHEME_E5,
        normalize: bool = True,
        api_key_header: str = "",
        require_pinned_revision: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if dimension <= 0:
            raise ValueError("EMBEDDING_DIMENSION 必须为正")
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = api_key or ""
        self._model = model or "multilingual-e5-small"
        self._dimension = dimension
        self._model_revision = model_revision or ""
        self._timeout = timeout
        self._max_batch = max_batch
        self._max_input_chars = max_input_chars
        self._prefix_scheme = prefix_scheme
        self._normalize = normalize
        self._api_key_header = api_key_header or ""
        self._require_pinned_revision = require_pinned_revision
        self._transport = transport

    def _revision_pinned(self) -> bool:
        return self._model_revision not in _UNPINNED_REVISIONS

    # ---- 身份/能力/健康 ----

    def identity(self) -> EmbeddingIdentity:
        return EmbeddingIdentity(
            provider=self.name,
            model=self._model,
            model_revision=self._model_revision,
            dimension=self._dimension,
            prefix_scheme=self._prefix_scheme,
            embedding_version=make_embedding_version(
                provider=self.name,
                model=self._model,
                model_revision=self._model_revision,
                dimension=self._dimension,
                prefix_scheme=self._prefix_scheme,
            ),
        )

    def capabilities(self) -> EmbeddingCapabilities:
        return EmbeddingCapabilities(
            dimension=self._dimension,
            max_batch=self._max_batch,
            max_input_chars=self._max_input_chars,
            supports_query_passage=self._prefix_scheme == PREFIX_SCHEME_E5,
        )

    def health(self) -> EmbeddingHealth:
        if not self._base_url:
            return EmbeddingHealth(ok=False, detail="缺少 EMBEDDING_BASE_URL", identity=self.identity())
        if self._require_pinned_revision and not self._revision_pinned():
            # fail-closed：未固定 revision 不可用于生产；文档保持可词法/标签检索，仅向量降级
            return EmbeddingHealth(
                ok=False,
                detail="embedding 模型 revision 未固定（设置 EMBEDDING_MODEL_REVISION 为不可变 commit）",
                identity=self.identity(),
            )
        return EmbeddingHealth(ok=True, detail="configured", identity=self.identity())

    # ---- 嵌入 ----

    def _prep(self, text: str, *, is_query: bool) -> str:
        t = (text or "")[: self._max_input_chars]
        if self._prefix_scheme == PREFIX_SCHEME_E5:
            t = apply_e5_prefix(t, is_query=is_query)
        return t

    def _guard_revision(self) -> None:
        if self._require_pinned_revision and not self._revision_pinned():
            raise ProviderNotConfigured(
                "embedding 模型 revision 未固定（设置 EMBEDDING_MODEL_REVISION 为不可变 commit）"
            )

    def embed_query(self, text: str) -> list[float]:
        self._guard_revision()
        return self._embed([self._prep(text, is_query=True)])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._guard_revision()
        if not texts:
            return []
        prepared = [self._prep(t, is_query=False) for t in texts]
        out: list[list[float]] = []
        for i in range(0, len(prepared), self._max_batch):
            out.extend(self._embed(prepared[i : i + self._max_batch]))
        return out

    def _auth_headers(self) -> dict[str, str]:
        if not self._api_key:
            return {}
        if self._api_key_header and self._api_key_header.lower() != "authorization":
            return {self._api_key_header: self._api_key}
        return {"Authorization": f"Bearer {self._api_key}"}

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        body = {"model": self._model, "input": inputs}
        url = f"{self._base_url}/embeddings"
        try:
            with httpx.Client(
                timeout=self._timeout, transport=self._transport, headers=self._auth_headers()
            ) as client:
                resp = client.post(url, json=body)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(str(exc), error_code="timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc

        _raise_for_status(resp)
        vectors = _parse_embeddings(resp, expected=len(inputs))
        result: list[list[float]] = []
        for vec in vectors:
            if len(vec) != self._dimension:
                raise EmbeddingDimensionMismatch(
                    f"维度不符：得到 {len(vec)}，期望 {self._dimension}",
                    http_status=resp.status_code,
                )
            result.append(l2_normalize(vec) if self._normalize else vec)
        return result


def _raise_for_status(resp: httpx.Response) -> None:
    code = resp.status_code
    if code < 400:
        return
    if code in (401, 403):
        raise ProviderAuthError(f"auth {code}", http_status=code)
    if code == 429:
        retry_after = resp.headers.get("retry-after")
        raise ProviderRateLimited(
            "rate limited",
            http_status=code,
            retry_after=float(retry_after) if (retry_after or "").replace(".", "", 1).isdigit() else None,
        )
    if code == 408:
        raise ProviderTimeoutError("request timeout", http_status=code)
    if code >= 500:
        raise ProviderUnavailable(f"server {code}", http_status=code)
    raise ProviderBadResponse(f"http {code}", http_status=code)


def _parse_embeddings(resp: httpx.Response, *, expected: int) -> list[list[float]]:
    try:
        data = resp.json()
        items = data["data"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderBadResponse("响应结构异常（缺 data）") from exc
    if not isinstance(items, list) or len(items) != expected:
        raise ProviderBadResponse(f"data 条数不符：得到 {len(items) if isinstance(items, list) else '?'}，期望 {expected}")
    # 按 index 稳定排序（OpenAI 契约保证返回 index，但不保证顺序）
    try:
        ordered = sorted(items, key=lambda d: int(d.get("index", 0)))
        return [list(d["embedding"]) for d in ordered]
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderBadResponse("响应缺 embedding/index") from exc
