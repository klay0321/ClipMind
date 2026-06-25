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
  has_poster: boolean;
  // PR-03A AI 分析概览（列表接口提供；旧响应可能缺省）
  ai_analysis_status?: AIRunStatus | null;
  ai_analyzed_total?: number;
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

// ===== PR-03A AI 理解分析 =====

export type AIRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled";

export type AIShotAnalysisStatus =
  | "pending"
  | "completed"
  | "degraded"
  | "failed"
  | "skipped";

export interface AIAnalysis {
  asset_id: number;
  has_run: boolean;
  run_id: number | null;
  status: AIRunStatus | null;
  progress: number;
  current_step: string | null;
  total_shots: number;
  analyzed_shots: number;
  failed_shots: number;
  skipped_cached: number;
  degraded: boolean;
  provider: string | null;
  model: string | null;
  error_message: string | null;
  celery_task_id: string | null;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  analyzed_total: number;
}

export interface ProductInfo {
  name: string;
  model: string;
  color: string;
  state: string;
}

// AI 原始结构化结果（PR-03A 不拆解为标签/产品库；待 PR-03B 人工审核）
export interface ShotAnalysisResult {
  one_line: string;
  detailed: string;
  product: ProductInfo;
  scene: string;
  action: string;
  shot_type: string;
  subject: string;
  marketing_use: string[];
  selling_points: string[];
  visible_text: string[];
  logo_brand: string[];
  quality_issues: string[];
  risk_flags: string[];
  confidence: number;
  needs_human_review: boolean;
  search_keywords: string[];
  recommended_scenes: string[];
}

export interface ShotAI {
  shot_id: number;
  has_analysis: boolean;
  status: AIShotAnalysisStatus | null;
  provider: string | null;
  model: string | null;
  confidence: number | null;
  needs_human_review: boolean;
  degraded_reason: string | null;
  result: Partial<ShotAnalysisResult> | null;
  updated_at: string | null;
}

// ===== PR-03B 标签 / 产品库 / 人工审核 =====

export type ReviewStatus =
  | "unreviewed"
  | "pending_review"
  | "confirmed"
  | "modified"
  | "rejected"
  | "unable";

export type ReviewActionKind = "confirm" | "modify" | "reject" | "unable" | "reopen";

export type TagType =
  | "product"
  | "scene"
  | "action"
  | "shot_type"
  | "marketing"
  | "quality"
  | "risk";

export interface ReviewState {
  shot_id: number;
  shot_generation: number;
  review_status: ReviewStatus;
  confirmed_result: Partial<ShotAnalysisResult> | null;
  confirmed_product_id: number | null;
  reviewer_label: string | null;
  review_comment: string | null;
  reviewed_at: string | null;
  stale_at: string | null;
  stale_reason: string | null;
  lock_version: number;
  updated_at: string | null;
}

export interface EffectiveResult {
  shot_id: number;
  review_status: string;
  source: "human" | "ai" | "rejected" | "unable" | "none";
  confirmed: boolean;
  searchable: boolean;
  result: Partial<ShotAnalysisResult> | null;
  ai_status: string | null;
  has_newer_ai_result: boolean;
  review_is_stale: boolean;
  stale_reason: string | null;
}

export interface ReviewEvent {
  id: number;
  action: ReviewActionKind;
  reviewer_label: string | null;
  shot_generation_snapshot: number | null;
  source_ai_analysis_id: number | null;
  comment: string | null;
  created_at: string;
  reviewer_id: number | null;
  // 审计前后快照（append-only 审计层；当前 UI 暂不展示 diff）
  before_data?: Record<string, unknown> | null;
  after_data?: Record<string, unknown> | null;
}

export interface ProductCandidate {
  product_id: number;
  product_name: string;
  brand: string | null;
  model: string | null;
  sku: string | null;
  match_type: string;
  match_score: number;
  match_reason: string;
}

export interface Product {
  id: number;
  brand: string | null;
  name: string;
  model: string | null;
  sku: string | null;
  selling_points: string[] | null;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
}

export interface TagDict {
  id: number;
  tag_type: TagType;
  tag_name: string;
  normalized_name: string;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
}

export interface AssetReviewSummary {
  asset_id: number;
  total_shots: number;
  ai_unanalyzed_count: number;
  ai_running_count: number;
  ai_failed_count: number;
  pending_review_count: number;
  unreviewed_count: number;
  confirmed_count: number;
  modified_count: number;
  rejected_count: number;
  unable_count: number;
  stale_review_count: number;
  risk_shot_count: number;
  primary_product: { id: number; name: string; brand: string | null } | null;
  related_products: { id: number; name: string }[];
  ai_overall_status: string;
}

export interface ReviewActionInput {
  lock_version: number;
  reviewer_label?: string;
  comment?: string;
  confirmed_result?: Partial<ShotAnalysisResult>;
  confirmed_product_id?: number | null;
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
