"""PR-03B 审核合并/投影/标准化/状态机/候选匹配 纯逻辑（供 API 与 PR-04 共用，可单测）。"""

from clipmind_shared.review.effective import (
    EffectiveResult,
    effective_result,
    review_stale_reason,
)
from clipmind_shared.review.matching import Candidate, ProductLike, match_products
from clipmind_shared.review.normalize import normalize_name
from clipmind_shared.review.projection import projected_tags
from clipmind_shared.review.state_machine import (
    InvalidReviewTransition,
    can_transition,
    next_status,
)

__all__ = [
    "EffectiveResult",
    "effective_result",
    "review_stale_reason",
    "normalize_name",
    "projected_tags",
    "next_status",
    "can_transition",
    "InvalidReviewTransition",
    "match_products",
    "ProductLike",
    "Candidate",
]
