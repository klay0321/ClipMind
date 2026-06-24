"""MiMoProvider：OpenAI 兼容的视觉分析 provider（PR-03A）。

通过 ``/chat/completions`` 发送系统提示词 + 多关键帧（Base64 内联图）请求结构化 JSON。
能力（是否支持图片等）由 ``scripts/probe_ai_provider.py`` 探测后据实配置；运行时据
``ProviderCapabilities`` 决定是否降级。**密钥仅置于请求头，绝不写日志/库/返回。**

错误分类便于编排层据 ``ProviderError`` 子类重试/退避/失败：
401/403→Auth、429→RateLimited、408/超时→Timeout、5xx→Unavailable、2xx 不可解析→BadResponse。
"""

from __future__ import annotations

import base64
import json
import mimetypes

import httpx

from clipmind_shared.ai.provider import ProviderCapabilities, ProviderHealth
from clipmind_shared.ai.providers.base import (
    AnalyzeOutcome,
    FrameRef,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderTimeoutError,
    ProviderUnavailable,
    Usage,
)

_USER_HINT = "请仅根据下列关键帧画面，输出符合给定 JSON Schema 的结构化 JSON。"


def _data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/webp"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _strip_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
        # 去掉可能残留的语言标记行已在上面的 split 处理
    return s.strip()


class MiMoProvider:
    name = "mimo"

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
        timeout: float = 60.0,
        max_images: int = 8,
        supports_images: bool = True,
        context_window: int = 0,
        # 鉴权头：空/"authorization" → "Authorization: Bearer <key>"；
        # 其它（如 "api-key"）→ "<header>: <key>"（类 Azure 风格，MiMo token-plan 端点用此）
        api_key_header: str = "",
        max_completion_tokens: int = 0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = api_key or ""
        self._model = model or "mimo-v2.5"
        self._timeout = timeout
        self._max_images = max_images
        self._supports_images = supports_images
        self._context_window = context_window
        self._api_key_header = api_key_header or ""
        self._max_completion_tokens = max_completion_tokens
        self._transport = transport

    def _auth_headers(self) -> dict[str, str]:
        if self._api_key_header and self._api_key_header.lower() != "authorization":
            return {self._api_key_header: self._api_key}
        return {"Authorization": f"Bearer {self._api_key}"}

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_images=self._supports_images,
            supports_video=False,
            supports_structured_output=True,
            supports_embeddings=False,
            max_images_per_call=self._max_images,
            context_window=self._context_window,
        )

    def health(self) -> ProviderHealth:
        ok = bool(self._base_url and self._api_key)
        return ProviderHealth(
            ok=ok,
            detail="configured" if ok else "缺少 AI_BASE_URL / AI_API_KEY",
            capabilities=self.capabilities(),
        )

    def _client(self) -> httpx.Client:
        # 不设 base_url：POST 绝对 URL，避免 "/v1" 前缀被相对路径覆盖
        return httpx.Client(
            timeout=self._timeout,
            transport=self._transport,
            headers=self._auth_headers(),
        )

    def analyze_frames(
        self,
        frames: list[FrameRef],
        *,
        prompt: str,
        schema: dict,
        timeout: float | None = None,
    ) -> AnalyzeOutcome:
        content: list[dict] = [{"type": "text", "text": _USER_HINT}]
        used = 0
        for f in frames[: self._max_images]:
            content.append({"type": "image_url", "image_url": {"url": _data_url(f.path)}})
            used += 1
        body: dict = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": content},
            ],
        }
        if self._max_completion_tokens > 0:
            body["max_completion_tokens"] = self._max_completion_tokens
        url = f"{self._base_url}/chat/completions"
        try:
            with self._client() as client:
                resp = client.post(url, json=body, timeout=timeout or self._timeout)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(str(exc), error_code="timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc

        _raise_for_status(resp)
        text = _extract_text(resp)
        parsed = _parse_json(text)
        usage = _usage(resp, used)
        model = _safe_model(resp) or self._model
        return AnalyzeOutcome(
            parsed=parsed,
            raw_excerpt=text[:512],
            usage=usage,
            model=model,
            http_status=resp.status_code,
        )


def _raise_for_status(resp: httpx.Response) -> None:
    code = resp.status_code
    if code < 400:
        return
    if code in (401, 403):
        raise ProviderAuthError(f"auth {code}", http_status=code)
    if code == 429:
        retry_after = resp.headers.get("retry-after")
        raise ProviderRateLimited(
            "rate limited", http_status=code,
            retry_after=float(retry_after) if (retry_after or "").replace(".", "", 1).isdigit() else None,
        )
    if code == 408:
        raise ProviderTimeoutError("request timeout", http_status=code)
    if code >= 500:
        raise ProviderUnavailable(f"server {code}", http_status=code)
    raise ProviderBadResponse(f"http {code}", http_status=code)


def _extract_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ProviderBadResponse("响应结构异常") from exc


def _parse_json(text: str) -> dict:
    try:
        obj = json.loads(_strip_fences(text))
    except json.JSONDecodeError as exc:
        raise ProviderBadResponse("响应非合法 JSON") from exc
    if not isinstance(obj, dict):
        raise ProviderBadResponse("响应 JSON 非对象")
    return obj


def _usage(resp: httpx.Response, used_images: int) -> Usage:
    try:
        u = resp.json().get("usage") or {}
    except ValueError:
        u = {}
    return Usage(
        input_tokens=u.get("prompt_tokens"),
        output_tokens=u.get("completion_tokens"),
        input_images=used_images,
    )


def _safe_model(resp: httpx.Response) -> str | None:
    try:
        return resp.json().get("model")
    except ValueError:
        return None
