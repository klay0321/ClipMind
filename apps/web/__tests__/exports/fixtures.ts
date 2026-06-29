import type {
  DynamicCollection,
  ExportCenterItem,
  FavoriteOut,
  SavedSearch,
} from "@/lib/types";

export { mutation, query } from "../search/fixtures";

export function makeExportItem(o: Partial<ExportCenterItem> = {}): ExportCenterItem {
  return {
    kind: "clip",
    id: 1,
    export_uuid: "uuid-1",
    project_id: null,
    status: "completed",
    format: "mp4",
    filename: "clip_1.mp4",
    has_file: true,
    row_count: null,
    error_message: null,
    created_at: "2026-06-28T00:00:00Z",
    started_at: "2026-06-28T00:00:01Z",
    finished_at: "2026-06-28T00:00:05Z",
    download_url: "/api/exports/1/download",
    download_count: 2,
    source: {},
    ...o,
  };
}

export function makeSavedSearch(o: Partial<SavedSearch> = {}): SavedSearch {
  return {
    id: 1,
    project_id: null,
    name: "竖屏产品特写",
    search_kind: "shot_search",
    query: { query: "竖屏 产品 特写", search_mode: "hybrid" },
    lock_version: 0,
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:30:00Z",
    ...o,
  };
}

export function makeFavorite(o: Partial<FavoriteOut> = {}): FavoriteOut {
  return {
    id: 1,
    target_type: "shot",
    asset_id: null,
    shot_id: 101,
    context: null,
    created_at: "2026-06-28T00:00:00Z",
    shot: {
      id: 101,
      asset_id: 10,
      asset_filename: "a.mp4",
      sequence_no: 3,
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
    },
    asset: null,
    ...o,
  };
}

export function makeDynamicCollection(o: Partial<DynamicCollection> = {}): DynamicCollection {
  return {
    id: 1,
    project_id: 1,
    name: "竖屏产品特写（实时）",
    description: null,
    search_kind: "shot_search",
    query: { query: "竖屏 产品 特写" },
    lock_version: 0,
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:30:00Z",
    ...o,
  };
}
