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
  generation?: number;
  retired?: boolean; // PR-C：历史分析代次（只读）
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

// 每产品绑定计数（只读聚合，/products/stats）。
export interface ProductStats {
  product_id: number;
  asset_count: number;
  shot_count: number;
  confirmed_shot_count: number;
}

export interface ProductStatsListResponse {
  items: ProductStats[];
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

// ===== PR-04 Gate B 语义搜索 / 画面描述匹配（与后端 schemas/search.py 对应）=====
//
// 命名说明：本仓库已有 `ShotSearchQuery`（api.ts，打 /shot-search，PR-03B 结构化筛选）。
// 下列为 Gate B 语义搜索（/search/shots、/match/description）的**独立**契约，互不混用。

export type SearchMode = "hybrid" | "semantic" | "lexical" | "structured";
// 固定方向：relevance/quality/latest 降序、duration 升序（后端 _reorder）。
export type SearchSort = "relevance" | "latest" | "duration" | "quality";
// 受控画幅白名单（AspectRatio StrEnum）。
export type AspectRatioValue = "16:9" | "9:16" | "1:1" | "4:3" | "3:4" | "21:9";
export const ASPECT_RATIO_VALUES: AspectRatioValue[] = [
  "16:9",
  "9:16",
  "1:1",
  "4:3",
  "3:4",
  "21:9",
];
export type ParserStatus = "ok" | "degraded";
export type EmbeddingStatus = "ok" | "degraded" | "unavailable";
export type RecommendationLevel = "high" | "medium" | "low" | "not_recommended";
export type SuggestionType =
  | "product"
  | "brand"
  | "scene"
  | "action"
  | "marketing"
  | "shot_type"
  | "tag";

// 搜索请求（page_size ≤ 100；空字段后端按缺省处理）
export interface ShotSearchRequest {
  query?: string;
  product_ids?: number[];
  brands?: string[];
  models?: string[];
  skus?: string[];
  scenes?: string[];
  actions?: string[];
  shot_types?: string[];
  marketing_uses?: string[];
  quality_levels?: string[];
  include_risks?: string[];
  exclude_risks?: string[];
  duration_min?: number | null;
  duration_max?: number | null;
  aspect_ratios?: AspectRatioValue[];
  review_statuses?: ReviewStatus[];
  confirmed_only?: boolean;
  include_excluded?: boolean;
  stale?: boolean | null;
  source_directory_id?: number | null;
  created_from?: string | null;
  created_to?: string | null;
  search_mode?: SearchMode;
  sort?: SearchSort;
  page: number;
  page_size: number;
}

export interface AssetBrief {
  id: number;
  filename: string;
  duration: number | null;
  width: number | null;
  height: number | null;
  orientation: string | null;
  source_directory_id: number | null;
}

export interface ProductBrief {
  id: number;
  name: string;
  brand: string | null;
  model: string | null;
  sku: string | null;
  match_kind: string | null; // sku | model | brand | name | alias | associated
}

// 综合分与分项分（[0,1]；缺失通道为 null，前端绝不当作 0 渲染）
export interface SearchResultItem {
  shot_id: number;
  asset_id: number;
  sequence_no: number;
  start_time: number;
  end_time: number;
  duration: number;
  status: string;
  asset: AssetBrief;
  preview_url: string | null;
  thumbnail_url: string | null;
  keyframe_url: string | null;
  download_url: string | null;
  product: ProductBrief | null;
  score: number;
  match_percent: number;
  semantic_score: number | null;
  lexical_score: number | null;
  tag_score: number | null;
  product_score: number | null;
  quality_score: number;
  review_bonus: number;
  risk_penalty: number;
  matched_reasons: string[];
  unmatched_requirements: string[];
  risk_warnings: string[];
  review_status: string | null;
  review_is_stale: boolean;
  embedding_degraded: boolean;
}

// 自然语言查询解析结果（用于「查询理解」展示与诚实降级）
export interface ParsedSearchQuery {
  original_query: string;
  normalized_query: string;
  positive_terms: string[];
  negative_terms: string[];
  products: string[];
  brands: string[];
  models: string[];
  skus: string[];
  scenes: string[];
  actions: string[];
  shot_types: string[];
  marketing_uses: string[];
  people: string[];
  objects: string[];
  quality_requirements: string[];
  required_risks: string[];
  excluded_risks: string[];
  min_duration: number | null;
  max_duration: number | null;
  aspect_ratios: AspectRatioValue[];
  review_statuses: ReviewStatus[];
  confirmed_only: boolean;
  include_excluded: boolean;
  allow_similar_scene: boolean;
  allow_similar_action: boolean;
  semantic_text: string;
  parser_provider: string;
  parser_model: string;
  parser_status: ParserStatus;
  parser_warnings: string[];
}

export interface ShotSearchResponse {
  items: SearchResultItem[];
  // total = 进入融合排序、可分页的候选数；truncated=false 时即精确匹配数。
  total: number;
  // filtered_total = 满足硬结构化过滤的精确总数（"可检索宇宙"）。
  filtered_total: number;
  truncated: boolean;
  page: number;
  page_size: number;
  search_mode_used: string;
  parser_status: string; // ok | degraded
  parser_provider: string;
  embedding_status: string; // ok | degraded | unavailable
  degraded: boolean;
  degradation_reasons: string[];
  elapsed_ms: number;
  query_plan_summary: Record<string, unknown>;
  parsed_query: ParsedSearchQuery;
}

export interface DescriptionMatchRequest {
  target_description: string;
  product_id?: number | null;
  limit: number;
  minimum_score?: number;
  exclude_risks?: string[];
  confirmed_only?: boolean;
  allow_similar_scene?: boolean;
  allow_similar_action?: boolean;
  duration_min?: number | null;
  duration_max?: number | null;
  aspect_ratios?: AspectRatioValue[];
}

export interface DescriptionMatchItem extends SearchResultItem {
  target_requirements: string[];
  matched_requirements: string[];
  requires_human_confirmation: boolean;
  recommendation_level: RecommendationLevel;
}

export interface DescriptionMatchResponse {
  items: DescriptionMatchItem[];
  // total = 满足硬过滤条件的候选总数（不含 minimum_score 过滤）
  total: number;
  filtered_total: number;
  truncated: boolean;
  minimum_score: number;
  target_requirements: string[];
  search_mode_used: string;
  parser_status: string;
  embedding_status: string;
  degraded: boolean;
  degradation_reasons: string[];
  elapsed_ms: number;
}

export interface SearchSuggestion {
  value: string;
  type: SuggestionType;
}

export interface SuggestionsResponse {
  items: SearchSuggestion[];
}

// 全库镜头拆解完整度（只读聚合，/stats/completeness）。真实计数，前端不估算。
export interface ShotCompleteness {
  total_assets: number;
  total_shots: number;
  ai_analyzed_shots: number;
  ai_failed_shots: number;
  pending_review_shots: number;
  confirmed_shots: number;
  searchable_shots: number;
  risk_shots: number;
}

export interface SearchIndexStatus {
  total_shots: number;
  indexed_documents: number;
  excluded_documents: number;
  completed_embeddings: number;
  degraded_embeddings: number;
  failed_embeddings: number;
  pending_embeddings: number;
  current_embedding_version: string;
  embedding_version_matched: number;
  embedding_version_mismatched: number;
  stale_documents: number;
  last_indexed_at: string | null;
  provider_healthy: boolean;
  provider_detail: string;
}

export interface RebuildAcceptedResponse {
  accepted: boolean;
  scope: string;
  target_id: number | null;
  force_reembed: boolean;
  only_failed: boolean;
  celery_task_id: string | null;
  detail: string;
}

// ===== PR-05 脚本匹配与剪辑清单（与后端 schemas/script.py 对齐）=====

export type ScriptStatus = "draft" | "parsing" | "parsed" | "matched" | "failed";
export type ScriptParseStatus = "pending" | "ok" | "degraded" | "failed";
// 段落匹配状态：pending 从未匹配 / matched 有候选 / gap 真实无结果 / degraded 降级匹配
export type ScriptMatchStatusKind = "pending" | "matched" | "gap" | "degraded";
// 剪辑清单选用状态：locked 锁定 / selected 已选未锁 / recommended 系统推荐 / none 无
export type SelectionStatus = "locked" | "selected" | "recommended" | "none";
export type DurationFitStatus = "fit" | "too_long" | "too_short" | "no_target";

// 段落结构化需求（键白名单与后端 _ALLOWED_STRUCTURED_KEYS 一致）
export interface StructuredRequirements {
  products?: string[];
  scenes?: string[];
  actions?: string[];
  shot_types?: string[];
  marketing_uses?: string[];
  people?: string[];
  objects?: string[];
  quality_requirements?: string[];
  selling_points?: string[];
  must_include?: string[];
}

export interface ScriptProject {
  id: number;
  name: string;
  source_format: string;
  status: ScriptStatus;
  parse_status: ScriptParseStatus;
  parser_provider: string | null;
  parser_model: string | null;
  parser_warnings: string[] | null;
  result_schema_version: number;
  segment_count: number;
  created_at: string;
  updated_at: string;
}

export interface ScriptSegment {
  id: number;
  script_project_id: number;
  order_index: number;
  segment_text: string;
  visual_requirement: string | null;
  normalized_text: string | null;
  target_duration_min: number | null;
  target_duration_max: number | null;
  product_id: number | null;
  structured_requirements: StructuredRequirements | null;
  negative_terms: string[] | null;
  excluded_risks: string[] | null;
  allow_similar_scene: boolean;
  allow_similar_action: boolean;
  current_generation: number;
  selected_shot_id: number | null;
  locked_shot_id: number | null;
  lock_version: number;
  match_status: ScriptMatchStatusKind;
  candidates_stale: boolean;
  parser_warnings: string[] | null;
  created_at: string;
  updated_at: string;
}

export interface ScriptProjectDetail extends ScriptProject {
  raw_script: string;
  segments: ScriptSegment[];
}

export interface ScriptListResponse {
  items: ScriptProject[];
  total: number;
  page: number;
  page_size: number;
}

// 候选镜头（分项分缺失为 null，前端绝不当 0；含展示 brief 与预览 URL）
export interface ScriptCandidate {
  shot_id: number;
  asset_id: number | null;
  rank: number;
  final_score: number;
  semantic_score: number | null;
  lexical_score: number | null;
  tag_score: number | null;
  product_score: number | null;
  quality_score: number | null;
  review_bonus: number | null;
  risk_penalty: number | null;
  matched_reasons: string[];
  unmatched_requirements: string[];
  risk_warnings: string[];
  sequence_no: number | null;
  start_time: number | null;
  end_time: number | null;
  duration: number | null;
  preview_url: string | null;
  thumbnail_url: string | null;
  keyframe_url: string | null;
}

export interface SegmentCandidatesResponse {
  segment_id: number;
  generation: number;
  current_generation: number;
  match_status: ScriptMatchStatusKind;
  candidate_count: number;
  best_score: number | null;
  gap_reasons: string[];
  reshoot_recommendation: string[];
  requires_human_confirmation: boolean;
  degraded: boolean;
  candidates_stale: boolean;
  selected_shot_id: number | null;
  locked_shot_id: number | null;
  lock_version: number;
  candidates: ScriptCandidate[];
}

export interface ScriptMatchResponse {
  script_id: number;
  total_segments: number;
  completed_segments: number[];
  skipped_locked_segments: number[];
  failed_segments: { segment_id: number; error: string }[];
  match_token: string | null;
}

export interface SegmentMatchStatus {
  segment_id: number;
  order_index: number;
  match_status: ScriptMatchStatusKind;
  current_generation: number;
  candidate_count: number;
  best_score: number | null;
  gap_reasons: string[];
  reshoot_recommendation: string[];
  requires_human_confirmation: boolean;
  degraded: boolean;
  candidates_stale: boolean;
  selected_shot_id: number | null;
  locked_shot_id: number | null;
  lock_version: number;
}

export interface ScriptMatchStatusResponse {
  script_id: number;
  total_segments: number;
  matched_segments: number;
  gap_segments: number;
  locked_segments: number;
  selected_segments: number;
  pending_segments: number;
  segments: SegmentMatchStatus[];
}

export interface EditListRow {
  segment_id: number;
  segment_order: number;
  segment_text: string;
  target_duration_min: number | null;
  target_duration_max: number | null;
  selection_status: SelectionStatus;
  match_status: ScriptMatchStatusKind;
  shot_id: number | null;
  asset_id: number | null;
  source_start: number | null;
  source_end: number | null;
  source_duration: number | null;
  suggested_in: number | null;
  suggested_out: number | null;
  suggested_duration: number | null;
  duration_status: DurationFitStatus | null;
  duration_warnings: string[];
  product_name: string | null;
  scene: string | null;
  action: string | null;
  match_score: number | null;
  matched_reasons: string[];
  unmatched_requirements: string[];
  risk_warnings: string[];
  gap_reasons: string[];
  reshoot_recommendation: string[];
  requires_human_confirmation: boolean;
  reused: boolean;
  shot_invalid: boolean;
}

export interface EditListSummary {
  total_segments: number;
  matched_segments: number;
  selected_segments: number;
  locked_segments: number;
  recommended_segments: number;
  gap_segments: number;
  risk_segments: number;
  target_total_duration_min: number | null;
  target_total_duration_max: number | null;
  suggested_total_duration: number;
  duplicate_shot_count: number;
  allocation_warnings: string[];
}

export interface ScriptEditList {
  script_id: number;
  summary: EditListSummary;
  rows: EditListRow[];
}

export interface ScriptExport {
  id: number;
  script_project_id: number;
  status: ExportStatus;
  export_format: string;
  filename: string | null;
  row_count: number | null;
  has_file: boolean;
  error_message: string | null;
  celery_task_id: string | null;
  created_at: string;
  finished_at: string | null;
}

// ---- 请求体 ----

export interface ScriptCreateRequest {
  name: string;
  raw_script: string;
  source_format?: string;
}

export interface SegmentUpdateRequest {
  lock_version: number;
  segment_text?: string;
  visual_requirement?: string | null;
  target_duration_min?: number | null;
  target_duration_max?: number | null;
  product_id?: number | null;
  structured_requirements?: StructuredRequirements;
  negative_terms?: string[];
  excluded_risks?: string[];
  allow_similar_scene?: boolean;
  allow_similar_action?: boolean;
}

export interface ScriptMatchRequest {
  candidate_limit?: number | null;
  match_token?: string | null;
  skip_locked?: boolean;
}

export interface SegmentMatchRequest {
  candidate_limit?: number | null;
  match_token?: string | null;
}

export interface SegmentSelectRequest {
  shot_id: number;
  lock_version: number;
  allow_override?: boolean;
}

export interface SegmentLockRequest {
  shot_id: number;
  lock_version: number;
  allow_override?: boolean;
  force?: boolean;
}

// ===== PR-06A 项目 / 静态镜头集合（与后端 schemas/project.py、collection.py 对齐）=====

export type ProjectStatus = "active" | "archived";
// 项目可见镜头来源：all=三源并集 / asset=素材派生 / explicit=显式加入 / collection=集合内
export type ProjectShotSource = "all" | "asset" | "explicit" | "collection";

export interface Project {
  id: number;
  name: string;
  description: string | null;
  status: ProjectStatus;
  archived_at: string | null;
  lock_version: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectListResponse {
  items: Project[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProjectStats {
  project_id: number;
  asset_count: number;
  visible_shot_count: number;
  explicit_shot_count: number;
  collection_count: number;
  collection_shot_count: number;
  product_count: number;
  script_count: number;
  active_script_count: number;
  locked_segment_count: number;
  gap_segment_count: number;
  completed_script_export_count: number;
  risk_shot_count: number;
  searchable_shot_count: number;
  updated_at: string;
}

export interface ProjectAssetItem {
  order_index: number;
  asset: Asset;
}

export interface ProjectAssetListResponse {
  items: ProjectAssetItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface Collection {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  lock_version: number;
  created_at: string;
  updated_at: string;
  shot_count: number;
}

export interface CollectionListResponse {
  items: Collection[];
  total: number;
  page: number;
  page_size: number;
}

// 批量成员操作结果（completed/skipped/failed；与后端事务语义一致）
export interface BatchFailure {
  id: number;
  error: string;
}

export interface BatchMembershipResult {
  completed: number[];
  skipped: number[];
  failed: BatchFailure[];
}

// ---- 请求体 ----

export interface ProjectCreateRequest {
  name: string;
  description?: string | null;
}

export interface ProjectUpdateRequest {
  lock_version: number;
  name?: string;
  description?: string | null;
}

export interface MemberBatchRequest {
  ids: number[];
  token?: string | null;
}

export interface MemberReorderRequest {
  ids: number[];
  lock_version: number;
}

export interface CollectionCreateRequest {
  name: string;
  description?: string | null;
}

export interface CollectionUpdateRequest {
  lock_version: number;
  name?: string;
  description?: string | null;
}

export interface ProjectShotsQuery {
  source?: ProjectShotSource;
  product_id?: number;
  review_status?: ReviewStatus;
  risk?: string;
  include_excluded?: boolean;
  page: number;
  page_size: number;
}

// ===== PR-06B 导出中心 / 多格式脚本导出 / ZIP 打包 / 保存搜索 / 收藏 / 动态集合 =====
//
// 与后端 schemas（export_center.py / saved_search.py / favorite.py /
// dynamic_collection.py）对齐。所有匹配度/分项分仍只读后端，不在前端重算。

// 导出种类：clip 单镜头片段 / script 脚本剪辑清单 / bundle 多镜头 ZIP 打包
export type ExportKind = "clip" | "script" | "bundle";

// 脚本多格式导出（与后端受控白名单一致）
export type ScriptExportFormat = "csv" | "xlsx" | "json" | "markdown" | "printable";
export const SCRIPT_EXPORT_FORMATS: ScriptExportFormat[] = [
  "csv",
  "xlsx",
  "json",
  "markdown",
  "printable",
];

// 导出中心统一行（合并 clip / script / bundle 三类导出记录）
export interface ExportCenterItem {
  kind: ExportKind;
  id: number;
  export_uuid: string;
  project_id: number | null;
  status: ExportStatus;
  format: string;
  filename: string | null;
  has_file: boolean;
  row_count: number | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  download_url: string;
  download_count: number;
  source: Record<string, unknown>;
}

export interface ExportCenterListResponse {
  items: ExportCenterItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ExportCenterQuery {
  kind?: ExportKind;
  status?: ExportStatus;
  project_id?: number;
  created_from?: string;
  created_to?: string;
  page: number;
  page_size: number;
}

export interface ExportRetryResponse {
  kind: ExportKind;
  id: number;
  status: string;
  detail: string;
}

// ZIP 打包多镜头导出
export type BundleMode = "reencode" | "copy";

export interface BundleCreateRequest {
  shot_ids: number[];
  mode?: BundleMode;
  project_id?: number;
}

export interface BundleAcceptedResponse {
  export_id: number;
  status: ExportStatus;
  celery_task_id: string | null;
  shot_count: number;
  detail: string;
}

// 保存搜索：query 为序列化的搜索请求（后端剥离 page/page_size）
export type SavedSearchKind = "shot_search" | "description_match";

export interface SavedSearch {
  id: number;
  project_id: number | null;
  name: string;
  search_kind: SavedSearchKind;
  query: Record<string, unknown>;
  lock_version: number;
  created_at: string;
  updated_at: string;
}

export interface SavedSearchListResponse {
  items: SavedSearch[];
  total: number;
  page: number;
  page_size: number;
}

export interface SavedSearchCreateRequest {
  name: string;
  search_kind: SavedSearchKind;
  query: Record<string, unknown>;
  project_id?: number;
}

export interface SavedSearchUpdateRequest {
  lock_version: number;
  name?: string;
  query?: Record<string, unknown>;
}

// 收藏：四种目标类型
export type FavoriteTargetType = "asset" | "shot" | "search_result" | "script_match_result";

export interface FavoriteAssetBrief {
  id: number;
  filename: string;
  duration: number | null;
  width: number | null;
  height: number | null;
}

export interface FavoriteOut {
  id: number;
  target_type: FavoriteTargetType;
  asset_id: number | null;
  shot_id: number | null;
  context: Record<string, unknown> | null;
  created_at: string;
  shot?: Shot | null;
  asset?: FavoriteAssetBrief | null;
}

export interface FavoriteListResponse {
  items: FavoriteOut[];
  total: number;
  page: number;
  page_size: number;
}

export interface FavoriteCreateRequest {
  target_type: FavoriteTargetType;
  asset_id?: number;
  shot_id?: number;
  context?: Record<string, unknown>;
}

// 动态集合：随当前素材/搜索索引实时更新，不保存固定镜头成员
export interface DynamicCollection {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  search_kind: SavedSearchKind;
  query: Record<string, unknown>;
  lock_version: number;
  created_at: string;
  updated_at: string;
}

export interface DynamicCollectionListResponse {
  items: DynamicCollection[];
  total: number;
  page: number;
  page_size: number;
}

export interface DynamicCollectionCreateRequest {
  name: string;
  description?: string | null;
  search_kind: SavedSearchKind;
  query: Record<string, unknown>;
}

export interface DynamicCollectionUpdateRequest {
  lock_version: number;
  name?: string;
  description?: string | null;
  search_kind?: SavedSearchKind;
  query?: Record<string, unknown>;
}

// ===== PR-A1 通用产品目录（Category → Family → Variant → SKU + Alias）=====
//
// 与后端 schemas/product_catalog.py 对齐。与既有扁平 `Product`（/api/products）**并存**。
// 关键约束：产品名/层级/别名值全部来自 API，前端绝不硬编码任何具体产品；
// 仅生命周期状态与别名类型是受控枚举常量（非产品值）。

// 目录节点层级
export type CatalogLevel = "category" | "family" | "variant" | "sku";

// 生命周期状态（与后端 CatalogStatus 一致）
export type CatalogStatus = "draft" | "active" | "paused" | "archived" | "merged";

// 别名类型（受控枚举常量，非产品值；与后端 CATALOG_ALIAS_TYPES 一致）
export type CatalogAliasType =
  | "zh_name"
  | "en_name"
  | "short_name"
  | "folder_alias"
  | "historical_name"
  | "sku_alias";

export const CATALOG_ALIAS_TYPES: CatalogAliasType[] = [
  "zh_name",
  "en_name",
  "short_name",
  "folder_alias",
  "historical_name",
  "sku_alias",
];

// 生命周期状态下拉/筛选可用值（非产品值，受控枚举）
export const CATALOG_STATUSES: CatalogStatus[] = [
  "draft",
  "active",
  "paused",
  "archived",
  "merged",
];

export interface Category {
  id: number;
  code: string;
  name_zh: string;
  name_en: string | null;
  description: string | null;
  status: CatalogStatus;
  sort_order: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface Family {
  id: number;
  code: string;
  category_id: number | null;
  name_zh: string;
  name_en: string | null;
  description: string | null;
  status: CatalogStatus;
  merged_into_id: number | null;
  legacy_product_id: number | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface Variant {
  id: number;
  code: string;
  family_id: number;
  name_zh: string;
  name_en: string | null;
  description: string | null;
  status: CatalogStatus;
  merged_into_id: number | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface Sku {
  id: number;
  code: string;
  family_id: number;
  variant_id: number | null;
  sku_code: string | null;
  name_zh: string;
  name_en: string | null;
  status: CatalogStatus;
  merged_into_id: number | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

// 任意目录实体的联合（各层字段的宽松超集，供跨层泛型 hook/详情复用）
export type CatalogNode = Category | Family | Variant | Sku;

export interface CatalogAlias {
  id: number;
  category_id: number | null;
  family_id: number | null;
  variant_id: number | null;
  sku_id: number | null;
  alias: string;
  normalized_alias: string;
  language: string | null;
  alias_type: string;
  is_primary: boolean;
}

// 只读层级树节点（/product-catalog/tree）
export interface CatalogTreeNode {
  level: CatalogLevel;
  id: number | null;
  code: string;
  name_zh: string;
  name_en: string | null;
  status: CatalogStatus;
  children: CatalogTreeNode[];
}

// 跨层级搜索 / 解析节点（/product-catalog/search、/resolve）
export interface CatalogSearchNode {
  level: CatalogLevel;
  id: number | null;
  code: string;
  name_zh: string;
  name_en: string | null;
  sku_code: string | null;
  status: CatalogStatus;
  redirected: boolean | null;
}

// 歧义安全解析结果（/product-catalog/resolve）。
// resolved：唯一命中 canonical；ambiguous：多个候选需人工选择；not_found：无命中。
export type CatalogResolveStatus = "resolved" | "ambiguous" | "not_found";

export interface CatalogResolveResult {
  status: CatalogResolveStatus;
  canonical: CatalogSearchNode | null;
  candidates: CatalogSearchNode[];
}

// ---- 列表响应（各层 { items, total } 分页）----
export interface CatalogListResponse<T> {
  items: T[];
  total: number;
}

// ---- 列表查询参数 ----
export interface CategoryListQuery {
  q?: string;
  status_filter?: CatalogStatus;
  include_archived?: boolean;
  limit?: number;
  offset?: number;
}

export interface FamilyListQuery extends CategoryListQuery {
  category_id?: number;
}

export interface VariantListQuery extends CategoryListQuery {
  family_id?: number;
}

export interface SkuListQuery extends CategoryListQuery {
  family_id?: number;
  variant_id?: number;
}

// ---- 请求体 ----
export interface CategoryCreateRequest {
  code?: string;
  name_zh: string;
  name_en?: string;
  description?: string;
  sort_order?: number;
}

export interface CategoryUpdateRequest {
  name_zh?: string;
  name_en?: string | null;
  description?: string | null;
  sort_order?: number;
}

export interface FamilyCreateRequest {
  code?: string;
  category_id?: number | null;
  name_zh: string;
  name_en?: string;
  description?: string;
  legacy_product_id?: number | null;
}

export interface FamilyUpdateRequest {
  name_zh?: string;
  name_en?: string | null;
  description?: string | null;
  category_id?: number | null;
}

export interface VariantCreateRequest {
  code?: string;
  family_id: number;
  name_zh: string;
  name_en?: string;
  description?: string;
}

export interface VariantUpdateRequest {
  name_zh?: string;
  name_en?: string | null;
  description?: string | null;
}

export interface SkuCreateRequest {
  code?: string;
  family_id: number;
  variant_id?: number | null;
  sku_code?: string;
  name_zh: string;
  name_en?: string;
}

export interface SkuUpdateRequest {
  name_zh?: string;
  name_en?: string | null;
  sku_code?: string;
}

export interface CatalogAliasCreateRequest {
  target_level: CatalogLevel;
  target_id: number;
  alias: string;
  language?: string;
  alias_type?: CatalogAliasType;
  is_primary?: boolean;
}

export interface CatalogAliasUpdateRequest {
  alias?: string;
  language?: string | null;
  alias_type?: CatalogAliasType;
  is_primary?: boolean;
}

export interface CatalogStatusRequest {
  status: CatalogStatus;
}

export interface CatalogMergeRequest {
  target_id: number;
}

// ===== PR-A2 动态产品属性 + 产品参考图库 =====
//
// 与后端 schemas（product_attribute.py / product_reference.py / catalog profile）对齐。
// 关键约束：属性定义、允许值、单位、参考图角度/状态全部来自 API 或受控枚举常量，
// 前端**绝不硬编码任何具体公司产品属性**；参考文件按 id 引用（/file、/thumbnail），绝不用路径。

// 属性值类型（受控枚举常量，决定渲染控件与 value 序列化方式）
export type AttributeValueType =
  | "text"
  | "number"
  | "boolean"
  | "enum"
  | "multi_enum"
  | "measurement"
  | "date";

export const ATTRIBUTE_VALUE_TYPES: AttributeValueType[] = [
  "text",
  "number",
  "boolean",
  "enum",
  "multi_enum",
  "measurement",
  "date",
];

// 属性定义（category 级或全局 category_id=null；四态生命周期）
export interface AttributeDefinition {
  id: number;
  category_id: number | null;
  key: string;
  name_zh: string;
  name_en: string | null;
  description: string | null;
  value_type: AttributeValueType;
  unit: string | null;
  allowed_values: string[] | null;
  validation_rules: Record<string, unknown> | null;
  required: boolean;
  searchable: boolean;
  identity_relevant: boolean;
  multi_value: boolean;
  sort_order: number;
  status: CatalogStatus;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

// 属性值（按 value_type 只有对应列非空；软删保留历史）
export interface AttributeValue {
  id: number;
  definition_id: number;
  family_id: number | null;
  variant_id: number | null;
  sku_id: number | null;
  value_text: string | null;
  value_number: number | null;
  value_boolean: boolean | null;
  value_json: string[] | null;
  value_date: string | null;
  unit: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

// 目标层级（属性值 / 参考图共用；无 category —— category 层不承载属性值/参考图）
export type AttributeTargetLevel = "family" | "variant" | "sku";

// upsert 的 value 联合：类型由 definition.value_type 决定
export type AttributeValueInput = string | number | boolean | string[] | null;

export interface AttributeDefinitionListQuery {
  category_id?: number;
  include_global?: boolean;
  status_filter?: CatalogStatus;
  searchable?: boolean;
  identity_relevant?: boolean;
  include_archived?: boolean;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface AttributeDefinitionListResponse {
  items: AttributeDefinition[];
  total: number;
}

export interface AttributeDefinitionCreateRequest {
  category_id?: number | null;
  key?: string;
  name_zh: string;
  name_en?: string;
  description?: string;
  value_type: AttributeValueType;
  unit?: string;
  allowed_values?: string[];
  validation_rules?: Record<string, unknown>;
  required?: boolean;
  searchable?: boolean;
  identity_relevant?: boolean;
  multi_value?: boolean;
  sort_order?: number;
}

export interface AttributeDefinitionUpdateRequest {
  name_zh?: string;
  name_en?: string | null;
  description?: string | null;
  unit?: string | null;
  allowed_values?: string[];
  validation_rules?: Record<string, unknown>;
  required?: boolean;
  searchable?: boolean;
  identity_relevant?: boolean;
  sort_order?: number;
}

export interface AttributeValueUpsertRequest {
  definition_id: number;
  target_level: AttributeTargetLevel;
  target_id: number;
  value: AttributeValueInput;
}

export interface AttributeValueListQuery {
  target_level: AttributeTargetLevel;
  target_id: number;
  include_archived?: boolean;
}

// ---- 参考图库 ----

// 角度白名单（受控枚举常量，非产品值）
export type ReferenceAngle =
  | "front"
  | "back"
  | "left"
  | "right"
  | "top"
  | "bottom"
  | "interface"
  | "package"
  | "installed"
  | "powered_on"
  | "powered_off"
  | "detail"
  | "other";

export const REFERENCE_ANGLES: ReferenceAngle[] = [
  "front",
  "back",
  "left",
  "right",
  "top",
  "bottom",
  "interface",
  "package",
  "installed",
  "powered_on",
  "powered_off",
  "detail",
  "other",
];

// 参考图状态白名单（rejected/archived 默认从列表隐藏）
export type ReferenceState = "draft" | "active" | "rejected" | "archived";

export const REFERENCE_STATES: ReferenceState[] = [
  "draft",
  "active",
  "rejected",
  "archived",
];

// 人工质量标记白名单（非 AI 判定；unchecked=未标记）
export type QualityStatus =
  | "unchecked"
  | "qualified"
  | "blurred"
  | "occluded"
  | "wrong_product"
  | "duplicate"
  | "low_resolution";

export const QUALITY_STATUSES: QualityStatus[] = [
  "unchecked",
  "qualified",
  "blurred",
  "occluded",
  "wrong_product",
  "duplicate",
  "low_resolution",
];

export interface ReferenceAsset {
  id: number;
  family_id: number | null;
  variant_id: number | null;
  sku_id: number | null;
  media_type: string;
  angle: ReferenceAngle | null;
  state: ReferenceState;
  quality_status: QualityStatus;
  is_primary: boolean;
  sort_order: number;
  width: number | null;
  height: number | null;
  file_size: number | null;
  sha256: string | null;
  original_filename: string | null;
  content_type: string | null;
  description: string | null;
  source_type: string | null;
  has_thumbnail: boolean;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

// 多图上传结果：单张失败进 errors，不影响其它成功图
export interface ReferenceUploadError {
  filename: string;
  detail: string;
}

export interface ReferenceUploadResponse {
  created: ReferenceAsset[];
  errors: ReferenceUploadError[];
}

export interface ReferenceListQuery {
  target_level: AttributeTargetLevel;
  target_id: number;
  include_archived?: boolean;
}

export interface ReferenceUpdateRequest {
  angle?: ReferenceAngle | null;
  quality_status?: QualityStatus;
  state?: ReferenceState;
  description?: string | null;
  sort_order?: number;
}

// ---- 目录资料完整度 profile（只读聚合）----
// ai_recognition_enabled 恒为 false —— 自动识别尚未启用，前端绝不伪造识别结果。
export interface CatalogProfile {
  level: CatalogLevel;
  id: number;
  code: string;
  name_zh: string;
  category_id: number | null;
  definition_count: number;
  value_count: number;
  required_total: number;
  required_filled: number;
  missing_required: { definition_id: number; key: string; name_zh: string }[];
  completeness: number | null;
  reference_total: number;
  reference_by_angle: Record<string, number>;
  reference_primary_id: number | null;
  ai_recognition_enabled: boolean;
}

// ===== PR-A2 Gate B 产品入驻治理（完整度策略 / readiness / 入驻审核 / 混淆关系 / 变更历史）=====
//
// 与后端 schemas/product_governance.py 对齐。关键约束：
//   - readiness 分数/检查项全部由后端基于真实数据计算，前端只展示、绝不重算或伪造；
//   - 入驻审核为「可信内网人工审核」，无用户权限体系，actor_label 仅为显示名；
//   - 混淆关系两侧节点名称来自 API（left/right），前端绝不硬编码任何公司产品名。

// 入驻审核状态（与后端 ONBOARDING_STATUSES 一致；独立于 Catalog 生命周期）
export type OnboardingStatus =
  | "incomplete"
  | "ready_for_review"
  | "approved"
  | "needs_changes"
  | "blocked";

export const ONBOARDING_STATUSES: OnboardingStatus[] = [
  "incomplete",
  "ready_for_review",
  "approved",
  "needs_changes",
  "blocked",
];

// 混淆关系严重程度（人工判定，受控枚举）
export type ConfusionSeverity = "low" | "medium" | "high";

export const CONFUSION_SEVERITIES: ConfusionSeverity[] = ["low", "medium", "high"];

// ---- 完整度策略（category 级；draft → activate 生效，版本单调递增）----
export interface ReadinessPolicy {
  id: number;
  category_id: number;
  version: number;
  name: string;
  min_reference_count: number;
  required_angles: string[] | null;
  min_identity_attribute_count: number;
  require_primary_reference: boolean;
  require_name_en: boolean;
  require_alias: boolean;
  require_sku_for_active_variant: boolean;
  status: CatalogStatus;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface ReadinessPolicyCreateRequest {
  category_id: number;
  name?: string;
  min_reference_count?: number;
  required_angles?: string[];
  min_identity_attribute_count?: number;
  require_primary_reference?: boolean;
  require_name_en?: boolean;
  require_alias?: boolean;
  require_sku_for_active_variant?: boolean;
}

export interface ReadinessPolicyListQuery {
  category_id?: number;
  include_archived?: boolean;
}

// ---- Readiness 计算结果（后端确定性计算；policy_version=0 表示系统默认策略）----
export interface ReadinessCheck {
  key: string;
  passed: boolean;
  current: unknown;
  required: unknown;
}

export interface ReadinessMissingItem {
  key: string;
  current: unknown;
  required: unknown;
}

export interface ReadinessBlockingItem {
  key: string;
  detail: string;
}

export interface ReadinessResult {
  target_level: AttributeTargetLevel;
  target_id: number;
  score: number;
  complete: boolean;
  policy_id: number | null;
  policy_version: number;
  checks: ReadinessCheck[];
  missing_items: ReadinessMissingItem[];
  blocking_items: ReadinessBlockingItem[];
  evaluated_at: string;
  // 恒为 false：完整度只是资料统计，不代表 AI 已能识别该产品
  ai_recognition_enabled: boolean;
}

// ---- 入驻审核（每目标一条当前记录；历史进变更历史）----
export interface OnboardingReview {
  id: number;
  family_id: number | null;
  variant_id: number | null;
  sku_id: number | null;
  status: OnboardingStatus;
  policy_id: number | null;
  policy_version: number | null;
  readiness_score: number | null;
  readiness_snapshot: Record<string, unknown> | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  reviewer_note: string | null;
  submitted_by: string | null;
  reviewed_by: string | null;
  created_at: string;
  updated_at: string;
}

// 审核动作请求体（note=审核意见；actor_label=非可信显示名，非登录身份）
export interface OnboardingActionRequest {
  note?: string;
  actor_label?: string;
}

// 审核动作种类（映射到后端 submit-review / approve / request-changes / block）
export type OnboardingActionKind = "submit" | "approve" | "request" | "block";

// ---- 易混淆产品关系（同层级、无方向；left/right 经 canonical 排序）----
export interface ConfusionFeature {
  feature: string;
  left_value: string;
  right_value: string;
  visible_in_reference: boolean;
  identity_relevant: boolean;
}

// 混淆对一侧节点的展示信息（对方名称来自 API，绝不硬编码）
export interface ConfusionSide {
  id: number;
  name_zh: string;
  code: string | null;
  status: CatalogStatus;
}

export interface ConfusionPair {
  id: number;
  target_level: AttributeTargetLevel;
  left_target_id: number;
  right_target_id: number;
  severity: ConfusionSeverity;
  reason: string | null;
  distinguishing_features: ConfusionFeature[] | null;
  review_note: string | null;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  left: ConfusionSide | null;
  right: ConfusionSide | null;
}

export interface ConfusionPairCreateRequest {
  target_level: AttributeTargetLevel;
  left_target_id: number;
  right_target_id: number;
  severity?: ConfusionSeverity;
  reason?: string;
  distinguishing_features?: ConfusionFeature[];
  review_note?: string;
}

export interface ConfusionPairUpdateRequest {
  severity?: ConfusionSeverity;
  reason?: string | null;
  distinguishing_features?: ConfusionFeature[];
  review_note?: string | null;
}

// ---- 目录变更历史（append-only 只读；before/after 为后端脱敏白名单快照）----
export interface CatalogRevision {
  id: number;
  revision_number: number;
  entity_type: string;
  entity_id: number;
  action: string;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
  change_summary: string | null;
  correlation_id: string;
  actor_label: string | null;
  created_at: string;
}

// ============================================================
// PR-B 最终成片 / 使用血缘
// 使用次数一律为后端派生统计（只读）；前端绝不允许直接编辑数字。
// ============================================================

export type FinalVideoStatus = "draft" | "ready" | "completed" | "archived";
export type UsageStatus = "proposed" | "suspected" | "confirmed" | "rejected" | "revoked";
export type UsageEvidenceMethod =
  | "manual"
  | "clipmind_project"
  | "editor_project"
  | "visual_match"
  | "audio_match"
  | "legacy_path_rule";

export interface FinalVideoUsageStats {
  source_shot_count: number;
  confirmed_count: number;
  proposed_count: number;
  suspected_count: number;
  rejected_count: number;
  revoked_count: number;
}

export interface FinalVideo {
  id: number;
  asset_id: number;
  project_id: number | null;
  script_project_id: number | null;
  title: string;
  description: string | null;
  version_label: string | null;
  status: FinalVideoStatus;
  completed_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  asset_filename: string | null;
  asset_duration: number | null;
  asset_has_poster: boolean;
  project_name: string | null;
  script_project_name: string | null;
  usage_stats: FinalVideoUsageStats;
}

export interface FinalVideoListResponse {
  items: FinalVideo[];
  total: number;
  page: number;
  page_size: number;
}

export interface FinalVideoCreateRequest {
  asset_id: number;
  title: string;
  description?: string;
  version_label?: string;
  project_id?: number;
  script_project_id?: number;
  status?: Exclude<FinalVideoStatus, "archived">;
  completed_at?: string;
}

export interface FinalVideoUpdateRequest {
  title?: string;
  description?: string | null;
  version_label?: string | null;
  project_id?: number | null;
  script_project_id?: number | null;
  status?: Exclude<FinalVideoStatus, "archived">;
  completed_at?: string | null;
}

export interface FinalVideoUsage {
  id: number;
  final_video_id: number;
  source_shot_id: number;
  source_asset_id: number;
  source_shot_generation: number | null;
  status: UsageStatus;
  evidence_method: UsageEvidenceMethod;
  confidence: number | null;
  evidence_summary: string | null;
  evidence_refs: Record<string, unknown> | null;
  confirmed_at: string | null;
  rejected_at: string | null;
  revoked_at: string | null;
  actor_label: string | null;
  review_note: string | null;
  created_at: string;
  updated_at: string;
  shot: Shot | null;
  source_asset_filename: string | null;
  occurrence_count: number;
  product_name: string | null;
}

export interface UsageCreateRequest {
  source_shot_id: number;
  evidence_summary?: string;
  confidence?: number;
  actor_label?: string;
  review_note?: string;
}

export interface UsageActionRequest {
  actor_label?: string;
  note?: string;
}

export interface UsageOccurrence {
  id: number;
  usage_id: number;
  occurrence_index: number;
  source_start_ms: number;
  source_end_ms: number;
  final_start_ms: number;
  final_end_ms: number;
  created_at: string;
  updated_at: string;
}

export interface OccurrenceCreateRequest {
  source_start_ms: number;
  source_end_ms: number;
  final_start_ms: number;
  final_end_ms: number;
}

export interface ProposeFromProjectResult {
  created: number;
  existing: number;
  skipped_unavailable: number;
  conflicts: number;
  segments_scanned: number;
  created_usage_ids: number[];
}

export interface UsageEvent {
  id: number;
  usage_id: number;
  action: string;
  before_status: string | null;
  after_status: string | null;
  actor_label: string | null;
  note: string | null;
  created_at: string;
}

export interface FinalVideoBrief {
  final_video_id: number;
  title: string;
  status: FinalVideoStatus;
  confirmed_at: string | null;
}

export interface ShotUsageSummary {
  shot_id: number;
  confirmed_usage_count: number;
  proposed_count: number;
  suspected_count: number;
  last_used_at: string | null;
  final_videos: FinalVideoBrief[];
}

export interface ShotUsageCount {
  shot_id: number;
  confirmed_usage_count: number;
  proposed_count: number;
}

export interface AssetUsageSummary {
  asset_id: number;
  total_shots: number;
  used_shot_count: number;
  never_used_shot_count: number;
  distinct_final_video_count: number;
  usage_distribution: Record<string, number>;
  last_used_at: string | null;
  // PR-C Gate B：历史弱证据（并列展示，绝不并入 confirmed 统计）
  confirmed_usage_count: number;
  accepted_legacy_evidence_count: number;
  pending_legacy_evidence_count: number;
  rejected_legacy_evidence_count: number;
  conflict_legacy_evidence_count: number;
  legacy_usage_state: LegacyUsageState;
  usage_count_known: boolean;
  final_video_known: boolean;
}

export interface UsageWithOccurrences extends FinalVideoUsage {
  occurrences: UsageOccurrence[];
}

export interface FinalVideoLineage {
  final_video: FinalVideo;
  usages: UsageWithOccurrences[];
}

export interface FinalVideoListQuery {
  page: number;
  page_size: number;
  status?: FinalVideoStatus;
  project_id?: number;
  q?: string;
  include_archived?: boolean;
}

// ============================================================
// PR-C Gate B 历史使用证据（弱证据）
// accept 只代表"该素材很可能曾被使用过"——次数/来源 Shot/成片均未知；
// 绝不等于 confirmed 使用次数，前端绝不显示为"已使用 N 次"。
// ============================================================

export type LegacyMatchTarget =
  | "directory_segment"
  | "filename"
  | "filename_stem"
  | "extension"
  | "relative_path";
export type LegacyMatchOperator = "equals" | "contains" | "starts_with" | "ends_with";
export type LegacyReviewStatus = "pending" | "accepted" | "rejected" | "conflict";
export type LegacyUsageState =
  | "no_legacy_evidence"
  | "legacy_evidence_pending"
  | "legacy_used_unknown"
  | "legacy_evidence_rejected"
  | "legacy_evidence_conflict";
export type LegacyImportRunStatus =
  | "pending"
  | "running"
  | "completed"
  | "completed_with_errors"
  | "failed"
  | "cancelled";

export interface LegacyUsageRule {
  id: number;
  name: string;
  description: string | null;
  source_directory_id: number | null;
  source_directory_name: string | null;
  match_target: LegacyMatchTarget;
  match_operator: LegacyMatchOperator;
  pattern: string;
  case_sensitive: boolean;
  include_present_locations: boolean;
  include_missing_locations: boolean;
  include_historical_locations: boolean;
  enabled: boolean;
  priority: number;
  // 语义版本（影响匹配语义的修改 +1；展示字段修改不加）
  version: number;
  snapshot_hash: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  evidence_count: number;
}

export interface LegacyRuleCreateRequest {
  name: string;
  description?: string;
  source_directory_id?: number;
  match_target: LegacyMatchTarget;
  match_operator: LegacyMatchOperator;
  pattern: string;
  case_sensitive?: boolean;
  include_present_locations?: boolean;
  include_missing_locations?: boolean;
  include_historical_locations?: boolean;
  priority?: number;
}

export interface LegacyRuleUpdateRequest {
  name?: string;
  description?: string | null;
  source_directory_id?: number | null;
  match_target?: LegacyMatchTarget;
  match_operator?: LegacyMatchOperator;
  pattern?: string;
  case_sensitive?: boolean;
  include_present_locations?: boolean;
  include_missing_locations?: boolean;
  include_historical_locations?: boolean;
  priority?: number;
}

export interface LegacyRuleListResponse {
  items: LegacyUsageRule[];
  total: number;
}

export interface LegacyImportRequest {
  source_directory_id?: number;
  rule_ids?: number[];
  dry_run?: boolean;
  actor_label?: string;
}

export interface LegacyPreviewSample {
  asset_id: number;
  relative_path: string;
  location_status: string;
  rule_id: number;
  rule_name: string;
  matched_component: string;
  already_exists: boolean;
}

export interface LegacyPreview {
  scanned_location_count: number;
  matched_location_count: number;
  matched_asset_count: number;
  would_create_count: number;
  existing_evidence_count: number;
  conflict_count: number;
  error_count: number;
  by_rule: Record<string, number>;
  by_location_status: Record<string, number>;
  samples: LegacyPreviewSample[];
}

export interface LegacyImportRun {
  id: number;
  source_directory_id: number | null;
  status: LegacyImportRunStatus;
  dry_run: boolean;
  location_scope: string[] | null;
  scanned_location_count: number;
  matched_location_count: number;
  matched_asset_count: number;
  created_evidence_count: number;
  existing_evidence_count: number;
  conflict_count: number;
  error_count: number;
  error_summary: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface LegacyImportRunListResponse {
  items: LegacyImportRun[];
  total: number;
}

export interface LegacyEvidence {
  id: number;
  asset_id: number;
  asset_filename: string | null;
  asset_status: string | null;
  product_name: string | null;
  asset_location_id: number | null;
  location_relative_path: string | null;
  location_status: string | null;
  source_root_name: string | null;
  rule_id: number | null;
  rule_name: string | null;
  // 证据来源规则的语义版本（快照冻结）
  rule_version: number;
  evidence_type: string;
  matched_target: LegacyMatchTarget;
  matched_component: string;
  review_status: LegacyReviewStatus;
  review_note: string | null;
  actor_label: string | null;
  first_observed_at: string;
  last_observed_at: string;
  observation_count: number;
  reviewed_at: string | null;
  created_at: string;
  confirmed_usage_count: number;
  has_final_video_usage: boolean;
}

export interface LegacyEvidenceListResponse {
  items: LegacyEvidence[];
  total: number;
  page: number;
  page_size: number;
}

export interface LegacyReviewActionRequest {
  actor_label?: string;
  note?: string;
}

export interface LegacyBulkReviewRequest {
  evidence_ids: number[];
  actor_label?: string;
  note?: string;
}

export interface LegacyBulkReviewResult {
  succeeded: number;
  skipped: number;
  failed: number;
  skipped_ids: number[];
}

export interface LegacyEvidenceEvent {
  id: number;
  evidence_id: number;
  action: string;
  before_status: string | null;
  after_status: string | null;
  actor_label: string | null;
  note: string | null;
  created_at: string;
}

export interface AssetLegacySummary {
  asset_id: number;
  legacy_usage_state: LegacyUsageState;
  accepted_count: number;
  pending_count: number;
  rejected_count: number;
  conflict_count: number;
  evidences: LegacyEvidence[];
}

// ============================================================
// PR-C 稳定素材身份 / 位置历史 / 指纹任务 / 分析代次
// 哈希只有缩短形式;绝不含绝对路径。
// ============================================================

export type LocationStatus = "present" | "missing" | "historical" | "conflict";
export type FingerprintState = "pending" | "quick_ready" | "full_ready" | "failed" | "stale";

export interface AssetLocationEntry {
  id: number;
  source_root_id: number;
  source_root_name: string | null;
  relative_path: string;
  location_status: LocationStatus;
  is_primary: boolean;
  file_size: number | null;
  first_seen_at: string;
  last_seen_at: string;
  missing_at: string | null;
  verified_at: string | null;
}

export interface AssetIdentity {
  asset_id: number;
  fingerprint_state: FingerprintState;
  quick_fingerprint_short: string | null;
  quick_fingerprint_version: string | null;
  full_hash_short: string | null;
  full_hash_algorithm: string | null;
  full_hash_available: boolean;
  content_size: number | null;
  fingerprinted_at: string | null;
  fingerprint_error: string | null;
  location_count: number;
  present_location_count: number;
  missing_location_count: number;
  conflict_location_count: number;
  primary_location: AssetLocationEntry | null;
  locations: AssetLocationEntry[];
  current_generation: number | null;
  historical_generation_count: number;
}

export interface FingerprintJob {
  id: number;
  kind: "quick" | "full";
  status: "queued" | "running" | "completed" | "partial" | "failed";
  total_count: number;
  completed_count: number;
  skipped_count: number;
  failed_count: number;
  progress: number;
  error_message: string | null;
  results: Record<string, string> | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface AnalysisGeneration {
  generation: number;
  run_id: number;
  status: string;
  is_current: boolean;
  shot_count: number;
  usage_referenced_count: number;
  created_at: string | null;
  finished_at: string | null;
}

export interface AnalysisGenerations {
  asset_id: number;
  current_generation: number | null;
  items: AnalysisGeneration[];
}

// ============================================================
// PR-D 统一使用记录中心（展示统一、事实分离）
// confirmed lineage 永远高于 legacy evidence；两类计数绝不相加；
// 正式使用次数只来自 confirmed FinalVideoUsage。
// ============================================================

export type ReviewItemType = "final_video_usage" | "legacy_usage_evidence";
export type ReviewGroup =
  | "needs_review"
  | "accepted_or_confirmed"
  | "rejected"
  | "conflict"
  | "revoked";
export type SourceStrength =
  | "confirmed_lineage"
  | "manual_proposed_lineage"
  | "project_proposed_lineage"
  | "suspected_lineage"
  | "accepted_legacy_evidence"
  | "pending_legacy_evidence"
  | "rejected_or_conflict";

export interface ReviewItem {
  item_type: ReviewItemType;
  item_id: number;
  review_group: ReviewGroup;
  source_strength: SourceStrength;
  review_status: string;
  asset_id: number | null;
  asset_filename: string | null;
  shot_id: number | null;          // legacy 恒 null（证据没有 Shot）
  shot_sequence_no: number | null;
  final_video_id: number | null;   // legacy 恒 null（证据没有成片）
  final_video_title: string | null;
  product: string | null;
  source_label: string | null;
  evidence_summary: string | null;
  created_at: string;
  last_observed_at: string | null;
  reviewed_at: string | null;
  available_actions: string[];
}

export interface ReviewListResponse {
  items: ReviewItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ReviewSummary {
  formal: {
    confirmed: number;
    proposed: number;
    suspected: number;
    rejected: number;
    revoked: number;
  };
  legacy: {
    pending: number;
    accepted: number;
    rejected: number;
    conflict: number;
  };
  needs_review_total: number;
}

export interface ReviewItemDetail {
  item: ReviewItem;
  formal_usage: Record<string, unknown> | null;
  legacy_evidence: Record<string, unknown> | null;
  events: {
    id: number;
    action: string;
    before_status: string | null;
    after_status: string | null;
    actor_label: string | null;
    note: string | null;
    created_at: string;
  }[];
}

export interface ReviewListQuery {
  page: number;
  page_size: number;
  item_type?: ReviewItemType;
  review_group?: ReviewGroup;
  source_strength?: SourceStrength;
  asset_id?: number;
  final_video_id?: number;
  source_directory_id?: number;
  product_family_id?: number;
  product_variant_id?: number;
  q?: string;
  sort?: string;
}

export interface ReviewBulkRequest {
  items: { item_type: ReviewItemType; item_id: number }[];
  action: string;
  actor_label?: string;
  note?: string;
}

export interface ReviewBulkResult {
  succeeded: number;
  skipped: number;
  failed: number;
  results: {
    item_type: ReviewItemType;
    item_id: number;
    outcome: "succeeded" | "skipped" | "failed";
    reason: string | null;
  }[];
}
