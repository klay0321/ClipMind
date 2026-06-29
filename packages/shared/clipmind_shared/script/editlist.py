"""PR-05 Gate B：剪辑清单与 CSV 的**纯逻辑**（无 DB、无网络、完全确定性）。

职责（API async 层与 export-worker sync 层共用同一套逻辑，各自只负责取数）：
- 全局镜头分配（去重 / 相邻差异 / 锁定优先 / 不为去重选明显更差镜头）；
- 时长适配建议（在范围内/偏短/偏长、建议入出点，绝不超出原始 shot 范围，本阶段只建议不裁切）；
- 缺口与补拍提示（规则派生，绝不编造素材事实）；
- 剪辑清单行 + 整体摘要；
- CSV 序列化（UTF-8 BOM、RFC4180 转义、CSV 公式注入防护、稳定列顺序、无匹配也成行）。

确定性：同一输入永远产生同一输出（无随机、无时间依赖；时间戳由调用方注入）。
"""

from __future__ import annotations

import csv
import dataclasses as _dc
import html as _html
import io
import json as _json
from dataclasses import dataclass, field

# 候选数量约定（每段）
DEFAULT_CANDIDATE_LIMIT = 10
MAX_CANDIDATE_LIMIT = 50

# 全局分配参数
DEFAULT_MAX_REUSE = 1          # 单个 shot 默认最多被分配给 1 个段落（超出触发去重）
# 为去重切换到候选时，允许的最大综合分下降；超过则保留 top（宁可重复也不明显降质）
DEDUP_MAX_SCORE_DROP = 0.2
# 低于该综合分的"系统推荐"标注为需人工复核
HIGH_CONFIDENCE_SCORE = 0.6

# CSV 注入危险前缀（Excel/Sheets 会把以这些字符开头的单元格当公式执行）
_CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


# ============================ 输入快照（调用方从 DB 组装） ============================


@dataclass
class CandidateView:
    """候选镜头快照（来自 script_shot_candidate + 关联 shot/asset/产品/标签）。

    锁定/选择的 override 镜头若不在当前代次候选中，调用方仍构造一个 CandidateView 放入
    ``candidates``（scores 置 None，``in_candidate_pool=False``），保证清单能取到其镜头事实。
    """

    shot_id: int
    asset_id: int
    rank: int
    final_score: float | None
    semantic_score: float | None = None
    lexical_score: float | None = None
    tag_score: float | None = None
    product_score: float | None = None
    quality_score: float | None = None
    review_bonus: float | None = None
    risk_penalty: float | None = None
    matched_reasons: list[str] = field(default_factory=list)
    unmatched_requirements: list[str] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)
    # 镜头事实
    sequence_no: int = 0
    source_start: float = 0.0
    source_end: float = 0.0
    source_duration: float = 0.0
    asset_filename: str | None = None
    product_name: str | None = None
    scene_labels: list[str] = field(default_factory=list)
    action_labels: list[str] = field(default_factory=list)
    review_status: str | None = None
    # 有效性：当前是否仍 READY 且未被审核排除（rejected/unable）。失效不静默换片，仅标注。
    is_valid: bool = True
    in_candidate_pool: bool = True


@dataclass
class SegmentView:
    """段落快照 + 当前代次候选 + 人工选择/锁定状态 + 上次匹配摘要。"""

    segment_id: int
    order_index: int
    segment_text: str
    visual_requirement: str | None = None
    product_id: int | None = None
    product_name: str | None = None
    scenes: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    shot_types: list[str] = field(default_factory=list)
    marketing_uses: list[str] = field(default_factory=list)
    excluded_risks: list[str] = field(default_factory=list)
    negative_terms: list[str] = field(default_factory=list)
    allow_similar_scene: bool = True
    allow_similar_action: bool = True
    target_duration_min: float | None = None
    target_duration_max: float | None = None
    current_generation: int = 1
    match_status: str = "pending"
    selected_shot_id: int | None = None
    locked_shot_id: int | None = None
    candidates: list[CandidateView] = field(default_factory=list)
    match_summary: dict | None = None


