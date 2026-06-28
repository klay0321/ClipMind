"""PR-05 Gate B：剪辑清单纯逻辑测试（无 DB，完全确定性）。

覆盖：时长建议 / 全局分配（去重·相邻差异·锁定·缺口·重复·确定性）/ 缺口与补拍派生 /
剪辑清单行与摘要 / CSV（BOM·转义·公式注入·无匹配成行·稳定列）。
"""

from __future__ import annotations

import csv
import io

from clipmind_shared.script import editlist as E


def _cv(shot_id, asset_id, rank, score, **kw):
    return E.CandidateView(
        shot_id=shot_id, asset_id=asset_id, rank=rank, final_score=score,
        source_start=kw.get("s", 0.0), source_end=kw.get("e", 5.0),
        source_duration=kw.get("e", 5.0) - kw.get("s", 0.0),
        scene_labels=kw.get("sc", []), action_labels=kw.get("ac", []),
        matched_reasons=kw.get("mr", []), risk_warnings=kw.get("rw", []),
        product_name=kw.get("pn"), is_valid=kw.get("valid", True),
        in_candidate_pool=kw.get("pool", True),
    )


# ---------------- 时长建议 ----------------


def test_duration_fit():
    d = E.compute_duration_suggestion(source_start=0.0, source_end=2.5, target_min=2.0, target_max=3.0)
    assert d.status == "fit"
    assert d.suggested_in == 0.0 and d.suggested_out == 2.5
    assert d.needs_trim is False


def test_duration_too_long_trims_within_range():
    d = E.compute_duration_suggestion(source_start=1.0, source_end=10.0, target_min=2.0, target_max=4.0)
    assert d.status == "too_long" and d.needs_trim is True
    assert d.suggested_in == 1.0 and d.suggested_out == 5.0  # 不超出 source_end
    assert d.suggested_duration == 4.0
    assert d.suggested_out <= 10.0


def test_duration_too_short_keeps_full_and_warns():
    d = E.compute_duration_suggestion(source_start=0.0, source_end=1.0, target_min=3.0, target_max=5.0)
    assert d.status == "too_short" and d.needs_trim is False
    assert d.suggested_in == 0.0 and d.suggested_out == 1.0
    assert d.warnings and "补画面" in d.warnings[0]


def test_duration_no_target():
    d = E.compute_duration_suggestion(source_start=0.0, source_end=4.0, target_min=None, target_max=None)
    assert d.status == "no_target" and d.diff is None


def test_duration_never_exceeds_source():
    d = E.compute_duration_suggestion(source_start=2.0, source_end=3.0, target_min=None, target_max=10.0)
    assert d.suggested_out <= 3.0 and d.suggested_in >= 2.0


# ---------------- 全局分配 ----------------


def test_allocate_dedup_avoids_reuse():
    s1 = E.SegmentView(segment_id=1, order_index=0, segment_text="a", match_status="matched",
                       candidates=[_cv(10, 100, 0, 0.9), _cv(11, 101, 1, 0.85)])
    s2 = E.SegmentView(segment_id=2, order_index=1, segment_text="b", match_status="matched",
                       candidates=[_cv(10, 100, 0, 0.88), _cv(12, 102, 1, 0.84)])
    alloc = E.allocate([s1, s2])
    assert alloc[1].shot_id == 10
    assert alloc[2].shot_id == 12  # 去重避免复用 10
    assert alloc[1].reused is False and alloc[2].reused is False


def test_allocate_reuse_when_no_alternative_warns():
    s1 = E.SegmentView(segment_id=1, order_index=0, segment_text="a", match_status="matched",
                       candidates=[_cv(10, 100, 0, 0.9)])
    s2 = E.SegmentView(segment_id=2, order_index=1, segment_text="b", match_status="matched",
                       candidates=[_cv(10, 100, 0, 0.9)])  # 仅一个候选
    alloc = E.allocate([s1, s2])
    assert alloc[1].shot_id == 10 and alloc[2].shot_id == 10
    assert alloc[1].reused and alloc[2].reused
    assert any("重复" in w for w in alloc[2].warnings)


