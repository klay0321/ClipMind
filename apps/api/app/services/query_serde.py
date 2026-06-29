"""PR-06B：保存搜索 / 动态集合的查询序列化（saved_search 与 dynamic_collection 共用）。

- 序列化：用对应请求模型校验后 dump，去掉 page/page_size/limit 等瞬态视图状态。
- 反序列化：把存库 dict 注回请求模型（pydantic 默认 extra=ignore，兼容旧字段/字段增删），
  re-run 时由调用方注入当前分页参数，按当前真实搜索服务重新计算。
"""

from __future__ import annotations

from clipmind_shared.models.enums import SearchKind

from app.schemas.search import DescriptionMatchRequest, ShotSearchRequest


def serialize_query(search_kind: SearchKind, raw: dict) -> dict:
    """校验并序列化查询（去瞬态分页），返回可入 JSONB 的 dict。非法查询由模型 422 拒绝。"""
    if search_kind == SearchKind.SHOT_SEARCH:
        data = ShotSearchRequest.model_validate(raw).model_dump(mode="json")
        data.pop("page", None)
        data.pop("page_size", None)
        return data
    data = DescriptionMatchRequest.model_validate(raw).model_dump(mode="json")
    data.pop("limit", None)
    return data


def build_shot_search_request(
    stored: dict, *, page: int, page_size: int
) -> ShotSearchRequest:
    """存库查询 → ShotSearchRequest（注入当前分页；旧字段宽容）。"""
    data = dict(stored)
    data["page"] = page
    data["page_size"] = page_size
    return ShotSearchRequest.model_validate(data)


def build_description_match_request(stored: dict, *, limit: int) -> DescriptionMatchRequest:
    """存库查询 → DescriptionMatchRequest（注入当前 limit；旧字段宽容）。"""
    data = dict(stored)
    data["limit"] = limit
    return DescriptionMatchRequest.model_validate(data)
