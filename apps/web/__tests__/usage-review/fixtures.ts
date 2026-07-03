import type {
  ReviewItem,
  ReviewItemDetail,
  ReviewSummary,
} from "@/lib/types";

export { mutation, query } from "../search/fixtures";

export function makeReviewItem(o: Partial<ReviewItem> = {}): ReviewItem {
  return {
    item_type: "final_video_usage",
    item_id: 11,
    review_group: "needs_review",
    source_strength: "project_proposed_lineage",
    review_status: "proposed",
    asset_id: 10,
    asset_filename: "raw_a.mp4",
    shot_id: 201,
    shot_sequence_no: 3,
    final_video_id: 1,
    final_video_title: "六月投放成片",
    product: null,
    source_label: "clipmind_project",
    evidence_summary: null,
    created_at: "2026-07-02T00:00:00Z",
    last_observed_at: null,
    reviewed_at: null,
    available_actions: ["confirm", "reject"],
    ...o,
  };
}

export function makeLegacyItem(o: Partial<ReviewItem> = {}): ReviewItem {
  return makeReviewItem({
    item_type: "legacy_usage_evidence",
    item_id: 21,
    source_strength: "pending_legacy_evidence",
    review_status: "pending",
    shot_id: null,
    shot_sequence_no: null,
    final_video_id: null,
    final_video_title: null,
    source_label: "历史标记规则 v1",
    evidence_summary: "historical-marker",
    last_observed_at: "2026-07-02T01:00:00Z",
    available_actions: ["accept", "reject", "mark_conflict"],
    ...o,
  });
}

export function makeSummary(o: Partial<ReviewSummary> = {}): ReviewSummary {
  return {
    formal: { confirmed: 2, proposed: 3, suspected: 1, rejected: 1, revoked: 1 },
    legacy: { pending: 4, accepted: 2, rejected: 1, conflict: 1 },
    needs_review_total: 8,
    ...o,
  };
}

export function makeDetail(o: Partial<ReviewItemDetail> = {}): ReviewItemDetail {
  return {
    item: makeLegacyItem(),
    formal_usage: null,
    legacy_evidence: {
      matched_component: "historical-marker",
      rule_name: "历史标记规则",
      rule_version: 1,
      observation_count: 2,
      location_relative_path: "historical-marker/clip_a.mp4",
    },
    events: [
      {
        id: 1,
        action: "detected",
        before_status: null,
        after_status: "pending",
        actor_label: null,
        note: null,
        created_at: "2026-07-02T00:00:00Z",
      },
      {
        id: 2,
        action: "observed_again",
        before_status: "pending",
        after_status: "pending",
        actor_label: null,
        note: null,
        created_at: "2026-07-02T01:00:00Z",
      },
    ],
    ...o,
  };
}
