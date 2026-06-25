"""镜头"有效结果"合并（人工优先）+ stale 判定（PR-03B 核心规则）。

有效结果规则（PRD 7.9.4）：
- confirmed / modified → 人工 confirmed_result（source=human，进搜索）；
- unreviewed / pending_review → AI parsed_result 作临时有效结果（source=ai，"尚未确认"）；
- rejected → 无有效结果，不进搜索/推荐（AI 原始仍可查看审计）；
- unable → 无有效结果，不进高置信搜索/推荐。

stale：人工审核绑定的 generation/指纹与当前不一致时失效（重拆镜头或输入变化）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clipmind_shared.models.enums import HUMAN_EFFECTIVE_STATUSES, ReviewStatus


@dataclass
class EffectiveResult:
    result: dict[str, Any] | None  # 有效结构化结果（None=无可用有效结果）
    source: str                    # human | ai | rejected | unable | none
    confirmed: bool                # 是否人工确认
    searchable: bool               # 是否进入搜索/推荐
    review_status: str             # 当前审核状态


def effective_result(
    ai_parsed: dict[str, Any] | None,
    *,
    review_status: str | None,
    confirmed_result: dict[str, Any] | None,
) -> EffectiveResult:
    rs = ReviewStatus(review_status) if review_status else ReviewStatus.UNREVIEWED

    if rs in HUMAN_EFFECTIVE_STATUSES:
        return EffectiveResult(
            result=confirmed_result, source="human", confirmed=True,
            searchable=True, review_status=rs.value,
        )
    if rs == ReviewStatus.REJECTED:
        return EffectiveResult(
            result=None, source="rejected", confirmed=False,
            searchable=False, review_status=rs.value,
        )
    if rs == ReviewStatus.UNABLE:
        return EffectiveResult(
            result=None, source="unable", confirmed=False,
            searchable=False, review_status=rs.value,
        )
    # unreviewed / pending_review → AI 临时有效结果
    if ai_parsed:
        return EffectiveResult(
            result=ai_parsed, source="ai", confirmed=False,
            searchable=True, review_status=rs.value,
        )
    return EffectiveResult(
        result=None, source="none", confirmed=False,
        searchable=False, review_status=rs.value,
    )


def review_stale_reason(
    *,
    review_generation: int,
    current_generation: int,
    review_fingerprint: str | None,
    current_fingerprint: str | None,
) -> str | None:
    """人工审核是否因重拆镜头/输入指纹变化而失效；返回原因或 None。"""
    if review_generation != current_generation:
        return "generation_changed"
    if (
        review_fingerprint
        and current_fingerprint
        and review_fingerprint != current_fingerprint
    ):
        return "fingerprint_changed"
    return None
