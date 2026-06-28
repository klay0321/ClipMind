import type {
  Asset,
  BatchMembershipResult,
  Collection,
  Product,
  Project,
  ProjectAssetItem,
  ProjectStats,
  ScriptProject,
  Shot,
} from "@/lib/types";

export { mutation, query } from "../search/fixtures";

export function makeProject(o: Partial<Project> = {}): Project {
  return {
    id: 1,
    name: "夏季广告",
    description: "真实素材组织",
    status: "active",
    archived_at: null,
    lock_version: 1,
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T01:00:00Z",
    ...o,
  };
}

export function makeStats(o: Partial<ProjectStats> = {}): ProjectStats {
  return {
    project_id: 1,
    asset_count: 3,
    visible_shot_count: 12,
    explicit_shot_count: 2,
    collection_count: 2,
    collection_shot_count: 5,
    product_count: 2,
    script_count: 1,
    active_script_count: 1,
    locked_segment_count: 1,
    gap_segment_count: 1,
    completed_script_export_count: 1,
    risk_shot_count: 2,
    searchable_shot_count: 4,
    updated_at: "2026-06-28T01:00:00Z",
    ...o,
  };
}

export function makeCollection(o: Partial<Collection> = {}): Collection {
  return {
    id: 1,
    project_id: 1,
    name: "Hook 集合",
    description: null,
    lock_version: 1,
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:30:00Z",
    shot_count: 3,
    ...o,
  };
}

export function makeShot(o: Partial<Shot> = {}): Shot {
  return {
    id: 101,
    asset_id: 10,
    asset_filename: "a.mp4",
    sequence_no: 1,
    start_time: 0,
    end_time: 2,
    duration: 2,
    detector_type: "fixed",
    detector_confidence: null,
    status: "ready",
    error_message: null,
    has_keyframe: true,
    has_thumbnail: true,
    has_proxy: true,
    keyframe_count: 0,
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:00:00Z",
    ...o,
  };
}

export function makeAsset(o: Partial<Asset> = {}): Asset {
  return {
    id: 10,
    source_directory_id: 1,
    relative_path: "a.mp4",
    normalized_relative_path: "a.mp4",
    filename: "a.mp4",
    extension: "mp4",
    file_size: 1000,
    modified_at: null,
    quick_hash: null,
    duration: 5,
    width: 1920,
    height: 1080,
    fps: 30,
    video_codec: "h264",
    audio_codec: "aac",
    orientation: "landscape",
    has_audio: true,
    status: "indexed",
    error_message: null,
    last_seen_scan_id: null,
    first_seen_at: "2026-06-28T00:00:00Z",
    last_seen_at: "2026-06-28T00:00:00Z",
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:00:00Z",
    shot_count: 4,
    analysis_status: null,
    cover_shot_id: null,
    has_poster: true,
    ...o,
  };
}

export function makeProjectAssetItem(o: Partial<ProjectAssetItem> = {}): ProjectAssetItem {
  return { order_index: 0, asset: makeAsset(), ...o };
}

export function makeProduct(o: Partial<Product> = {}): Product {
  return {
    id: 5,
    brand: "PowerGo",
    name: "吹风机",
    model: null,
    sku: null,
    selling_points: null,
    status: "active",
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:00:00Z",
    ...o,
  };
}

export function makeScript(o: Partial<ScriptProject> = {}): ScriptProject {
  return {
    id: 7,
    name: "吹风机脚本",
    source_format: "paste",
    status: "parsed",
    parse_status: "ok",
    parser_provider: "mimo",
    parser_model: null,
    parser_warnings: null,
    result_schema_version: 1,
    segment_count: 4,
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:00:00Z",
    ...o,
  };
}

export function makeBatch(o: Partial<BatchMembershipResult> = {}): BatchMembershipResult {
  return { completed: [], skipped: [], failed: [], ...o };
}
