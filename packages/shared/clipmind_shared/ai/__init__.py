"""AI 能力层：高层接口骨架（PR-01）+ PR-03A 视觉分析实现与契约。"""

from clipmind_shared.ai.factory import NotConfiguredVisualProvider, get_provider
from clipmind_shared.ai.fingerprint import compute_fingerprint, hash_bytes, hash_file
from clipmind_shared.ai.prompt import PROMPT_VERSION, build_analysis_prompt
from clipmind_shared.ai.provider import (
    AIProvider,
    NotConfiguredProvider,
    ProviderCapabilities,
    ProviderHealth,
)
from clipmind_shared.ai.providers.base import (
    AnalyzeOutcome,
    FrameRef,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderError,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderTimeoutError,
    ProviderUnavailable,
    Usage,
    VisualAnalysisProvider,
)
from clipmind_shared.ai.providers.fake import FakeProvider
from clipmind_shared.ai.schema import (
    SHOT_ANALYSIS_SCHEMA_VERSION,
    ProductInfo,
    ShotAnalysisResult,
    shot_analysis_json_schema,
    validate_shot_analysis,
)

__all__ = [
    # PR-01 高层骨架
    "AIProvider",
    "ProviderCapabilities",
    "ProviderHealth",
    "NotConfiguredProvider",
    # PR-03A 视觉分析契约 / 实现
    "VisualAnalysisProvider",
    "FrameRef",
    "Usage",
    "AnalyzeOutcome",
    "FakeProvider",
    "NotConfiguredVisualProvider",
    "get_provider",
    # 异常
    "ProviderError",
    "ProviderNotConfigured",
    "ProviderAuthError",
    "ProviderTimeoutError",
    "ProviderRateLimited",
    "ProviderBadResponse",
    "ProviderUnavailable",
    # Schema / 指纹 / 提示词
    "ShotAnalysisResult",
    "ProductInfo",
    "SHOT_ANALYSIS_SCHEMA_VERSION",
    "shot_analysis_json_schema",
    "validate_shot_analysis",
    "compute_fingerprint",
    "hash_bytes",
    "hash_file",
    "PROMPT_VERSION",
    "build_analysis_prompt",
]