# ============================ 时长建议 ============================


@dataclass
class DurationSuggestion:
    source_start: float
    source_end: float
    source_duration: float
    suggested_in: float
    suggested_out: float
    suggested_duration: float
    status: str            # fit | too_long | too_short | no_target
    diff: float | None     # source_duration - 最近目标边界（fit=0；no_target=None）
    needs_trim: bool
    warnings: list[str]


def _round(x: float | None, n: int = 3) -> float | None:
    return round(x, n) if x is not None else None


def compute_duration_suggestion(
    *,
    source_start: float,
    source_end: float,
    target_min: float | None,
    target_max: float | None,
) -> DurationSuggestion:
    """从原始 shot 时间码 + 段目标时长推导建议入/出点（绝不超出 [source_start, source_end]）。"""
    start = float(source_start)
    end = float(source_end)
    src_dur = max(0.0, end - start)
    warnings: list[str] = []

    if target_min is None and target_max is None:
        return DurationSuggestion(
            source_start=start, source_end=end, source_duration=round(src_dur, 3),
            suggested_in=start, suggested_out=end, suggested_duration=round(src_dur, 3),
            status="no_target", diff=None, needs_trim=False, warnings=warnings,
        )

    if target_max is not None and src_dur > target_max + 1e-6:
        # 偏长：建议从入点裁切到目标上限（不超出原范围）
        out = min(end, start + target_max)
        warnings.append(f"镜头偏长，建议裁切约 {src_dur - target_max:.2f}s")
        return DurationSuggestion(
            source_start=start, source_end=end, source_duration=round(src_dur, 3),
            suggested_in=start, suggested_out=round(out, 3),
            suggested_duration=round(min(target_max, out - start), 3),
            status="too_long", diff=round(src_dur - target_max, 3),
            needs_trim=True, warnings=warnings,
        )

    if target_min is not None and src_dur < target_min - 1e-6:
        # 偏短：保留整段，提示需补画面/慢放（不伪造超出原范围的时间码）
        warnings.append(f"镜头偏短，缺约 {target_min - src_dur:.2f}s，需补画面或慢放")
        return DurationSuggestion(
            source_start=start, source_end=end, source_duration=round(src_dur, 3),
            suggested_in=start, suggested_out=end, suggested_duration=round(src_dur, 3),
            status="too_short", diff=round(src_dur - target_min, 3),
            needs_trim=False, warnings=warnings,
        )

    # 在范围内（或仅满足单边约束）
    return DurationSuggestion(
        source_start=start, source_end=end, source_duration=round(src_dur, 3),
        suggested_in=start, suggested_out=end, suggested_duration=round(src_dur, 3),
        status="fit", diff=0.0, needs_trim=False, warnings=warnings,
    )


# ============================ 缺口 / 补拍提示（规则派生） ============================