def test_allocate_no_dedup_if_quality_drop_too_large():
    # 唯一去重替代远逊（0.9 → 0.5，超过 DEDUP_MAX_SCORE_DROP）→ 宁可重复也不明显降质
    s1 = E.SegmentView(segment_id=1, order_index=0, segment_text="a", match_status="matched",
                       candidates=[_cv(10, 100, 0, 0.9)])
    s2 = E.SegmentView(segment_id=2, order_index=1, segment_text="b", match_status="matched",
                       candidates=[_cv(10, 100, 0, 0.9), _cv(13, 103, 1, 0.5)])
    alloc = E.allocate([s1, s2])
    assert alloc[2].shot_id == 10  # 保留 top（重复），不选明显更差的 13


def test_allocate_locked_invalid_not_swapped():
    s = E.SegmentView(segment_id=1, order_index=0, segment_text="a", match_status="matched",
                      locked_shot_id=99,
                      candidates=[_cv(99, 109, -1, None, valid=False, pool=False)])
    alloc = E.allocate([s])
    assert alloc[1].shot_id == 99 and alloc[1].source == "locked"
    assert alloc[1].shot_invalid is True


def test_allocate_gap_when_no_candidates():
    s = E.SegmentView(segment_id=1, order_index=0, segment_text="a", match_status="gap", candidates=[])
    alloc = E.allocate([s])
    assert alloc[1].shot_id is None and alloc[1].source == "gap"


def test_allocate_deterministic():
    segs = [
        E.SegmentView(segment_id=i, order_index=i, segment_text=str(i), match_status="matched",
                      candidates=[_cv(10, 100, 0, 0.9), _cv(20 + i, 200 + i, 1, 0.8)])
        for i in range(5)
    ]
    a1 = {k: v.shot_id for k, v in E.allocate(segs).items()}
    a2 = {k: v.shot_id for k, v in E.allocate(segs).items()}
    assert a1 == a2


def test_allocate_selected_priority_over_recommended():
    s = E.SegmentView(segment_id=1, order_index=0, segment_text="a", match_status="matched",
                      selected_shot_id=11,
                      candidates=[_cv(10, 100, 0, 0.9), _cv(11, 101, 1, 0.5)])
    alloc = E.allocate([s])
    assert alloc[1].shot_id == 11 and alloc[1].source == "selected"


# ---------------- 缺口 / 补拍派生 ----------------


def test_derive_outcome_matched():
    sv = E.SegmentView(segment_id=1, order_index=0, segment_text="a")
    o = E.derive_match_outcome(sv, candidate_count=3, best_score=0.8, degraded=False)
    assert o["match_status"] == "matched" and o["gap_reasons"] == []
    assert o["requires_human_confirmation"] is False  # 高分人工无需


def test_derive_outcome_low_score_requires_human():
    sv = E.SegmentView(segment_id=1, order_index=0, segment_text="a")
    o = E.derive_match_outcome(sv, candidate_count=2, best_score=0.3, degraded=False)
    assert o["requires_human_confirmation"] is True


def test_derive_outcome_gap_product():
    sv = E.SegmentView(segment_id=1, order_index=0, segment_text="a", product_id=7, product_name="吹风机")
    o = E.derive_match_outcome(sv, candidate_count=0, best_score=None, degraded=False)
    assert o["match_status"] == "gap"
    assert any("吹风机" in r for r in o["gap_reasons"])
    assert any("吹风机" in r for r in o["reshoot_recommendation"])
    assert o["requires_human_confirmation"] is True


def test_derive_outcome_gap_scene_action_hard():
    sv = E.SegmentView(segment_id=1, order_index=0, segment_text="a",
                       scenes=["户外"], actions=["安装"],
                       allow_similar_scene=False, allow_similar_action=False)
    o = E.derive_match_outcome(sv, candidate_count=0, best_score=None, degraded=False)
    assert any("户外" in r for r in o["gap_reasons"])
    assert any("安装" in r for r in o["gap_reasons"])


