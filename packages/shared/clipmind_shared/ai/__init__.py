"""AI Provider 接口骨架（PR-01 仅预留边界，PR-03 实现真实 MiMo provider）。"""

from clipmind_shared.ai.provider import (
    AIProvider,
    NotConfiguredProvider,
    ProviderCapabilities,
    ProviderHealth,
)

__all__ = [
    "AIProvider",
    "ProviderCapabilities",
    "ProviderHealth",
    "NotConfiguredProvider",
]