def derive_match_outcome(
    seg: SegmentView,
    *,
    candidate_count: int,
    best_score: float | None,
    degraded: bool,
) -> dict:
    """匹配后规则派生 match_status / gap_reasons / reshoot_recommendation / requires_human。

    绝不由 LLM 编造素材事实：缺口原因只陈述"段落要求了 X 但未找到符合硬约束的镜头"，
    补拍提示只按要求类型给出（产品特写 / 场景 / 动作 等）。
    """
    if candidate_count > 0:
        status = "degraded" if degraded else "matched"
        requires_human = (
            best_score is None or best_score < HIGH_CONFIDENCE_SCORE or degraded
        )
        return {
            "match_status": status,
            "candidate_count": candidate_count,
            "best_score": _round(best_score, 4),
            "gap_reasons": [],
            "reshoot_recommendation": [],
            "requires_human_confirmation": bool(requires_human),
            "degraded": bool(degraded),
        }

    # 无候选 → 真实缺口
    gap_reasons: list[str] = []
    reshoot: list[str] = []
    if seg.product_id is not None:
        name = seg.product_name or f"产品#{seg.product_id}"
        gap_reasons.append(f"无符合产品硬约束的镜头：{name}")
        reshoot.append(f"补拍产品「{name}」的特写/使用镜头")
    if not seg.allow_similar_scene and seg.scenes:
        scenes = "、".join(seg.scenes[:5])
        gap_reasons.append(f"缺少要求场景：{scenes}")
        reshoot.append(f"补拍场景：{scenes}")
    if not seg.allow_similar_action and seg.actions:
        actions = "、".join(seg.actions[:5])
        gap_reasons.append(f"缺少要求动作：{actions}")
        reshoot.append(f"补拍动作：{actions}")
    if seg.excluded_risks:
        gap_reasons.append(f"排除风险后无可用镜头（排除：{'、'.join(seg.excluded_risks[:5])}）")
    if degraded:
        gap_reasons.append("检索降级（embedding 不可用），结果可能不完整，建议恢复后重试")
    if not gap_reasons:
        gap_reasons.append("现有素材库无符合该段画面要求的镜头")
        reshoot.append("补拍符合该段画面描述的镜头")

    return {
        "match_status": "gap",
        "candidate_count": 0,
        "best_score": None,
        "gap_reasons": gap_reasons,
        "reshoot_recommendation": reshoot,
        "requires_human_confirmation": True,
        "degraded": bool(degraded),
    }


# ============================ 全局分配 ============================


@dataclass
class Assignment:
    segment_id: int
    shot_id: int | None
    source: str            # locked | selected | recommended | gap
    reused: bool = False
    shot_invalid: bool = False
    warnings: list[str] = field(default_factory=list)


def _lookup(seg: SegmentView) -> dict[int, CandidateView]:
    return {c.shot_id: c for c in seg.candidates}


def _adjacent_similar(a: CandidateView, b: CandidateView) -> bool:
    """相邻段镜头是否高度相似：同一 shot，或同素材且场景/动作标签完全一致。"""
    if a.shot_id == b.shot_id:
        return True
    return (
        a.asset_id == b.asset_id
        and a.scene_labels == b.scene_labels
        and a.action_labels == b.action_labels
    )


