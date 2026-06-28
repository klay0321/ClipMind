"""PR-05 Gate B：从 ORM 行装配剪辑清单 ``SegmentView`` 的**会话无关**纯转换。

API（async session）与 export-worker（sync session）各自跑查询，但共用本模块的行→事实、
事实→候选视图、段落→视图转换，确保剪辑清单与 CSV 导出对**同一数据**产出**一致结果**。
"""

from __future__ import annotations

from typing import Any

from clipmind_shared.models.enums import ReviewStatus, ShotStatus, TagType
from clipmind_shared.script import editlist as E

_EXCLUDED_VALUES = (ReviewStatus.REJECTED.value, ReviewStatus.UNABLE.value)
_HUMAN_VALUES = (ReviewStatus.CONFIRMED.value, ReviewStatus.MODIFIED.value)


def term_list(structured: dict | None, key: str) -> list[str]:
    """从段落 structured_requirements 取某键的去重字符串列表。"""
    if not structured:
        return []
    val = structured.get(key)
    if not isinstance(val, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for v in val:
        s = str(v).strip()
        k = s.lower()
        if s and k not in seen:
            seen.add(k)
            out.append(s)
    return out


def effective_source(review_status: str | None, stale_at) -> str:
    """镜头有效标签来源：human（已审核未 stale）否则 ai（与 search/shot_filter 一致）。"""
    if review_status in _HUMAN_VALUES and stale_at is None:
        return "human"
    return "ai"


def new_fact(
    *,
    asset_id: int,
    sequence_no: int,
    start_time: float,
    end_time: float,
    duration: float | None,
    asset_filename: str | None,
    status: Any,
    review_status: Any,
    stale_at: Any,
) -> dict:
    """构造一个镜头事实 dict（标签/产品后续填充）。status/review_status 可为枚举或字符串。"""
    rs = review_status.value if hasattr(review_status, "value") else review_status
    st = status.value if hasattr(status, "value") else status
    is_excluded = rs in _EXCLUDED_VALUES
    return {
        "asset_id": int(asset_id),
        "sequence_no": int(sequence_no),
        "source_start": float(start_time),
        "source_end": float(end_time),
        "source_duration": float(duration or 0.0),
        "asset_filename": asset_filename,
        "review_status": rs,
        "eff_source": effective_source(rs, stale_at),
        "is_valid": (st == ShotStatus.READY.value) and not is_excluded,
        "scene_labels": [],
        "action_labels": [],
        "product_name": None,
    }


def apply_tag(fact: dict, *, source: Any, tag_type: Any, tag_name: str) -> None:
    """把一条标签按"该镜头有效来源"归入场景/动作。"""
    src = source.value if hasattr(source, "value") else source
    if src != fact["eff_source"]:
        return
    tt = tag_type.value if hasattr(tag_type, "value") else tag_type
    if tt == TagType.SCENE.value:
        fact["scene_labels"].append(tag_name)
    elif tt == TagType.ACTION.value:
        fact["action_labels"].append(tag_name)


def candidate_view(candidate, fact: dict | None, *, in_pool: bool) -> E.CandidateView:
    """ScriptShotCandidate + 镜头事实 → CandidateView。"""
    f = fact or {}
    return E.CandidateView(
        shot_id=candidate.shot_id,
        asset_id=f.get("asset_id", 0),
        rank=candidate.rank,
        final_score=candidate.final_score,
        semantic_score=candidate.semantic_score,
        lexical_score=candidate.lexical_score,
        tag_score=candidate.tag_score,
        product_score=candidate.product_score,
        quality_score=candidate.quality_score,
        review_bonus=candidate.review_bonus,
        risk_penalty=candidate.risk_penalty,
        matched_reasons=list(candidate.matched_reasons or []),
        unmatched_requirements=list(candidate.unmatched_requirements or []),
        risk_warnings=list(candidate.risk_warnings or []),
        sequence_no=f.get("sequence_no", 0),
        source_start=f.get("source_start", 0.0),
        source_end=f.get("source_end", 0.0),
        source_duration=f.get("source_duration", 0.0),
        asset_filename=f.get("asset_filename"),
        product_name=f.get("product_name"),
        scene_labels=f.get("scene_labels", []),
        action_labels=f.get("action_labels", []),
        review_status=f.get("review_status"),
        is_valid=f.get("is_valid", False),
        in_candidate_pool=in_pool,
    )


def override_view(shot_id: int, fact: dict | None) -> E.CandidateView:
    """锁定/选择的 override 镜头（不在当前候选）→ 仅镜头事实，scores 置 None。"""
    f = fact or {}
    return E.CandidateView(
        shot_id=shot_id,
        asset_id=f.get("asset_id", 0),
        rank=-1,
        final_score=None,
        sequence_no=f.get("sequence_no", 0),
        source_start=f.get("source_start", 0.0),
        source_end=f.get("source_end", 0.0),
        source_duration=f.get("source_duration", 0.0),
        asset_filename=f.get("asset_filename"),
        product_name=f.get("product_name"),
        scene_labels=f.get("scene_labels", []),
        action_labels=f.get("action_labels", []),
        review_status=f.get("review_status"),
        is_valid=f.get("is_valid", False),
        in_candidate_pool=False,
    )


def assemble_segment_view(segment, candidate_views: list[E.CandidateView]) -> E.SegmentView:
    """ScriptSegment + 候选视图（含 override）→ SegmentView。"""
    structured = segment.structured_requirements or {}
    return E.SegmentView(
        segment_id=segment.id,
        order_index=segment.order_index,
        segment_text=segment.segment_text,
        visual_requirement=segment.visual_requirement,
        product_id=segment.product_id,
        scenes=term_list(structured, "scenes"),
        actions=term_list(structured, "actions"),
        shot_types=term_list(structured, "shot_types"),
        marketing_uses=term_list(structured, "marketing_uses"),
        excluded_risks=list(segment.excluded_risks or []),
        negative_terms=list(segment.negative_terms or []),
        allow_similar_scene=segment.allow_similar_scene,
        allow_similar_action=segment.allow_similar_action,
        target_duration_min=segment.target_duration_min,
        target_duration_max=segment.target_duration_max,
        current_generation=segment.current_generation,
        match_status=segment.match_status,
        selected_shot_id=segment.selected_shot_id,
        locked_shot_id=segment.locked_shot_id,
        candidates=candidate_views,
        match_summary=segment.match_summary,
    )
