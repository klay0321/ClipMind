import type {
  AssetLegacySummary,
  LegacyEvidence,
  LegacyImportRun,
  LegacyPreview,
  LegacyUsageRule,
} from "@/lib/types";

export { mutation, query } from "../search/fixtures";

export function makeRule(o: Partial<LegacyUsageRule> = {}): LegacyUsageRule {
  return {
    id: 1,
    name: "历史标记目录",
    description: null,
    source_directory_id: null,
    source_directory_name: null,
    match_target: "directory_segment",
    match_operator: "equals",
    pattern: "historical-marker",
    case_sensitive: false,
    include_present_locations: true,
    include_missing_locations: true,
    include_historical_locations: true,
    enabled: true,
    priority: 100,
    version: 1,
    snapshot_hash: "a".repeat(64),
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    archived_at: null,
    evidence_count: 2,
    ...o,
  };
}

export function makeEvidence(o: Partial<LegacyEvidence> = {}): LegacyEvidence {
  return {
    id: 11,
    asset_id: 10,
    asset_filename: "clip_a.mp4",
    asset_status: "ready",
    product_name: null,
    asset_location_id: 5,
    location_relative_path: "historical-marker/clip_a.mp4",
    location_status: "present",
    source_root_name: "素材根",
    rule_id: 1,
    rule_name: "历史标记目录",
    rule_version: 1,
    evidence_type: "directory_marker",
    matched_target: "directory_segment",
    matched_component: "historical-marker",
    review_status: "pending",
    review_note: null,
    actor_label: null,
    first_observed_at: "2026-07-01T00:00:00Z",
    last_observed_at: "2026-07-01T00:00:00Z",
    observation_count: 1,
    reviewed_at: null,
    created_at: "2026-07-01T00:00:00Z",
    confirmed_usage_count: 0,
    has_final_video_usage: false,
    ...o,
  };
}

export function makeRun(o: Partial<LegacyImportRun> = {}): LegacyImportRun {
  return {
    id: 3,
    source_directory_id: null,
    status: "completed",
    dry_run: false,
    location_scope: ["present", "missing", "historical"],
    scanned_location_count: 40,
    matched_location_count: 6,
    matched_asset_count: 5,
    created_evidence_count: 5,
    existing_evidence_count: 1,
    conflict_count: 0,
    error_count: 0,
    error_summary: null,
    started_at: "2026-07-01T00:00:00Z",
    completed_at: "2026-07-01T00:01:00Z",
    created_at: "2026-07-01T00:00:00Z",
    ...o,
  };
}

export function makePreview(o: Partial<LegacyPreview> = {}): LegacyPreview {
  return {
    scanned_location_count: 40,
    matched_location_count: 6,
    matched_asset_count: 5,
    would_create_count: 5,
    existing_evidence_count: 1,
    conflict_count: 0,
    error_count: 0,
    by_rule: { "1": 6 },
    by_location_status: { present: 4, historical: 2 },
    samples: [
      {
        asset_id: 10,
        relative_path: "historical-marker/clip_a.mp4",
        location_status: "present",
        rule_id: 1,
        rule_name: "历史标记目录",
        matched_component: "historical-marker",
        already_exists: false,
      },
    ],
    ...o,
  };
}

export function makeLegacySummary(o: Partial<AssetLegacySummary> = {}): AssetLegacySummary {
  return {
    asset_id: 10,
    legacy_usage_state: "legacy_used_unknown",
    accepted_count: 1,
    pending_count: 0,
    rejected_count: 0,
    conflict_count: 0,
    evidences: [makeEvidence({ review_status: "accepted" })],
    ...o,
  };
}