def allocate(
    segments: list[SegmentView],
    *,
    max_reuse: int = DEFAULT_MAX_REUSE,
    forbid_adjacent_reuse: bool = True,
) -> dict[int, Assignment]:
    """脚本层全局分配（确定性）。

    优先级：人工锁定 > 人工选择 > 候选综合分（已含产品/风险/审核/质量）。
    在不明显降质前提下减少同一 shot 重复使用、避免相邻段使用高度相似镜头；候选不足允许缺口。
    锁定/选择的镜头即使失效（被 excluded）也保留并标注，绝不静默换片。
    """
    by_order = sorted(segments, key=lambda s: s.order_index)
    usage: dict[int, int] = {}
    result: dict[int, Assignment] = {}
    prev_pick: CandidateView | None = None

    # Pass 1：锁定/选择（人工决定，最高优先；占用 usage；不被去重改动）
    for seg in by_order:
        lk = _lookup(seg)
        forced_id = seg.locked_shot_id if seg.locked_shot_id is not None else None
        source = None
        if seg.locked_shot_id is not None:
            forced_id, source = seg.locked_shot_id, "locked"
        elif seg.selected_shot_id is not None:
            forced_id, source = seg.selected_shot_id, "selected"
        if forced_id is not None:
            cv = lk.get(forced_id)
            invalid = (cv is None) or (not cv.is_valid)
            warnings = []
            if invalid:
                warnings.append("已选/锁定镜头已失效（被删除或排除），请重新选择")
            usage[forced_id] = usage.get(forced_id, 0) + 1
            result[seg.segment_id] = Assignment(
                segment_id=seg.segment_id, shot_id=forced_id, source=source,
                shot_invalid=invalid, warnings=warnings,
            )

    # Pass 2：系统推荐（仅对无人工选择/锁定的段；从有效候选去重挑选）
    for seg in by_order:
        if seg.segment_id in result:
            # 已由 Pass 1 处理；更新 prev_pick 供相邻判断
            picked = result[seg.segment_id]
            prev_pick = _lookup(seg).get(picked.shot_id) if picked.shot_id else prev_pick
            continue
        valid = [c for c in seg.candidates if c.is_valid and c.in_candidate_pool]
        valid.sort(key=lambda c: (c.rank, c.shot_id))
        if not valid:
            result[seg.segment_id] = Assignment(
                segment_id=seg.segment_id, shot_id=None, source="gap",
            )
            prev_pick = None
            continue

        top = valid[0]
        # 优先选：未超复用 + 不与相邻段高度相似；否则在不明显降质内放宽
        choice = None
        for c in valid:
            if usage.get(c.shot_id, 0) >= max_reuse:
                continue
            if forbid_adjacent_reuse and prev_pick is not None and _adjacent_similar(c, prev_pick):
                continue
            if (top.final_score or 0.0) - (c.final_score or 0.0) > DEDUP_MAX_SCORE_DROP:
                continue  # 去重代价过大 → 不为去重选明显更差镜头
            choice = c
            break

        warnings: list[str] = []
        if choice is None:
            # 放宽相邻约束再试（仍限复用与降质）
            for c in valid:
                if usage.get(c.shot_id, 0) >= max_reuse:
                    continue
                if (top.final_score or 0.0) - (c.final_score or 0.0) > DEDUP_MAX_SCORE_DROP:
                    continue
                choice = c
                break
            if choice is not None and prev_pick is not None and _adjacent_similar(choice, prev_pick):
                warnings.append("相邻段使用了相似镜头（无更优替代）")
        if choice is None:
            # 仍无 → 保留 top（允许重复），显式告警
            choice = top
            if usage.get(top.shot_id, 0) >= max_reuse:
                warnings.append("候选不足，重复使用镜头")

        usage[choice.shot_id] = usage.get(choice.shot_id, 0) + 1
        result[seg.segment_id] = Assignment(
            segment_id=seg.segment_id, shot_id=choice.shot_id, source="recommended",
            warnings=warnings,
        )
        prev_pick = choice

    # 标注重复（最终被分配到 >1 段的 shot）
    for a in result.values():
        if a.shot_id is not None and usage.get(a.shot_id, 0) > 1:
            a.reused = True
    return result


# ============================ 剪辑清单行 / 摘要 ============================


@dataclass
class EditListRow:
    segment_id: int
    segment_order: int          # 1-based 展示序号
    segment_text: str
    target_duration_min: float | None
    target_duration_max: float | None
    selection_status: str       # locked | selected | recommended | none
    match_status: str           # pending | matched | gap | degraded
    shot_id: int | None
    asset_id: int | None
    source_start: float | None
    source_end: float | None
    source_duration: float | None
    suggested_in: float | None
    suggested_out: float | None
    suggested_duration: float | None
    duration_status: str | None
    duration_warnings: list[str]
    product_name: str | None
    scene: str | None
    action: str | None
    match_score: float | None
    matched_reasons: list[str]
    unmatched_requirements: list[str]
    risk_warnings: list[str]
    gap_reasons: list[str]
    reshoot_recommendation: list[str]
    requires_human_confirmation: bool
    reused: bool
    shot_invalid: bool


@dataclass
class EditListSummary:
    total_segments: int
    matched_segments: int
    selected_segments: int
    locked_segments: int
    recommended_segments: int
    gap_segments: int
    risk_segments: int
    target_total_duration_min: float | None
    target_total_duration_max: float | None
    suggested_total_duration: float
    duplicate_shot_count: int
    allocation_warnings: list[str]


def _summary_from(summary: dict | None, key, default=None):
    if not summary:
        return default
    return summary.get(key, default)