def test_derive_outcome_degraded_flag():
    sv = E.SegmentView(segment_id=1, order_index=0, segment_text="a")
    o = E.derive_match_outcome(sv, candidate_count=2, best_score=0.9, degraded=True)
    assert o["match_status"] == "degraded" and o["degraded"] is True
    assert o["requires_human_confirmation"] is True


# ---------------- 剪辑清单行 / 摘要 ----------------


def _editlist_segments():
    s1 = E.SegmentView(segment_id=1, order_index=0, segment_text="开场", match_status="matched",
                       target_duration_min=2.0, target_duration_max=3.0,
                       candidates=[_cv(10, 100, 0, 0.9, e=8.0, rw=["风险提示：水印"])])
    s2 = E.SegmentView(segment_id=2, order_index=1, segment_text="卖点", match_status="matched",
                       selected_shot_id=12,
                       candidates=[_cv(12, 102, 0, 0.7)])
    s3 = E.SegmentView(segment_id=3, order_index=2, segment_text="缺口", match_status="gap",
                       match_summary={"gap_reasons": ["无符合产品硬约束的镜头：A"],
                                      "reshoot_recommendation": ["补拍 A 特写"],
                                      "requires_human_confirmation": True}, candidates=[])
    return [s1, s2, s3]


def test_build_edit_list_counts_and_no_match_row():
    rows, summ = E.build_edit_list(_editlist_segments())
    assert len(rows) == 3
    assert summ.total_segments == 3 and summ.gap_segments == 1
    assert summ.selected_segments == 1 and summ.recommended_segments == 1
    assert summ.risk_segments == 1
    # 推荐行不得标成人工已选
    assert rows[0].selection_status == "recommended"
    assert rows[1].selection_status == "selected"
    assert rows[2].selection_status == "none" and rows[2].shot_id is None
    assert rows[2].gap_reasons and rows[2].reshoot_recommendation


def test_build_edit_list_duration_in_row():
    rows, _ = E.build_edit_list(_editlist_segments())
    assert rows[0].duration_status == "too_long"
    assert rows[0].suggested_duration == 3.0


# ---------------- CSV ----------------


def test_csv_bom_and_headers():
    rows, _ = E.build_edit_list(_editlist_segments())
    data = E.to_csv(rows)
    assert data[:3] == b"\xef\xbb\xbf"
    text = data[3:].decode("utf-8")
    reader = list(csv.reader(io.StringIO(text)))
    assert reader[0] == E.csv_headers()
    assert len(reader) == 1 + 3  # 表头 + 3 段（含无匹配段）


def test_csv_escapes_comma_quote_newline():
    s = E.SegmentView(segment_id=1, order_index=0, segment_text='含,逗号"引号"\n换行',
                      match_status="matched", candidates=[_cv(10, 100, 0, 0.9)])
    rows, _ = E.build_edit_list([s])
    text = E.to_csv(rows)[3:].decode("utf-8")
    parsed = list(csv.reader(io.StringIO(text)))
    # csv 正确解析回原文（RFC4180 转义无损）
    assert parsed[1][1] == '含,逗号"引号"\n换行'


def test_csv_formula_injection_guarded():
    for danger in ["=SUM(A1)", "+1", "-2+3", "@x"]:
        s = E.SegmentView(segment_id=1, order_index=0, segment_text=danger,
                          match_status="matched", candidates=[_cv(10, 100, 0, 0.9)])
        rows, _ = E.build_edit_list([s])
        text = E.to_csv(rows)[3:].decode("utf-8")
        cell = list(csv.reader(io.StringIO(text)))[1][1]
        assert cell.startswith("'"), f"{danger!r} 未被防护: {cell!r}"


def test_csv_numbers_not_guarded():
    s = E.SegmentView(segment_id=1, order_index=0, segment_text="正常",
                      match_status="matched", target_duration_min=2.0,
                      candidates=[_cv(10, 100, 0, 0.9)])
    rows, _ = E.build_edit_list([s])
    text = E.to_csv(rows)[3:].decode("utf-8")
    cells = list(csv.reader(io.StringIO(text)))[1]
    assert cells[0] == "1"  # 段落序号
