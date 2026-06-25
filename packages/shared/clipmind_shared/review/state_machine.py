"""审核状态机（显式转换；禁止任意字符串更新）。

支持转换（非法转换抛 InvalidReviewTransition，API 映射为 409）：
  unreviewed → pending_review（reopen，进入审核）
  unreviewed → confirmed/modified/rejected/unable（直接审核入口）
  pending_review → confirmed/modified/rejected/unable
  confirmed → modified/rejected/reopen(pending)
  modified → modified/rejected/reopen(pending)
  rejected → reopen(pending)
  unable → reopen(pending)
"""

from __future__ import annotations

from clipmind_shared.models.enums import ReviewAction, ReviewStatus

_S = ReviewStatus
_A = ReviewAction

# action → 目标状态
_TARGET: dict[ReviewAction, ReviewStatus] = {
    _A.CONFIRM: _S.CONFIRMED,
    _A.MODIFY: _S.MODIFIED,
    _A.REJECT: _S.REJECTED,
    _A.UNABLE: _S.UNABLE,
}

# action → 允许的来源状态集合
_ALLOWED_FROM: dict[ReviewAction, set[ReviewStatus]] = {
    _A.CONFIRM: {_S.UNREVIEWED, _S.PENDING_REVIEW},
    _A.MODIFY: {_S.UNREVIEWED, _S.PENDING_REVIEW, _S.CONFIRMED, _S.MODIFIED},
    _A.REJECT: {_S.UNREVIEWED, _S.PENDING_REVIEW, _S.CONFIRMED, _S.MODIFIED},
    _A.UNABLE: {_S.UNREVIEWED, _S.PENDING_REVIEW},
    _A.REOPEN: {_S.UNREVIEWED, _S.CONFIRMED, _S.MODIFIED, _S.REJECTED, _S.UNABLE},
}


class InvalidReviewTransition(Exception):
    """非法审核状态转换。"""

    def __init__(self, current: ReviewStatus, action: ReviewAction) -> None:
        super().__init__(f"非法转换: {current.value} --{action.value}-->")
        self.current = current
        self.action = action


def next_status(current: ReviewStatus, action: ReviewAction) -> ReviewStatus:
    allowed = _ALLOWED_FROM.get(action, set())
    if current not in allowed:
        raise InvalidReviewTransition(current, action)
    if action == _A.REOPEN:
        return _S.PENDING_REVIEW
    return _TARGET[action]


def can_transition(current: ReviewStatus, action: ReviewAction) -> bool:
    return current in _ALLOWED_FROM.get(action, set())