def build_edit_list(
    segments: list[SegmentView],
    *,
    max_reuse: int = DEFAULT_MAX_REUSE,
    forbid_adjacent_reuse: bool = True,
) -> tuple[list[EditListRow], EditListSummary]:
    """组装剪辑清单（行 + 摘要）。绝不把系统推荐第一名描述成人工已确认。"""
    alloc = allocate(
        segments, max_reuse=max_reuse, forbid_adjacent_reuse=forbid_adjacent_reuse
    )
    by_order = sorted(segments, key=lambda s: s.order_index)

    rows: list[EditListRow] = []
    matched = selected = locked = recommended = gap = risk = 0
    tgt_min_sum = 0.0
    tgt_max_sum = 0.0
    has_min = has_max = False
    suggested_total = 0.0
    used_shots: dict[int, int] = {}
    all_warnings: list[str] = []

    for i, seg in enumerate(by_order, start=1):
        a = alloc[seg.segment_id]
        lk = _lookup(seg)
        cv = lk.get(a.shot_id) if a.shot_id is not None else None
        all_warnings.extend(a.warnings)

        if a.source == "locked":
            sel_status = "locked"
            locked += 1
        elif a.source == "selected":
            sel_status = "selected"
            selected += 1
        elif a.source == "recommended":
            sel_status = "recommended"
            recommended += 1
        else:
            sel_status = "none"

        # match_status：以段落持久化为准（pending/matched/gap/degraded）
        ms = seg.match_status or "pending"
        if ms == "gap" or a.shot_id is None:
            gap += 1 if ms == "gap" else 0
        if ms in ("matched", "degraded"):
            matched += 1

        dur = None
        if cv is not None:
            dur = compute_duration_suggestion(
                source_start=cv.source_start, source_end=cv.source_end,
                target_min=seg.target_duration_min, target_max=seg.target_duration_max,
            )
            suggested_total += dur.suggested_duration
            if a.shot_id is not None:
                used_shots[a.shot_id] = used_shots.get(a.shot_id, 0) + 1

        if seg.target_duration_min is not None:
            tgt_min_sum += seg.target_duration_min
            has_min = True
        if seg.target_duration_max is not None:
            tgt_max_sum += seg.target_duration_max
            has_max = True

        risk_warnings = list(cv.risk_warnings) if cv else []
        if risk_warnings:
            risk += 1

        rows.append(
            EditListRow(
                segment_id=seg.segment_id,
                segment_order=i,
                segment_text=seg.segment_text,
                target_duration_min=seg.target_duration_min,
                target_duration_max=seg.target_duration_max,
                selection_status=sel_status,
                match_status=ms,
                shot_id=a.shot_id,
                asset_id=cv.asset_id if cv else None,
                source_start=cv.source_start if cv else None,
                source_end=cv.source_end if cv else None,
                source_duration=round(cv.source_duration, 3) if cv else None,
                suggested_in=dur.suggested_in if dur else None,
                suggested_out=dur.suggested_out if dur else None,
                suggested_duration=dur.suggested_duration if dur else None,
                duration_status=dur.status if dur else None,
                duration_warnings=dur.warnings if dur else [],
                product_name=cv.product_name if cv else seg.product_name,
                scene="、".join(cv.scene_labels[:5]) if cv and cv.scene_labels else None,
                action="、".join(cv.action_labels[:5]) if cv and cv.action_labels else None,
                match_score=_round(cv.final_score, 4) if cv else None,
                matched_reasons=list(cv.matched_reasons) if cv else [],
                unmatched_requirements=list(cv.unmatched_requirements) if cv else [],
                risk_warnings=risk_warnings,
                gap_reasons=list(_summary_from(seg.match_summary, "gap_reasons", []) or []),
                reshoot_recommendation=list(
                    _summary_from(seg.match_summary, "reshoot_recommendation", []) or []
                ),
                requires_human_confirmation=bool(
                    _summary_from(seg.match_summary, "requires_human_confirmation", a.shot_id is None)
                ),
                reused=a.reused,
                shot_invalid=a.shot_invalid,
            )
        )

    duplicate_shot_count = sum(1 for _sid, n in used_shots.items() if n > 1)
    summary = EditListSummary(
        total_segments=len(by_order),
        matched_segments=matched,
        selected_segments=selected,
        locked_segments=locked,
        recommended_segments=recommended,
        gap_segments=gap,
        risk_segments=risk,
        target_total_duration_min=round(tgt_min_sum, 3) if has_min else None,
        target_total_duration_max=round(tgt_max_sum, 3) if has_max else None,
        suggested_total_duration=round(suggested_total, 3),
        duplicate_shot_count=duplicate_shot_count,
        allocation_warnings=list(dict.fromkeys(all_warnings)),
    )
    return rows, summary


