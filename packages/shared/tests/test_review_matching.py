"""审核状态机 + 产品候选匹配 纯逻辑测试（PR-03B）。"""

from __future__ import annotations

import pytest

from clipmind_shared.models.enums import ReviewAction as A
from clipmind_shared.models.enums import ReviewStatus as S
from clipmind_shared.review import (
    InvalidReviewTransition,
    ProductLike,
    match_products,
    next_status,
    normalize_name,
)


# ---- 状态机 ----

def test_legal_transitions():
    assert next_status(S.PENDING_REVIEW, A.CONFIRM) == S.CONFIRMED
    assert next_status(S.PENDING_REVIEW, A.MODIFY) == S.MODIFIED
    assert next_status(S.PENDING_REVIEW, A.REJECT) == S.REJECTED
    assert next_status(S.PENDING_REVIEW, A.UNABLE) == S.UNABLE
    assert next_status(S.CONFIRMED, A.MODIFY) == S.MODIFIED
    assert next_status(S.CONFIRMED, A.REJECT) == S.REJECTED
    assert next_status(S.MODIFIED, A.MODIFY) == S.MODIFIED
    assert next_status(S.REJECTED, A.REOPEN) == S.PENDING_REVIEW
    assert next_status(S.UNABLE, A.REOPEN) == S.PENDING_REVIEW
    assert next_status(S.UNREVIEWED, A.CONFIRM) == S.CONFIRMED


@pytest.mark.parametrize(
    "cur,act",
    [
        (S.REJECTED, A.CONFIRM),
        (S.CONFIRMED, A.CONFIRM),
        (S.UNABLE, A.MODIFY),
        (S.PENDING_REVIEW, A.REOPEN),
        (S.REJECTED, A.MODIFY),
    ],
)
def test_illegal_transitions(cur, act):
    with pytest.raises(InvalidReviewTransition):
        next_status(cur, act)


# ---- 候选匹配 ----

def _p(pid, name, **kw):
    return ProductLike(
        id=pid, name=name, brand=kw.get("brand"), model=kw.get("model"),
        sku=kw.get("sku"), normalized_name=normalize_name(name),
        normalized_aliases=[normalize_name(a) for a in kw.get("aliases", [])],
    )


def test_sku_exact_wins():
    c = match_products("PG-X1", [_p(2, "别的"), _p(1, "充电器", sku="pg x1")])
    assert c[0].product_id == 1 and c[0].match_type == "sku"


def test_name_and_alias():
    prods = [_p(1, "PowerGo", aliases=["小钢炮"])]
    assert match_products("powergo", prods)[0].match_type == "name"
    assert match_products("小钢炮", prods)[0].match_type == "alias"


def test_multiple_same_name_returns_multiple():
    c = match_products("充电器", [_p(1, "充电器"), _p(2, "充电器")])
    assert len(c) == 2  # 同名歧义返回多个，不自行选择


def test_no_match_returns_empty():
    assert match_products("完全无关xyz", [_p(1, "充电器")]) == []


def test_stable_sort_by_product_id():
    c = match_products("充电器", [_p(3, "充电器"), _p(1, "充电器")])
    assert [x.product_id for x in c] == [1, 3]


def test_fuzzy_is_candidate_only():
    c = match_products("充电器pro", [_p(1, "充电器")])
    assert c and c[0].match_type in ("contains", "fuzzy")
