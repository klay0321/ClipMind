"""视觉分析 provider 的具体契约与共享类型（PR-03A）。

在 PR-01 的高层 ``AIProvider`` 协议之上，定义 PR-03A 真正使用的视觉分析接口
``VisualAnalysisProvider`` 与输入/输出/异常类型。FakeProvider / MiMoProvider 实现之。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from clipmind_shared.ai.provider import ProviderCapabilities, ProviderHealth


@dataclass
class FrameRef:
    """一个关键帧输入：绝对路径 + 可选预算的内容 sha256（用于指纹）。"""

    path: str
    sha256: str | None = None


@dataclass
class Usage:
    """单次调用用量（用于成本台账；未知留 None）。"""

    input_tokens: int | None = None
    output_tokens: int | None = None
    input_images: int = 0


@dataclass
class AnalyzeOutcome:
    """provider 单次分析返回。

    parsed 为结构化 JSON dict（由编排层用 Schema 校验）；降级时 parsed 为 None 且
    degraded=True（绝不伪造视觉结果）。raw_excerpt 为脱敏截断的原始响应。
    """

    parsed: dict | None
    raw_excerpt: str
    usage: Usage
    model: str
    method: str = "analyze_frames"
    degraded: bool = False
    degraded_reason: str | None = None
    http_status: int | None = None


# ---- 异常分类（编排层据此决定重试/退避/失败）----


class ProviderError(Exception):
    error_code = "provider_error"

    def __init__(
        self,
        message: str = "",
        *,
        http_status: int | None = None,
        error_code: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        if error_code:
            self.error_code = error_code
        self.retry_after = retry_after


class ProviderNotConfigured(ProviderError):
    error_code = "not_configured"


class ProviderAuthError(ProviderError):
    error_code = "auth_error"


class ProviderTimeoutError(ProviderError):
    error_code = "timeout"


class ProviderRateLimited(ProviderError):
    error_code = "rate_limited"


class ProviderBadResponse(ProviderError):
    """响应不可解析 / 非合法 JSON / Schema 校验失败。"""

    error_code = "bad_response"


class ProviderUnavailable(ProviderError):
    error_code = "unavailable"


@runtime_checkable
class VisualAnalysisProvider(Protocol):
    """视觉（多关键帧）画面理解 provider 契约。"""

    name: str

    def capabilities(self) -> ProviderCapabilities: ...

    def health(self) -> ProviderHealth: ...

    def analyze_frames(
        self,
        frames: list[FrameRef],
        *,
        prompt: str,
        schema: dict,
        timeout: float = 30.0,
    ) -> AnalyzeOutcome: ...