# ============================ CSV 序列化 ============================

# 固定列顺序（kind：text=用户文本需防注入 / num=自产数值安全 / list=列表用 | 连接需防注入）
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("段落序号", "num"),
    ("段落文案", "text"),
    ("目标时长下限(s)", "num"),
    ("目标时长上限(s)", "num"),
    ("选用状态", "text"),
    ("匹配状态", "text"),
    ("镜头ID", "num"),
    ("素材ID", "num"),
    ("源入点(s)", "num"),
    ("源出点(s)", "num"),
    ("源时长(s)", "num"),
    ("建议入点(s)", "num"),
    ("建议出点(s)", "num"),
    ("建议时长(s)", "num"),
    ("时长状态", "text"),
    ("时长提示", "list"),
    ("产品", "text"),
    ("场景", "text"),
    ("动作", "text"),
    ("匹配度", "num"),
    ("匹配理由", "list"),
    ("未满足要求", "list"),
    ("风险提示", "list"),
    ("缺口原因", "list"),
    ("补拍建议", "list"),
    ("需人工确认", "text"),
    ("镜头重复", "text"),
    ("镜头失效", "text"),
)


def _guard(value: str) -> str:
    """CSV 公式注入防护：危险前缀单元格加前导单引号（OWASP 推荐缓解）。"""
    if value and value[0] in _CSV_DANGEROUS_PREFIXES:
        return "'" + value
    return value


def _num(x: float | int | None) -> str:
    if x is None:
        return ""
    if isinstance(x, float):
        # 稳定数值格式，去除多余尾零，不制造虚假精度
        return f"{x:.3f}".rstrip("0").rstrip(".")
    return str(x)


def _list_cell(values: list[str]) -> str:
    return _guard(" | ".join(v.replace("|", "/") for v in values if v))


def _bool_cell(b: bool) -> str:
    return "是" if b else "否"


def row_to_cells(row: EditListRow) -> list[str]:
    """单行 → 与 _COLUMNS 对齐的字符串单元格（已防注入/格式化）。"""
    return [
        _num(row.segment_order),
        _guard(row.segment_text or ""),
        _num(row.target_duration_min),
        _num(row.target_duration_max),
        _guard(row.selection_status),
        _guard(row.match_status),
        _num(row.shot_id),
        _num(row.asset_id),
        _num(row.source_start),
        _num(row.source_end),
        _num(row.source_duration),
        _num(row.suggested_in),
        _num(row.suggested_out),
        _num(row.suggested_duration),
        _guard(row.duration_status or ""),
        _list_cell(row.duration_warnings),
        _guard(row.product_name or ""),
        _guard(row.scene or ""),
        _guard(row.action or ""),
        _num(row.match_score),
        _list_cell(row.matched_reasons),
        _list_cell(row.unmatched_requirements),
        _list_cell(row.risk_warnings),
        _list_cell(row.gap_reasons),
        _list_cell(row.reshoot_recommendation),
        _bool_cell(row.requires_human_confirmation),
        _bool_cell(row.reused),
        _bool_cell(row.shot_invalid),
    ]


def to_csv(rows: list[EditListRow]) -> bytes:
    """剪辑清单 → CSV 字节（UTF-8 BOM；RFC4180 由 csv 模块转义；无匹配段落也成行）。"""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([h for h, _kind in _COLUMNS])
    for row in rows:
        writer.writerow(row_to_cells(row))
    # UTF-8 BOM 让 Excel 正确识别中文
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def csv_headers() -> list[str]:
    return [h for h, _kind in _COLUMNS]


