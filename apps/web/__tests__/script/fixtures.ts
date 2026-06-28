import type {
  ScriptCandidate,
  ScriptEditList,
  EditListRow,
  ScriptExport,
  ScriptProjectDetail,
  ScriptSegment,
  SegmentCandidatesResponse,
} from "@/lib/types";

export { mutation, query } from "../search/fixtures";

export function makeSegment(o: Partial<ScriptSegment> = {}): ScriptSegment {
  return {
    id: 1,
    script_project_id: 1,
    order_index: 0,
    segment_text: "开场展示产品外观",
    visual_requirement: null,
    normalized_text: null,
    target_duration_min: 2,
    target_duration_max: 4,
    product_id: null,
    structured_requirements: { scenes: ["室内"], actions: ["展示"] },
    negative_terms: null,
    excluded_risks: null,
    allow_similar_scene: true,
    allow_similar_action: true,
    current_generation: 1,
    selected_shot_id: null,
    locked_shot_id: null,
    lock_version: 0,
    match_status: "matched",
    candidates_stale: false,
    parser_warnings: null,
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:00:00Z",
    ...o,
  };
}

export function makeProject(o: Partial<ScriptProjectDetail> = {}): ScriptProjectDetail {
  return {
    id: 1,
    name: "吹风机产品介绍",
    source_format: "paste",
    status: "parsed",
    parse_status: "ok",
    parser_provider: "mimo",
    parser_model: "mimo-v2.5-pro",
    parser_warnings: null,
    result_schema_version: 1,
    segment_count: 1,
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:00:00Z",
    raw_script: "开场展示产品外观。\n\n使用演示。",
    segments: [makeSegment()],
    ...o,
  };
}

export function makeCandidate(o: Partial<ScriptCandidate> = {}): ScriptCandidate {
  return {
    shot_id: 101,
    asset_id: 16,
    rank: 0,
    final_score: 0.72,
    semantic_score: 0.8,
    lexical_score: 0.5,
    tag_score: 0.4,
    product_score: null,
    quality_score: 1,
    review_bonus: 0,
    risk_penalty: 0,
    matched_reasons: ["语义相似（向量召回）"],
    unmatched_requirements: ["动作不完整：展示"],
    risk_warnings: [],
    sequence_no: 1,
    start_time: 0,
    end_time: 5,
    duration: 5,
    preview_url: "/api/shots/101/preview",
    thumbnail_url: "/api/shots/101/thumbnail",
    keyframe_url: "/api/shots/101/keyframe",
    ...o,
  };
}

export function makeCandidatesResponse(
  o: Partial<SegmentCandidatesResponse> = {},
): SegmentCandidatesResponse {
  return {
    segment_id: 1,
    generation: 1,
    current_generation: 1,
    match_status: "matched",
    candidate_count: 2,
    best_score: 0.72,
    gap_reasons: [],
    reshoot_recommendation: [],
    requires_human_confirmation: false,
    degraded: false,
    candidates_stale: false,
    selected_shot_id: null,
    locked_shot_id: null,
    lock_version: 0,
    candidates: [makeCandidate(), makeCandidate({ shot_id: 102, rank: 1, final_score: 0.55 })],
    ...o,
  };
}

export function makeEditRow(o: Partial<EditListRow> = {}): EditListRow {
  return {
    segment_id: 1,
    segment_order: 1,
    segment_text: "开场展示产品外观",
    target_duration_min: 2,
    target_duration_max: 4,
    selection_status: "recommended",
    match_status: "matched",
    shot_id: 101,
    asset_id: 16,
    source_start: 0,
    source_end: 5,
    source_duration: 5,
    suggested_in: 0,
    suggested_out: 4,
    suggested_duration: 4,
    duration_status: "too_long",
    duration_warnings: ["镜头偏长，建议裁切约 1.00s"],
    product_name: "吹风机",
    scene: "室内",
    action: "展示",
    match_score: 0.72,
    matched_reasons: ["语义相似（向量召回）"],
    unmatched_requirements: [],
    risk_warnings: [],
    gap_reasons: [],
    reshoot_recommendation: [],
    requires_human_confirmation: true,
    reused: false,
    shot_invalid: false,
    ...o,
  };
}

export function makeEditList(rows: EditListRow[], o: Partial<ScriptEditList> = {}): ScriptEditList {
  return {
    script_id: 1,
    summary: {
      total_segments: rows.length,
      matched_segments: rows.filter((r) => r.match_status === "matched").length,
      selected_segments: rows.filter((r) => r.selection_status === "selected").length,
      locked_segments: rows.filter((r) => r.selection_status === "locked").length,
      recommended_segments: rows.filter((r) => r.selection_status === "recommended").length,
      gap_segments: rows.filter((r) => r.match_status === "gap").length,
      risk_segments: rows.filter((r) => r.risk_warnings.length > 0).length,
      target_total_duration_min: 2,
      target_total_duration_max: 4,
      suggested_total_duration: 4,
      duplicate_shot_count: 0,
      allocation_warnings: [],
      ...(o.summary ?? {}),
    },
    rows,
    ...o,
  };
}

export function makeExport(o: Partial<ScriptExport> = {}): ScriptExport {
  return {
    id: 7,
    script_project_id: 1,
    status: "queued",
    export_format: "csv",
    filename: null,
    row_count: null,
    has_file: false,
    error_message: null,
    celery_task_id: "csvtask-7",
    created_at: "2026-06-28T00:00:00Z",
    finished_at: null,
    ...o,
  };
}
