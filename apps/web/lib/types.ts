// 与后端 API schema 对应的前端类型。

export type AssetStatus =
  | "discovered"
  | "indexed"
  | "error"
  | "source_missing"
  | "pending"
  | "processing"
  | "shot_split"
  | "ai_analyzing"
  | "pending_review"
  | "searchable"
  | "paused"
  | "archived";

export type ScanStatus =
  | "never_scanned"
  | "queued"
  | "scanning"
  | "completed"
  | "failed"
  | "cancelled";

export type ScanRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface Asset {
  id: number;
  source_directory_id: number;
  relative_path: string;
  normalized_relative_path: string;
  filename: string;
  extension: string;
  file_size: number;
  modified_at: string | null;
  quick_hash: string | null;
  duration: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  orientation: string | null;
  has_audio: boolean | null;
  status: AssetStatus;
  error_message: string | null;
  last_seen_scan_id: number | null;
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
  // PR-02 镜头分析概览
  shot_count: number;
  analysis_status: MediaRunStatus | null;
  cover_shot_id: number | null;
}

// ===== PR-02 拆镜头 / 派生文件 =====

export type ShotStatus = "pending" | "processing" | "ready" | "failed";

export type MediaRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type ExportStatus = "queued" | "running" | "completed" | "failed";

export interface Shot {
  id: number;
  asset_id: number;
  asset_filename: string | null;
  sequence_no: number;
  start_time: number;
  end_time: number;
  duration: number;
  detector_type: string;
  detector_confidence: number | null;
  status: ShotStatus;
  error_message: string | null;
  has_keyframe: boolean;
  has_thumbnail: boolean;
  has_proxy: boolean;
  keyframe_count: number;
  created_at: string;
  updated_at: string;
}

export interface ShotDetail extends Shot {
  asset_filename: string;
  asset_duration: number | null;
  asset_width: number | null;
  asset_height: number | null;
  asset_video_codec: string | null;
  asset_audio_codec: string | null;
}

export interface ShotAnalysis {
  asset_id: number;
  has_run: boolean;
  run_id: number | null;
  status: MediaRunStatus | null;
  progress: number;
  current_step: string | null;
  total_shots: number;
  completed_shots: number;
  error_message: string | null;
  celery_task_id: string | null;
  generation: number;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  shot_count: number;
}

export interface ExportItem {
  id: number;
  asset_id: number | null;
  shot_id: number | null;
  status: ExportStatus;
  mode: string;
  source_asset_id: number;
  source_shot_id: number;
  source_generation: number;
  source_sequence_no: number;
  source_start_time: number;
  source_end_time: number;
  source_filename: string;
  source_relative_path: string;
  filename: string | null;
  error_message: string | null;
  celery_task_id: string | null;
  has_file: boolean;
  created_at: string;
  finished_at: string | null;
}

export interface ShotQuery {
  asset_id?: number;
  status?: ShotStatus;
  page: number;
  page_size: number;
}

export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface SourceDirectory {
  id: number;
  name: string;
  mount_path: string;
  enabled: boolean;
  recursive: boolean;
  include_extensions: string[];
  exclude_patterns: string[];
  read_only: boolean;
  scan_status: ScanStatus;
  last_scanned_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScanRun {
  id: number;
  source_directory_id: number;
  status: ScanRunStatus;
  celery_task_id: string | null;
  queued_at: string;
  started_at: string | null;
  heartbeat_at: string | null;
  finished_at: string | null;
  worker_name: string | null;
  files_discovered: number;
  files_new: number;
  files_modified: number;
  files_missing: number;
  files_errored: number;
  error_message: string | null;
}

export interface ScanStatusResponse {
  source_directory_id: number;
  scan_status: ScanStatus;
  last_scanned_at: string | null;
  latest_run: ScanRun | null;
}

export interface SourceDirectoryCreate {
  name: string;
  mount_path: string;
  recursive?: boolean;
  enabled?: boolean;
  include_extensions?: string[];
  exclude_patterns?: string[];
}

export interface AssetQuery {
  page: number;
  page_size: number;
  q?: string;
  status?: AssetStatus | "";
  source_directory_id?: number;
}