# ============================ PR-06B 多格式序列化（XLSX / JSON / Markdown / Printable HTML） ============================
#
# 全部复用 build_edit_list 的 rows/summary 与同一套防注入/转义；纯逻辑、确定性、无 DB/网络。
# 磁盘名固定 ASCII；内容绝不含本机绝对路径 / Key / Endpoint（仅 shot/asset/时间码/段落文本等业务字段）。

SCRIPT_EXPORT_DISK_NAMES: dict[str, str] = {
    "csv": "edit_list.csv",
    "xlsx": "edit_list.xlsx",
    "json": "edit_list.json",
    "markdown": "edit_list.md",
    "printable": "edit_list.html",
}
SCRIPT_EXPORT_CONTENT_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json; charset=utf-8",
    "markdown": "text/markdown; charset=utf-8",
    "printable": "text/html; charset=utf-8",
}
SCRIPT_EXPORT_NAME_SUFFIX: dict[str, str] = {
    "csv": ".csv",
    "xlsx": ".xlsx",
    "json": ".json",
    "markdown": ".md",
    "printable": ".html",
}


def build_meta(
    *, project_name: str | None, project_id: int, row_count: int, generated_at: str
) -> dict:
    """导出元数据（无路径/Key/Endpoint）。generated_at 由调用方注入（ISO 字符串），保持确定性。"""
    return {
        "kind": "script_edit_list",
        "schema_version": 1,
        "project_id": int(project_id),
        "project_name": project_name or f"script_{project_id}",
        "row_count": int(row_count),
        "generated_at": generated_at,
    }


def to_json(rows: list[EditListRow], summary: EditListSummary, *, meta: dict) -> bytes:
    """剪辑清单 → JSON 字节（UTF-8；固定 schema；含 metadata + summary + segments；缺口段保留）。"""
    payload = {
        "metadata": meta,
        "summary": _dc.asdict(summary),
        "segments": [_dc.asdict(r) for r in rows],
    }
    return _json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def to_xlsx(rows: list[EditListRow], summary: EditListSummary, *, meta: dict) -> bytes:
    """剪辑清单 → XLSX 字节（openpyxl；中文正常；数值列写为数值，文本/列表列防注入）。"""
    from openpyxl import Workbook  # 延迟导入，仅多格式导出路径需要

    wb = Workbook()
    ws = wb.active
    ws.title = "剪辑清单"
    ws.append([h for h, _kind in _COLUMNS])
    for row in rows:
        cells = row_to_cells(row)  # 已按列格式化 + 防注入
        out: list = []
        for (_, kind), value in zip(_COLUMNS, cells, strict=True):
            if kind == "num" and value != "":
                try:
                    num = float(value)
                    out.append(int(num) if num.is_integer() else num)
                    continue
                except ValueError:
                    pass
            out.append(value)
        ws.append(out)

    # 摘要页（数值，安全）
    ws2 = wb.create_sheet("摘要")
    for k, v in _dc.asdict(summary).items():
        ws2.append([k, v if not isinstance(v, list) else " | ".join(map(str, v))])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _md_cell(value: str) -> str:
    """Markdown 表格单元格转义：竖线/换行不破坏表格（value 已经过 _guard 防注入）。"""
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def to_markdown(rows: list[EditListRow], summary: EditListSummary, *, meta: dict) -> bytes:
    """剪辑清单 → Markdown 字节（标题 + 摘要 + 表格 + 缺口/补拍可读段；特殊字符正确转义）。"""
    lines: list[str] = []
    name = _md_cell(_guard(str(meta.get("project_name", ""))))
    lines.append(f"# 剪辑清单：{name}")
    lines.append("")
    lines.append(
        f"- 段落总数：{summary.total_segments} ｜ 已匹配：{summary.matched_segments} "
        f"｜ 锁定：{summary.locked_segments} ｜ 缺口：{summary.gap_segments} "
        f"｜ 风险段：{summary.risk_segments}"
    )
    if summary.suggested_total_duration:
        lines.append(f"- 建议总时长：约 {summary.suggested_total_duration:.2f}s")
    lines.append(f"- 生成时间：{meta.get('generated_at', '')}")
    lines.append("")

    headers = [h for h, _kind in _COLUMNS]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        cells = [_md_cell(c) for c in row_to_cells(row)]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    gap_rows = [r for r in rows if r.gap_reasons or r.reshoot_recommendation]
    if gap_rows:
        lines.append("## 缺口与补拍建议")
        lines.append("")
        for r in gap_rows:
            lines.append(f"### 段落 {r.segment_order}")
            if r.gap_reasons:
                lines.append("- 缺口原因：")
                lines.extend(f"  - {_md_cell(_guard(g))}" for g in r.gap_reasons)
            if r.reshoot_recommendation:
                lines.append("- 补拍建议：")
                lines.extend(f"  - {_md_cell(_guard(s))}" for s in r.reshoot_recommendation)
            lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")


