import { vi } from "vitest";

import type {
  FinalVideo,
  FinalVideoLineage,
  Shot,
  UsageWithOccurrences,
} from "@/lib/types";

export { mutation, query } from "../search/fixtures";

export function makeFinalVideo(o: Partial<FinalVideo> = {}): FinalVideo {
  return {
    id: 1,
    asset_id: 90,
    project_id: 5,
    script_project_id: null,
    title: "产品宣传片 6 月投放版",
    description: null,
    version_label: "v1",
    status: "draft",
    completed_at: null,
    archived_at: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T01:00:00Z",
    asset_filename: "final_cut.mp4",
    asset_duration: 62.5,
    asset_has_poster: false,
    project_name: "夏季广告",
    script_project_name: null,
    usage_stats: {
      source_shot_count: 3,
      confirmed_count: 1,
      proposed_count: 2,
      suspected_count: 0,
      rejected_count: 0,
      revoked_count: 0,
    },
    ...o,
  };
}

export function makeUsageShot(o: Partial<Shot> = {}): Shot {
  return {
    id: 201,
    asset_id: 10,
    asset_filename: "raw_a.mp4",
    sequence_no: 3,
    start_time: 4,
    end_time: 9,
    duration: 5,
    detector_type: "content",
    detector_confidence: null,
    status: "ready",
    error_message: null,
    has_keyframe: true,
    has_thumbnail: true,
    has_proxy: true,
    keyframe_count: 0,
    created_at: "2026-06-30T00:00:00Z",
    updated_at: "2026-06-30T00:00:00Z",
    ...o,
  } as Shot;
}

export function makeUsage(o: Partial<UsageWithOccurrences> = {}): UsageWithOccurrences {
  return {
    id: 11,
    final_video_id: 1,
    source_shot_id: 201,
    source_asset_id: 10,
    source_shot_generation: 1,
    status: "proposed",
    evidence_method: "manual",
    confidence: null,
    evidence_summary: null,
    evidence_refs: null,
    confirmed_at: null,
    rejected_at: null,
    revoked_at: null,
    actor_label: null,
    review_note: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    shot: makeUsageShot(),
    source_asset_filename: "raw_a.mp4",
    occurrence_count: 0,
    product_name: null,
    occurrences: [],
    ...o,
  };
}

export function makeLineage(o: Partial<FinalVideoLineage> = {}): FinalVideoLineage {
  return {
    final_video: makeFinalVideo(),
    usages: [makeUsage()],
    ...o,
  };
}

export function lifecycleMutation() {
  return { mutate: vi.fn(), isPending: false, error: null } as never;
}