_PRINTABLE_CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
       color: #1a1a1a; margin: 24px; }
h1 { font-size: 20px; margin: 0 0 8px; }
.meta { color: #555; font-size: 13px; margin-bottom: 16px; }
.summary { background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px;
           padding: 10px 14px; margin-bottom: 16px; font-size: 13px; }
table { border-collapse: collapse; width: 100%; font-size: 12px; }
th, td { border: 1px solid #ccc; padding: 4px 6px; text-align: left; vertical-align: top; }
th { background: #efefef; position: sticky; top: 0; }
.gap { color: #b00; }
@media print {
  body { margin: 8mm; }
  th { position: static; }
  tr { break-inside: avoid; }
  .no-print { display: none; }
}
""".strip()


def to_printable_html(
    rows: list[EditListRow], summary: EditListSummary, *, meta: dict
) -> bytes:
    """剪辑清单 → 自包含可打印 HTML 字节（内联样式 + 打印样式，无外部 CDN；用户文本 HTML escape）。"""

    def esc(value: str) -> str:
        return _html.escape(str(value), quote=True)

    name = esc(meta.get("project_name", ""))
    headers = "".join(f"<th>{esc(h)}</th>" for h, _kind in _COLUMNS)
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row_to_cells(row)) + "</tr>"
        for row in rows
    )
    summary_html = esc(
        f"段落总数 {summary.total_segments} ｜ 已匹配 {summary.matched_segments} "
        f"｜ 锁定 {summary.locked_segments} ｜ 缺口 {summary.gap_segments} "
        f"｜ 风险段 {summary.risk_segments} ｜ 建议总时长约 "
        f"{summary.suggested_total_duration:.2f}s"
    )
    doc = (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>剪辑清单：{name}</title>"
        f"<style>{_PRINTABLE_CSS}</style></head><body>"
        f"<h1>剪辑清单：{name}</h1>"
        f'<div class="meta">生成时间：{esc(meta.get("generated_at", ""))}'
        f' ｜ 段落数：{summary.total_segments}</div>'
        f'<div class="summary">{summary_html}</div>'
        '<button class="no-print" onclick="window.print()">打印</button>'
        f"<table><thead><tr>{headers}</tr></thead><tbody>{body_rows}</tbody></table>"
        "</body></html>"
    )
    return doc.encode("utf-8")


def serialize_edit_list(
    fmt: str, rows: list[EditListRow], summary: EditListSummary, *, meta: dict
) -> bytes:
    """按格式分派序列化（csv/xlsx/json/markdown/printable）。"""
    if fmt == "csv":
        return to_csv(rows)
    if fmt == "xlsx":
        return to_xlsx(rows, summary, meta=meta)
    if fmt == "json":
        return to_json(rows, summary, meta=meta)
    if fmt == "markdown":
        return to_markdown(rows, summary, meta=meta)
    if fmt == "printable":
        return to_printable_html(rows, summary, meta=meta)
    raise ValueError(f"unsupported export format: {fmt}")
