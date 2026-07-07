// 同源 API 客户端：浏览器只访问 /api/*，由 web 服务端代理到内部 api。

import type {
  AIAnalysis,
  Asset,
  AssetQuery,
  AssetReviewSummary,
  AssetSearchRequest,
  AssetSearchResponse,
  BatchAnalyzeResult,
  DescriptionMatchRequest,
  DescriptionMatchResponse,
  EffectiveResult,
  ExportItem,
  PageResult,
  Product,
  ProductCandidate,
  ProductStatsListResponse,
  ProcessingOverview,
  RebuildAcceptedResponse,
  ReviewActionInput,
  ReviewActionKind,
  ReviewEvent,
  ReviewState,
  ScanRun,
  ScanStatusResponse,
  ScriptCreateRequest,
  ScriptEditList,
  ScriptExport,
  ScriptListResponse,
  ScriptMatchRequest,
  ScriptMatchResponse,
  ScriptMatchStatusResponse,
  ScriptProject,
  ScriptProjectDetail,
  ScriptSegment,
  SearchIndexStatus,
  ShotCompleteness,
  SegmentCandidatesResponse,
  SegmentLockRequest,
  SegmentMatchRequest,
  SegmentSelectRequest,
  SegmentUpdateRequest,
  Shot,
  ShotAI,
  ShotAnalysis,
  ShotDetail,
  ShotQuery,
  ShotSearchRequest,
  ShotSearchResponse,
  SourceDirectory,
  SourceDirectoryCreate,
  SuggestionsResponse,
  TagDict,
  VisualSearchOut,
} from "./types";
import type {
  BatchMembershipResult,
  Collection,
  CollectionCreateRequest,
  CollectionListResponse,
  CollectionUpdateRequest,
  Project,
  ProjectAssetListResponse,
  ProjectCreateRequest,
  ProjectListResponse,
  ProjectShotsQuery,
  ProjectStats,
  ProjectStatus,
  ProjectUpdateRequest,
} from "./types";
import type {
  BundleAcceptedResponse,
  BundleCreateRequest,
  DynamicCollection,
  DynamicCollectionCreateRequest,
  DynamicCollectionListResponse,
  DynamicCollectionUpdateRequest,
  ExportCenterItem,
  ExportCenterListResponse,
  ExportCenterQuery,
  ExportKind,
  ExportRetryResponse,
  FavoriteCreateRequest,
  FavoriteListResponse,
  FavoriteOut,
  FavoriteTargetType,
  SavedSearch,
  SavedSearchCreateRequest,
  SavedSearchKind,
  SavedSearchListResponse,
  SavedSearchUpdateRequest,
  ScriptExportFormat,
} from "./types";
import type {
  CatalogAlias,
  CatalogAliasCreateRequest,
  CatalogAliasUpdateRequest,
  CatalogLevel,
  CatalogListResponse,
  CatalogMergeRequest,
  CatalogResolveResult,
  CatalogSearchNode,
  CatalogStatus,
  CatalogTreeNode,
  Category,
  CategoryCreateRequest,
  CategoryListQuery,
  CategoryUpdateRequest,
  Family,
  FamilyCreateRequest,
  FamilyListQuery,
  FamilyUpdateRequest,
  Sku,
  SkuCreateRequest,
  SkuListQuery,
  SkuUpdateRequest,
  Variant,
  VariantCreateRequest,
  VariantListQuery,
  VariantUpdateRequest,
} from "./types";
import type {
  AttributeDefinition,
  AttributeDefinitionCreateRequest,
  AttributeDefinitionListQuery,
  AttributeDefinitionListResponse,
  AttributeDefinitionUpdateRequest,
  AttributeTargetLevel,
  AttributeValue,
  AttributeValueListQuery,
  AttributeValueUpsertRequest,
  CatalogProfile,
  ReferenceAsset,
  ReferenceListQuery,
  ReferenceUpdateRequest,
  ReferenceUploadResponse,
} from "./types";
import type {
  CatalogRevision,
  ConfusionPair,
  ConfusionPairCreateRequest,
  ConfusionPairUpdateRequest,
  OnboardingActionRequest,
  OnboardingReview,
  ReadinessPolicy,
  ReadinessPolicyCreateRequest,
  ReadinessPolicyListQuery,
  ReadinessResult,
} from "./types";
import type {
  AnalysisGenerations,
  AssetIdentity,
  AssetLocationEntry,
  AssetUsageSummary,
  FingerprintJob,
  FinalVideo,
  FinalVideoCreateRequest,
  FinalVideoLineage,
  FinalVideoListQuery,
  FinalVideoListResponse,
  FinalVideoUpdateRequest,
  FinalVideoUsage,
  OccurrenceCreateRequest,
  ProposeFromProjectResult,
  ShotUsageCount,
  ShotUsageSummary,
  UsageActionRequest,
  UsageCreateRequest,
  UsageEvent,
  UsageOccurrence,
} from "./types";
import type {
  ReviewBulkRequest,
  ReviewBulkResult,
  VisualCandidateResponse,
  FamilyMediaSummary,
  PMBulkResult,
  PmOperation,
  ProductMediaLink,
  ProductMediaPage,
  UnassignedGroups,
  ProductSuggestion,
  ShotLinksView,
  VisualCoverage,
  VisualStatus,
  ReviewItemDetail,
  ReviewItemType,
  ReviewListQuery,
  ReviewListResponse,
  ReviewSummary,
} from "./types";
import type {
  AssetLegacySummary,
  LegacyBulkReviewRequest,
  LegacyBulkReviewResult,
  LegacyEvidence,
  LegacyEvidenceEvent,
  LegacyEvidenceListResponse,
  LegacyImportRequest,
  LegacyImportRun,
  LegacyImportRunListResponse,
  LegacyPreview,
  LegacyReviewActionRequest,
  LegacyReviewStatus,
  LegacyRuleCreateRequest,
  LegacyRuleListResponse,
  LegacyRuleUpdateRequest,
  LegacyUsageRule,
} from "./types";

// 入驻审核动作 → 后端路径段（受控映射，不拼接任意字符串）
export const ONBOARDING_ACTION_PATHS = {
  submit: "submit-review",
  approve: "approve",
  request: "request-changes",
  block: "block",
} as const;

export type OnboardingActionPath =
  (typeof ONBOARDING_ACTION_PATHS)[keyof typeof ONBOARDING_ACTION_PATHS];

export interface ShotSearchQuery {
  asset_id?: number;
  review_status?: string;
  has_ai_result?: boolean;
  stale?: boolean;
  product_id?: number;
  scene?: string;
  action?: string;
  shot_type?: string;
  marketing_use?: string;
  quality?: string;
  risk?: string;
  include_excluded?: boolean;
  sort?: string;
  page: number;
  page_size: number;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

const BASE = "/api";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      // 忽略非 JSON 错误体
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function buildAssetQuery(query: AssetQuery): string {
  const params = new URLSearchParams();
  params.set("page", String(query.page));
  params.set("page_size", String(query.page_size));
  if (query.q) params.set("q", query.q);
  if (query.status) params.set("status", query.status);
  if (query.source_directory_id != null)
    params.set("source_directory_id", String(query.source_directory_id));
  if (query.media_kind) params.set("media_kind", query.media_kind);
  return params.toString();
}

function buildShotQuery(query: ShotQuery): string {
  const params = new URLSearchParams();
  params.set("page", String(query.page));
  params.set("page_size", String(query.page_size));
  if (query.asset_id != null) params.set("asset_id", String(query.asset_id));
  if (query.status) params.set("status", query.status);
  return params.toString();
}

// 资源直链（用于 <img>/<video> src 与下载，浏览器走同源代理，不经 fetch）
export const assetPosterUrl = (id: number) => `/api/assets/${id}/poster`;
export const shotThumbnailUrl = (id: number) => `/api/shots/${id}/thumbnail`;
export const shotKeyframeUrl = (id: number) => `/api/shots/${id}/keyframe`;
export const shotKeyframeAtUrl = (id: number, index: number) =>
  `/api/shots/${id}/keyframe/${index}`;
export const shotPreviewUrl = (id: number) => `/api/shots/${id}/preview`;
export const exportDownloadUrl = (id: number) => `/api/exports/${id}/download`;
// 脚本剪辑清单 CSV 下载（走同源安全代理，浏览器直链不经 fetch）
export const scriptCsvDownloadUrl = (scriptId: number, exportId: number) =>
  `/api/scripts/${scriptId}/exports/${exportId}/download`;
// PR-06B 多格式脚本导出下载（与 CSV 同代理；格式由后端记录决定）
export const scriptExportDownloadUrl = (scriptId: number, exportId: number) =>
  `/api/scripts/${scriptId}/exports/${exportId}/download`;
// PR-06B ZIP 打包导出下载直链
export const bundleDownloadUrl = (id: number) => `/api/exports/bundle/${id}/download`;
// PR-A2 参考图文件直链（<img> 直接用，按 id 引用；缩略缺失后端回退原图）
export const referenceFileUrl = (id: number) => `/api/product-reference-assets/${id}/file`;
export const referenceThumbnailUrl = (id: number) =>
  `/api/product-reference-assets/${id}/thumbnail`;

export const api = {
  listAssets(query: AssetQuery): Promise<PageResult<Asset>> {
    return http<PageResult<Asset>>(`/assets?${buildAssetQuery(query)}`);
  },
  getAsset(id: number): Promise<Asset> {
    return http<Asset>(`/assets/${id}`);
  },
  rescanAsset(id: number): Promise<{ asset_id: number; celery_task_id: string }> {
    return http(`/assets/${id}/rescan`, { method: "POST" });
  },
  // ===== AAP 批量分析 + 全局处理概览 =====
  batchAnalyze(payload: {
    asset_ids?: number[];
    source_directory_id?: number;
    stages: ("shots" | "ai")[];
    max_items?: number;
  }): Promise<BatchAnalyzeResult> {
    return http<BatchAnalyzeResult>(`/assets/batch-analyze`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  searchAssets(req: AssetSearchRequest): Promise<AssetSearchResponse> {
    return http<AssetSearchResponse>(`/search/assets`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  processingOverview(): Promise<ProcessingOverview> {
    return http<ProcessingOverview>(`/processing/overview`);
  },
  listSourceDirectories(): Promise<SourceDirectory[]> {
    return http<SourceDirectory[]>(`/source-directories`);
  },
  createSourceDirectory(payload: SourceDirectoryCreate): Promise<SourceDirectory> {
    return http<SourceDirectory>(`/source-directories`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  scan(id: number): Promise<ScanRun> {
    return http<ScanRun>(`/source-directories/${id}/scan`, { method: "POST" });
  },
  scanStatus(id: number): Promise<ScanStatusResponse> {
    return http<ScanStatusResponse>(`/source-directories/${id}/status`);
  },

  // ===== PR-02 镜头分析 / 镜头 / 导出 =====
  analyzeShots(assetId: number): Promise<{ asset_id: number; run_id: number; status: string }> {
    return http(`/assets/${assetId}/analyze-shots`, { method: "POST" });
  },
  retryShotAnalysis(
    assetId: number,
  ): Promise<{ asset_id: number; run_id: number; status: string }> {
    return http(`/assets/${assetId}/shot-analysis/retry`, { method: "POST" });
  },
  shotAnalysis(assetId: number): Promise<ShotAnalysis> {
    return http<ShotAnalysis>(`/assets/${assetId}/shot-analysis`);
  },
  assetShots(query: ShotQuery): Promise<PageResult<Shot>> {
    return http<PageResult<Shot>>(`/assets/${query.asset_id}/shots?${buildShotQuery(query)}`);
  },
  listShots(query: ShotQuery): Promise<PageResult<Shot>> {
    return http<PageResult<Shot>>(`/shots?${buildShotQuery(query)}`);
  },
  getShot(id: number): Promise<ShotDetail> {
    return http<ShotDetail>(`/shots/${id}`);
  },
  exportShot(id: number, mode = "reencode"): Promise<{ export_id: number; status: string }> {
    return http(`/shots/${id}/export`, {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
  },
  getExport(id: number): Promise<ExportItem> {
    return http<ExportItem>(`/exports/${id}`);
  },

  // ===== PR-03A AI 理解分析 =====
  analyzeAssetAi(
    assetId: number,
  ): Promise<{ asset_id: number; run_id: number; status: string; celery_task_id: string | null }> {
    return http(`/assets/${assetId}/analyze`, { method: "POST" });
  },
  retryAssetAi(
    assetId: number,
  ): Promise<{ asset_id: number; run_id: number; status: string; celery_task_id: string | null }> {
    return http(`/assets/${assetId}/ai-analysis/retry`, { method: "POST" });
  },
  aiAnalysis(assetId: number): Promise<AIAnalysis> {
    return http<AIAnalysis>(`/assets/${assetId}/ai-analysis`);
  },
  analyzeShotAi(
    shotId: number,
  ): Promise<{ asset_id: number; run_id: number; status: string }> {
    return http(`/shots/${shotId}/analyze`, { method: "POST" });
  },
  shotAi(shotId: number): Promise<ShotAI> {
    return http<ShotAI>(`/shots/${shotId}/ai`);
  },

  // ===== PR-03B 审核 / 产品 / 标签 / 汇总 / 筛选 =====
  effectiveResult(shotId: number): Promise<EffectiveResult> {
    return http<EffectiveResult>(`/shots/${shotId}/effective-result`);
  },
  reviewState(shotId: number): Promise<ReviewState> {
    return http<ReviewState>(`/shots/${shotId}/review`);
  },
  reviewEvents(shotId: number): Promise<ReviewEvent[]> {
    return http<ReviewEvent[]>(`/shots/${shotId}/review-events`);
  },
  reviewAction(
    shotId: number,
    action: ReviewActionKind,
    body: ReviewActionInput,
  ): Promise<ReviewState> {
    return http<ReviewState>(`/shots/${shotId}/review/${action}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  productCandidates(shotId: number): Promise<ProductCandidate[]> {
    return http<ProductCandidate[]>(`/shots/${shotId}/product-candidates`);
  },
  reviewSummary(assetId: number): Promise<AssetReviewSummary> {
    return http<AssetReviewSummary>(`/assets/${assetId}/review-summary`);
  },
  shotSearch(query: ShotSearchQuery): Promise<PageResult<Shot>> {
    const p = new URLSearchParams();
    p.set("page", String(query.page));
    p.set("page_size", String(query.page_size));
    for (const k of [
      "asset_id", "review_status", "has_ai_result", "stale", "product_id",
      "scene", "action", "shot_type", "marketing_use", "quality", "risk",
      "include_excluded", "sort",
    ] as const) {
      const v = query[k];
      if (v != null && v !== "") p.set(k, String(v));
    }
    return http<PageResult<Shot>>(`/shot-search?${p.toString()}`);
  },
  listProducts(q?: string): Promise<Product[]> {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    return http<Product[]>(`/products?${p.toString()}`);
  },
  productStats(): Promise<ProductStatsListResponse> {
    return http<ProductStatsListResponse>(`/products/stats`);
  },
  listTags(tagType?: string): Promise<TagDict[]> {
    const p = new URLSearchParams();
    if (tagType) p.set("tag_type", tagType);
    return http<TagDict[]>(`/tags?${p.toString()}`);
  },

  // ===== PR-04 Gate B 语义搜索 / 画面描述匹配（POST JSON）=====
  searchShots(req: ShotSearchRequest, signal?: AbortSignal): Promise<ShotSearchResponse> {
    return http<ShotSearchResponse>(`/search/shots`, {
      method: "POST",
      body: JSON.stringify(req),
      signal,
    });
  },
  matchDescription(
    req: DescriptionMatchRequest,
    signal?: AbortSignal,
  ): Promise<DescriptionMatchResponse> {
    return http<DescriptionMatchResponse>(`/match/description`, {
      method: "POST",
      body: JSON.stringify(req),
      signal,
    });
  },
  searchSuggestions(q?: string, limit = 10): Promise<SuggestionsResponse> {
    const p = new URLSearchParams();
    if (q && q.trim()) p.set("q", q.trim());
    p.set("limit", String(limit));
    return http<SuggestionsResponse>(`/search/suggestions?${p.toString()}`);
  },
  searchIndexStatus(): Promise<SearchIndexStatus> {
    return http<SearchIndexStatus>(`/search/index/status`);
  },
  shotCompleteness(): Promise<ShotCompleteness> {
    return http<ShotCompleteness>(`/stats/completeness`);
  },
  // 管理操作（不进普通用户主流程）：单镜头/单素材重建检索文档
  rebuildSearchShot(shotId: number, forceReembed = false): Promise<RebuildAcceptedResponse> {
    const p = new URLSearchParams();
    if (forceReembed) p.set("force_reembed", "true");
    return http<RebuildAcceptedResponse>(`/search/index/rebuild/shot/${shotId}?${p.toString()}`, {
      method: "POST",
    });
  },
  sweepSearchIndex(limit = 500, forceReembed = false): Promise<RebuildAcceptedResponse> {
    const p = new URLSearchParams();
    p.set("limit", String(limit));
    if (forceReembed) p.set("force_reembed", "true");
    return http<RebuildAcceptedResponse>(`/search/index/sweep?${p.toString()}`, { method: "POST" });
  },
  async uploadAsset(
    file: File,
  ): Promise<{ filename: string; bytes: number; source_directory_id: number; scan_run_id: number }> {
    const fd = new FormData();
    fd.append("file", file);
    // 不手动设 Content-Type，浏览器自动带 multipart boundary
    const res = await fetch(`${BASE}/uploads`, { method: "POST", body: fd });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body?.detail ?? detail;
      } catch {
        // 忽略
      }
      throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return res.json();
  },

  // ===== PR-05 脚本匹配与剪辑清单（Gate A/B；POST/PATCH JSON）=====
  listScripts(page = 1, pageSize = 20): Promise<ScriptListResponse> {
    return http<ScriptListResponse>(`/scripts?page=${page}&page_size=${pageSize}`);
  },
  createScript(req: ScriptCreateRequest): Promise<ScriptProject> {
    return http<ScriptProject>(`/scripts`, { method: "POST", body: JSON.stringify(req) });
  },
  getScript(id: number): Promise<ScriptProjectDetail> {
    return http<ScriptProjectDetail>(`/scripts/${id}`);
  },
  renameScript(id: number, name: string): Promise<ScriptProject> {
    return http<ScriptProject>(`/scripts/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
  },
  parseScript(id: number, parser?: string, force = false): Promise<ScriptProjectDetail> {
    const p = force ? "?force=true" : "";
    return http<ScriptProjectDetail>(`/scripts/${id}/parse${p}`, {
      method: "POST",
      body: JSON.stringify(parser ? { parser } : {}),
    });
  },
  updateSegment(
    scriptId: number,
    segmentId: number,
    req: SegmentUpdateRequest,
  ): Promise<ScriptSegment> {
    return http<ScriptSegment>(`/scripts/${scriptId}/segments/${segmentId}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    });
  },
  reorderSegments(scriptId: number, segmentIds: number[]): Promise<ScriptProjectDetail> {
    return http<ScriptProjectDetail>(`/scripts/${scriptId}/segments/reorder`, {
      method: "POST",
      body: JSON.stringify({ segment_ids: segmentIds }),
    });
  },
  matchScript(scriptId: number, req: ScriptMatchRequest = {}): Promise<ScriptMatchResponse> {
    return http<ScriptMatchResponse>(`/scripts/${scriptId}/match`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  matchSegment(
    scriptId: number,
    segmentId: number,
    req: SegmentMatchRequest = {},
  ): Promise<SegmentCandidatesResponse> {
    return http<SegmentCandidatesResponse>(`/scripts/${scriptId}/segments/${segmentId}/match`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  segmentCandidates(
    scriptId: number,
    segmentId: number,
    generation?: number,
  ): Promise<SegmentCandidatesResponse> {
    const p = generation != null ? `?generation=${generation}` : "";
    return http<SegmentCandidatesResponse>(
      `/scripts/${scriptId}/segments/${segmentId}/candidates${p}`,
    );
  },
  selectCandidate(
    scriptId: number,
    segmentId: number,
    req: SegmentSelectRequest,
  ): Promise<ScriptSegment> {
    return http<ScriptSegment>(`/scripts/${scriptId}/segments/${segmentId}/select`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  lockCandidate(
    scriptId: number,
    segmentId: number,
    req: SegmentLockRequest,
  ): Promise<ScriptSegment> {
    return http<ScriptSegment>(`/scripts/${scriptId}/segments/${segmentId}/lock`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  unlockSegment(scriptId: number, segmentId: number, lockVersion: number): Promise<ScriptSegment> {
    return http<ScriptSegment>(`/scripts/${scriptId}/segments/${segmentId}/unlock`, {
      method: "POST",
      body: JSON.stringify({ lock_version: lockVersion }),
    });
  },
  scriptMatchStatus(scriptId: number): Promise<ScriptMatchStatusResponse> {
    return http<ScriptMatchStatusResponse>(`/scripts/${scriptId}/match-status`);
  },
  scriptEditList(scriptId: number): Promise<ScriptEditList> {
    return http<ScriptEditList>(`/scripts/${scriptId}/edit-list`);
  },
  createScriptCsvExport(scriptId: number): Promise<ScriptExport> {
    return http<ScriptExport>(`/scripts/${scriptId}/exports/csv`, { method: "POST" });
  },
  scriptExportStatus(scriptId: number, exportId: number): Promise<ScriptExport> {
    return http<ScriptExport>(`/scripts/${scriptId}/exports/${exportId}`);
  },

  // ===== PR-06A 项目 / 静态镜头集合 =====
  listProjects(page = 1, pageSize = 20, status?: ProjectStatus): Promise<ProjectListResponse> {
    const p = new URLSearchParams();
    p.set("page", String(page));
    p.set("page_size", String(pageSize));
    if (status) p.set("status", status);
    return http<ProjectListResponse>(`/projects?${p.toString()}`);
  },
  getProject(id: number): Promise<Project> {
    return http<Project>(`/projects/${id}`);
  },
  getProjectStats(id: number): Promise<ProjectStats> {
    return http<ProjectStats>(`/projects/${id}/stats`);
  },
  createProject(req: ProjectCreateRequest): Promise<Project> {
    return http<Project>(`/projects`, { method: "POST", body: JSON.stringify(req) });
  },
  updateProject(id: number, req: ProjectUpdateRequest): Promise<Project> {
    return http<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(req) });
  },
  archiveProject(id: number, lockVersion: number): Promise<Project> {
    return http<Project>(`/projects/${id}/archive`, {
      method: "POST",
      body: JSON.stringify({ lock_version: lockVersion }),
    });
  },
  unarchiveProject(id: number, lockVersion: number): Promise<Project> {
    return http<Project>(`/projects/${id}/unarchive`, {
      method: "POST",
      body: JSON.stringify({ lock_version: lockVersion }),
    });
  },
  projectAssets(id: number, page = 1, pageSize = 24): Promise<ProjectAssetListResponse> {
    return http<ProjectAssetListResponse>(
      `/projects/${id}/assets?page=${page}&page_size=${pageSize}`,
    );
  },
  addProjectAssets(id: number, ids: number[]): Promise<BatchMembershipResult> {
    return http<BatchMembershipResult>(`/projects/${id}/assets/batch`, {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
  },
  removeProjectAsset(id: number, assetId: number): Promise<void> {
    return http<void>(`/projects/${id}/assets/${assetId}`, { method: "DELETE" });
  },
  reorderProjectAssets(id: number, ids: number[], lockVersion: number): Promise<Project> {
    return http<Project>(`/projects/${id}/assets/reorder`, {
      method: "POST",
      body: JSON.stringify({ ids, lock_version: lockVersion }),
    });
  },
  projectShots(id: number, query: ProjectShotsQuery): Promise<PageResult<Shot>> {
    const p = new URLSearchParams();
    p.set("page", String(query.page));
    p.set("page_size", String(query.page_size));
    if (query.source) p.set("source", query.source);
    if (query.product_id != null) p.set("product_id", String(query.product_id));
    if (query.review_status) p.set("review_status", query.review_status);
    if (query.risk) p.set("risk", query.risk);
    if (query.include_excluded) p.set("include_excluded", "true");
    return http<PageResult<Shot>>(`/projects/${id}/shots?${p.toString()}`);
  },
  addProjectShots(id: number, ids: number[]): Promise<BatchMembershipResult> {
    return http<BatchMembershipResult>(`/projects/${id}/shots/batch`, {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
  },
  removeProjectShot(id: number, shotId: number): Promise<void> {
    return http<void>(`/projects/${id}/shots/${shotId}`, { method: "DELETE" });
  },
  reorderProjectShots(id: number, ids: number[], lockVersion: number): Promise<Project> {
    return http<Project>(`/projects/${id}/shots/reorder`, {
      method: "POST",
      body: JSON.stringify({ ids, lock_version: lockVersion }),
    });
  },
  projectProducts(id: number, page = 1, pageSize = 50): Promise<PageResult<Product>> {
    return http<PageResult<Product>>(
      `/projects/${id}/products?page=${page}&page_size=${pageSize}`,
    );
  },
  addProjectProducts(id: number, ids: number[]): Promise<BatchMembershipResult> {
    return http<BatchMembershipResult>(`/projects/${id}/products/batch`, {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
  },
  removeProjectProduct(id: number, productId: number): Promise<void> {
    return http<void>(`/projects/${id}/products/${productId}`, { method: "DELETE" });
  },
  projectScripts(id: number, page = 1, pageSize = 20): Promise<ScriptListResponse> {
    return http<ScriptListResponse>(
      `/projects/${id}/scripts?page=${page}&page_size=${pageSize}`,
    );
  },
  attachProjectScript(id: number, scriptId: number): Promise<ScriptProject> {
    return http<ScriptProject>(`/projects/${id}/scripts/${scriptId}`, { method: "POST" });
  },
  detachProjectScript(id: number, scriptId: number): Promise<ScriptProject> {
    return http<ScriptProject>(`/projects/${id}/scripts/${scriptId}`, { method: "DELETE" });
  },
  listProjectCollections(projectId: number, page = 1, pageSize = 20): Promise<CollectionListResponse> {
    return http<CollectionListResponse>(
      `/projects/${projectId}/collections?page=${page}&page_size=${pageSize}`,
    );
  },
  createCollection(projectId: number, req: CollectionCreateRequest): Promise<Collection> {
    return http<Collection>(`/projects/${projectId}/collections`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  getCollection(id: number): Promise<Collection> {
    return http<Collection>(`/collections/${id}`);
  },
  updateCollection(id: number, req: CollectionUpdateRequest): Promise<Collection> {
    return http<Collection>(`/collections/${id}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    });
  },
  deleteCollection(id: number): Promise<void> {
    return http<void>(`/collections/${id}`, { method: "DELETE" });
  },
  collectionShots(id: number, page = 1, pageSize = 24): Promise<PageResult<Shot>> {
    return http<PageResult<Shot>>(`/collections/${id}/shots?page=${page}&page_size=${pageSize}`);
  },
  addCollectionShots(id: number, ids: number[]): Promise<BatchMembershipResult> {
    return http<BatchMembershipResult>(`/collections/${id}/shots/batch`, {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
  },
  removeCollectionShot(id: number, shotId: number): Promise<void> {
    return http<void>(`/collections/${id}/shots/${shotId}`, { method: "DELETE" });
  },
  reorderCollectionShots(id: number, ids: number[], lockVersion: number): Promise<Collection> {
    return http<Collection>(`/collections/${id}/shots/reorder`, {
      method: "POST",
      body: JSON.stringify({ ids, lock_version: lockVersion }),
    });
  },

  // ===== PR-06B 导出中心（合并 clip / script / bundle）=====
  exportCenter(query: ExportCenterQuery): Promise<ExportCenterListResponse> {
    const p = new URLSearchParams();
    p.set("page", String(query.page));
    p.set("page_size", String(query.page_size));
    if (query.kind) p.set("kind", query.kind);
    if (query.status) p.set("status", query.status);
    if (query.project_id != null) p.set("project_id", String(query.project_id));
    if (query.created_from) p.set("created_from", query.created_from);
    if (query.created_to) p.set("created_to", query.created_to);
    return http<ExportCenterListResponse>(`/export-center?${p.toString()}`);
  },
  exportCenterItem(kind: ExportKind, id: number): Promise<ExportCenterItem> {
    return http<ExportCenterItem>(`/export-center/${kind}/${id}`);
  },
  retryExportCenter(kind: ExportKind, id: number): Promise<ExportRetryResponse> {
    return http<ExportRetryResponse>(`/export-center/${kind}/${id}/retry`, { method: "POST" });
  },
  deleteExportCenter(kind: ExportKind, id: number): Promise<void> {
    return http<void>(`/export-center/${kind}/${id}`, { method: "DELETE" });
  },

  // ===== PR-06B ZIP 打包多镜头导出 =====
  createBundle(req: BundleCreateRequest): Promise<BundleAcceptedResponse> {
    return http<BundleAcceptedResponse>(`/exports/bundle`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  getBundle(id: number): Promise<ExportCenterItem> {
    return http<ExportCenterItem>(`/exports/bundle/${id}`);
  },

  // ===== PR-06B 多格式脚本导出 =====
  createScriptExport(scriptId: number, format: ScriptExportFormat): Promise<ScriptExport> {
    const p = new URLSearchParams();
    p.set("format", format);
    return http<ScriptExport>(`/scripts/${scriptId}/exports?${p.toString()}`, { method: "POST" });
  },

  // ===== PR-06B 保存搜索 =====
  listSavedSearches(
    projectId?: number,
    searchKind?: SavedSearchKind,
    page = 1,
    pageSize = 20,
  ): Promise<SavedSearchListResponse> {
    const p = new URLSearchParams();
    p.set("page", String(page));
    p.set("page_size", String(pageSize));
    if (projectId != null) p.set("project_id", String(projectId));
    if (searchKind) p.set("search_kind", searchKind);
    return http<SavedSearchListResponse>(`/saved-searches?${p.toString()}`);
  },
  getSavedSearch(id: number): Promise<SavedSearch> {
    return http<SavedSearch>(`/saved-searches/${id}`);
  },
  createSavedSearch(req: SavedSearchCreateRequest): Promise<SavedSearch> {
    return http<SavedSearch>(`/saved-searches`, { method: "POST", body: JSON.stringify(req) });
  },
  updateSavedSearch(id: number, req: SavedSearchUpdateRequest): Promise<SavedSearch> {
    return http<SavedSearch>(`/saved-searches/${id}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    });
  },
  deleteSavedSearch(id: number): Promise<void> {
    return http<void>(`/saved-searches/${id}`, { method: "DELETE" });
  },
  runSavedSearch<T>(id: number, page = 1, pageSize = 24): Promise<T> {
    const p = new URLSearchParams();
    p.set("page", String(page));
    p.set("page_size", String(pageSize));
    return http<T>(`/saved-searches/${id}/run?${p.toString()}`, { method: "POST" });
  },

  // ===== PR-06B 收藏 =====
  listFavorites(
    targetType?: FavoriteTargetType,
    page = 1,
    pageSize = 24,
  ): Promise<FavoriteListResponse> {
    const p = new URLSearchParams();
    p.set("page", String(page));
    p.set("page_size", String(pageSize));
    if (targetType) p.set("target_type", targetType);
    return http<FavoriteListResponse>(`/favorites?${p.toString()}`);
  },
  createFavorite(req: FavoriteCreateRequest): Promise<FavoriteOut> {
    return http<FavoriteOut>(`/favorites`, { method: "POST", body: JSON.stringify(req) });
  },
  deleteFavorite(id: number): Promise<void> {
    return http<void>(`/favorites/${id}`, { method: "DELETE" });
  },

  // ===== PR-06B 动态集合 =====
  listDynamicCollections(
    projectId: number,
    page = 1,
    pageSize = 20,
  ): Promise<DynamicCollectionListResponse> {
    return http<DynamicCollectionListResponse>(
      `/projects/${projectId}/dynamic-collections?page=${page}&page_size=${pageSize}`,
    );
  },
  getDynamicCollection(id: number): Promise<DynamicCollection> {
    return http<DynamicCollection>(`/dynamic-collections/${id}`);
  },
  createDynamicCollection(
    projectId: number,
    req: DynamicCollectionCreateRequest,
  ): Promise<DynamicCollection> {
    return http<DynamicCollection>(`/projects/${projectId}/dynamic-collections`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  updateDynamicCollection(
    id: number,
    req: DynamicCollectionUpdateRequest,
  ): Promise<DynamicCollection> {
    return http<DynamicCollection>(`/dynamic-collections/${id}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    });
  },
  deleteDynamicCollection(id: number): Promise<void> {
    return http<void>(`/dynamic-collections/${id}`, { method: "DELETE" });
  },
  dynamicCollectionShots<T>(id: number, page = 1, pageSize = 24): Promise<T> {
    return http<T>(`/dynamic-collections/${id}/shots?page=${page}&page_size=${pageSize}`);
  },

  // ===== PR-A1 通用产品目录（Category / Family / Variant / SKU / Alias + tree/search/resolve）=====
  //
  // 与既有 /products（扁平业务产品）并存。列表 query 全部可选；产品值全部来自后端。

  // ---- Category ----
  listCategories(query: CategoryListQuery = {}): Promise<CatalogListResponse<Category>> {
    return http<CatalogListResponse<Category>>(`/product-categories?${buildCatalogQuery(query)}`);
  },
  createCategory(req: CategoryCreateRequest): Promise<Category> {
    return http<Category>(`/product-categories`, { method: "POST", body: JSON.stringify(req) });
  },
  getCategory(id: number): Promise<Category> {
    return http<Category>(`/product-categories/${id}`);
  },
  updateCategory(id: number, req: CategoryUpdateRequest): Promise<Category> {
    return http<Category>(`/product-categories/${id}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    });
  },
  archiveCategory(id: number): Promise<Category> {
    return http<Category>(`/product-categories/${id}/archive`, { method: "POST" });
  },
  restoreCategory(id: number): Promise<Category> {
    return http<Category>(`/product-categories/${id}/restore`, { method: "POST" });
  },
  setCategoryStatus(id: number, status: CatalogStatus): Promise<Category> {
    return http<Category>(`/product-categories/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
  },

  // ---- Family ----
  listFamilies(query: FamilyListQuery = {}): Promise<CatalogListResponse<Family>> {
    return http<CatalogListResponse<Family>>(`/product-families?${buildCatalogQuery(query)}`);
  },
  createFamily(req: FamilyCreateRequest): Promise<Family> {
    return http<Family>(`/product-families`, { method: "POST", body: JSON.stringify(req) });
  },
  getFamily(id: number): Promise<Family> {
    return http<Family>(`/product-families/${id}`);
  },
  updateFamily(id: number, req: FamilyUpdateRequest): Promise<Family> {
    return http<Family>(`/product-families/${id}`, { method: "PATCH", body: JSON.stringify(req) });
  },
  archiveFamily(id: number): Promise<Family> {
    return http<Family>(`/product-families/${id}/archive`, { method: "POST" });
  },
  restoreFamily(id: number): Promise<Family> {
    return http<Family>(`/product-families/${id}/restore`, { method: "POST" });
  },
  mergeFamily(id: number, req: CatalogMergeRequest): Promise<Family> {
    return http<Family>(`/product-families/${id}/merge`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  setFamilyStatus(id: number, status: CatalogStatus): Promise<Family> {
    return http<Family>(`/product-families/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
  },

  // ---- Variant ----
  listVariants(query: VariantListQuery = {}): Promise<CatalogListResponse<Variant>> {
    return http<CatalogListResponse<Variant>>(`/product-variants?${buildCatalogQuery(query)}`);
  },
  createVariant(req: VariantCreateRequest): Promise<Variant> {
    return http<Variant>(`/product-variants`, { method: "POST", body: JSON.stringify(req) });
  },
  getVariant(id: number): Promise<Variant> {
    return http<Variant>(`/product-variants/${id}`);
  },
  updateVariant(id: number, req: VariantUpdateRequest): Promise<Variant> {
    return http<Variant>(`/product-variants/${id}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    });
  },
  archiveVariant(id: number): Promise<Variant> {
    return http<Variant>(`/product-variants/${id}/archive`, { method: "POST" });
  },
  restoreVariant(id: number): Promise<Variant> {
    return http<Variant>(`/product-variants/${id}/restore`, { method: "POST" });
  },
  mergeVariant(id: number, req: CatalogMergeRequest): Promise<Variant> {
    return http<Variant>(`/product-variants/${id}/merge`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  setVariantStatus(id: number, status: CatalogStatus): Promise<Variant> {
    return http<Variant>(`/product-variants/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
  },

  // ---- SKU ----
  listSkus(query: SkuListQuery = {}): Promise<CatalogListResponse<Sku>> {
    return http<CatalogListResponse<Sku>>(`/product-skus?${buildCatalogQuery(query)}`);
  },
  createSku(req: SkuCreateRequest): Promise<Sku> {
    return http<Sku>(`/product-skus`, { method: "POST", body: JSON.stringify(req) });
  },
  getSku(id: number): Promise<Sku> {
    return http<Sku>(`/product-skus/${id}`);
  },
  updateSku(id: number, req: SkuUpdateRequest): Promise<Sku> {
    return http<Sku>(`/product-skus/${id}`, { method: "PATCH", body: JSON.stringify(req) });
  },
  archiveSku(id: number): Promise<Sku> {
    return http<Sku>(`/product-skus/${id}/archive`, { method: "POST" });
  },
  restoreSku(id: number): Promise<Sku> {
    return http<Sku>(`/product-skus/${id}/restore`, { method: "POST" });
  },
  mergeSku(id: number, req: CatalogMergeRequest): Promise<Sku> {
    return http<Sku>(`/product-skus/${id}/merge`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  setSkuStatus(id: number, status: CatalogStatus): Promise<Sku> {
    return http<Sku>(`/product-skus/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
  },

  // ---- Alias ----
  listCatalogAliases(targetLevel: CatalogLevel, targetId: number): Promise<CatalogAlias[]> {
    const p = new URLSearchParams();
    p.set("target_level", targetLevel);
    p.set("target_id", String(targetId));
    return http<CatalogAlias[]>(`/product-aliases?${p.toString()}`);
  },
  createCatalogAlias(req: CatalogAliasCreateRequest): Promise<CatalogAlias> {
    return http<CatalogAlias>(`/product-aliases`, { method: "POST", body: JSON.stringify(req) });
  },
  updateCatalogAlias(id: number, req: CatalogAliasUpdateRequest): Promise<CatalogAlias> {
    return http<CatalogAlias>(`/product-aliases/${id}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    });
  },
  deleteCatalogAlias(id: number): Promise<void> {
    return http<void>(`/product-aliases/${id}`, { method: "DELETE" });
  },

  // ---- Catalog tree / search / resolve ----
  catalogTree(includeArchived = false): Promise<CatalogTreeNode[]> {
    const p = new URLSearchParams();
    if (includeArchived) p.set("include_archived", "true");
    return http<CatalogTreeNode[]>(`/product-catalog/tree?${p.toString()}`);
  },
  catalogSearch(q: string): Promise<CatalogSearchNode[]> {
    const p = new URLSearchParams();
    p.set("q", q);
    return http<CatalogSearchNode[]>(`/product-catalog/search?${p.toString()}`);
  },
  catalogResolve(value: string): Promise<CatalogResolveResult> {
    const p = new URLSearchParams();
    p.set("value", value);
    return http<CatalogResolveResult>(`/product-catalog/resolve?${p.toString()}`);
  },

  // ===== PR-A2 动态产品属性（定义 + 值）+ 参考图库 + profile =====
  //
  // 属性定义、允许值、单位、参考图角度/状态全部来自后端；上传用 FormData（不手动设
  // Content-Type，让浏览器自动带 multipart boundary）。文件按 id 引用，绝不用路径。

  // ---- 属性定义 ----
  listAttributeDefinitions(
    query: AttributeDefinitionListQuery = {},
  ): Promise<AttributeDefinitionListResponse> {
    return http<AttributeDefinitionListResponse>(
      `/product-attribute-definitions?${buildAttributeDefQuery(query)}`,
    );
  },
  createAttributeDefinition(
    req: AttributeDefinitionCreateRequest,
  ): Promise<AttributeDefinition> {
    return http<AttributeDefinition>(`/product-attribute-definitions`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  getAttributeDefinition(id: number): Promise<AttributeDefinition> {
    return http<AttributeDefinition>(`/product-attribute-definitions/${id}`);
  },
  updateAttributeDefinition(
    id: number,
    req: AttributeDefinitionUpdateRequest,
  ): Promise<AttributeDefinition> {
    return http<AttributeDefinition>(`/product-attribute-definitions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    });
  },
  archiveAttributeDefinition(id: number): Promise<AttributeDefinition> {
    return http<AttributeDefinition>(`/product-attribute-definitions/${id}/archive`, {
      method: "POST",
    });
  },
  restoreAttributeDefinition(id: number): Promise<AttributeDefinition> {
    return http<AttributeDefinition>(`/product-attribute-definitions/${id}/restore`, {
      method: "POST",
    });
  },
  setAttributeDefinitionStatus(
    id: number,
    status: CatalogStatus,
  ): Promise<AttributeDefinition> {
    return http<AttributeDefinition>(`/product-attribute-definitions/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
  },

  // ---- 属性值 ----
  listAttributeValues(query: AttributeValueListQuery): Promise<AttributeValue[]> {
    const p = new URLSearchParams();
    p.set("target_level", query.target_level);
    p.set("target_id", String(query.target_id));
    if (query.include_archived) p.set("include_archived", "true");
    return http<AttributeValue[]>(`/product-attribute-values?${p.toString()}`);
  },
  setAttributeValue(req: AttributeValueUpsertRequest): Promise<AttributeValue> {
    return http<AttributeValue>(`/product-attribute-values`, {
      method: "PUT",
      body: JSON.stringify(req),
    });
  },
  deleteAttributeValue(id: number): Promise<void> {
    return http<void>(`/product-attribute-values/${id}`, { method: "DELETE" });
  },

  // ---- 参考图 ----
  listReferences(query: ReferenceListQuery): Promise<ReferenceAsset[]> {
    const p = new URLSearchParams();
    p.set("target_level", query.target_level);
    p.set("target_id", String(query.target_id));
    if (query.include_archived) p.set("include_archived", "true");
    return http<ReferenceAsset[]>(`/product-reference-assets?${p.toString()}`);
  },
  async uploadReferences(input: {
    targetLevel: AttributeTargetLevel;
    targetId: number;
    files: File[];
    angle?: string;
    state?: string;
    description?: string;
    isPrimary?: boolean;
  }): Promise<ReferenceUploadResponse> {
    const fd = new FormData();
    fd.append("target_level", input.targetLevel);
    fd.append("target_id", String(input.targetId));
    if (input.angle) fd.append("angle", input.angle);
    if (input.state) fd.append("state", input.state);
    if (input.description) fd.append("description", input.description);
    if (input.isPrimary != null) fd.append("is_primary", String(input.isPrimary));
    for (const f of input.files) fd.append("files", f);
    // 不手动设 Content-Type，浏览器自动带 multipart boundary
    const res = await fetch(`${BASE}/product-reference-assets`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body?.detail ?? detail;
      } catch {
        // 忽略非 JSON 错误体
      }
      throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return res.json();
  },
  getReference(id: number): Promise<ReferenceAsset> {
    return http<ReferenceAsset>(`/product-reference-assets/${id}`);
  },
  updateReference(id: number, req: ReferenceUpdateRequest): Promise<ReferenceAsset> {
    return http<ReferenceAsset>(`/product-reference-assets/${id}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    });
  },
  setReferencePrimary(id: number): Promise<ReferenceAsset> {
    return http<ReferenceAsset>(`/product-reference-assets/${id}/primary`, {
      method: "POST",
    });
  },
  archiveReference(id: number): Promise<ReferenceAsset> {
    return http<ReferenceAsset>(`/product-reference-assets/${id}/archive`, {
      method: "POST",
    });
  },
  restoreReference(id: number): Promise<ReferenceAsset> {
    return http<ReferenceAsset>(`/product-reference-assets/${id}/restore`, {
      method: "POST",
    });
  },
  deleteReference(id: number): Promise<void> {
    return http<void>(`/product-reference-assets/${id}`, { method: "DELETE" });
  },
  batchAngleReferences(ids: number[], angle: string): Promise<ReferenceAsset[]> {
    return http<ReferenceAsset[]>(`/product-reference-assets/batch-angle`, {
      method: "POST",
      body: JSON.stringify({ ids, angle }),
    });
  },
  batchArchiveReferences(ids: number[]): Promise<ReferenceAsset[]> {
    return http<ReferenceAsset[]>(`/product-reference-assets/batch-archive`, {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
  },

  // ---- 目录资料完整度 profile ----
  catalogProfile(level: CatalogLevel, id: number): Promise<CatalogProfile> {
    return http<CatalogProfile>(`/product-catalog/${level}/${id}/profile`);
  },

  // ===== PR-A2 Gate B 产品入驻治理 =====
  //
  // readiness / 入驻审核由后端基于真实数据计算与守卫，前端只展示结果；
  // 变更历史 append-only 只读；混淆关系两侧展示信息由后端补充。

  // ---- 完整度策略 ----
  listReadinessPolicies(
    query: ReadinessPolicyListQuery = {},
  ): Promise<{ items: ReadinessPolicy[]; total: number }> {
    const p = new URLSearchParams();
    if (query.category_id != null) p.set("category_id", String(query.category_id));
    if (query.include_archived) p.set("include_archived", "true");
    return http<{ items: ReadinessPolicy[]; total: number }>(
      `/product-readiness-policies?${p.toString()}`,
    );
  },
  createReadinessPolicy(req: ReadinessPolicyCreateRequest): Promise<ReadinessPolicy> {
    return http<ReadinessPolicy>(`/product-readiness-policies`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  activateReadinessPolicy(id: number): Promise<ReadinessPolicy> {
    return http<ReadinessPolicy>(`/product-readiness-policies/${id}/activate`, {
      method: "POST",
    });
  },
  archiveReadinessPolicy(id: number): Promise<ReadinessPolicy> {
    return http<ReadinessPolicy>(`/product-readiness-policies/${id}/archive`, {
      method: "POST",
    });
  },

  // ---- Readiness（GET 读取 / POST 重新评估，同一确定性计算）----
  getReadiness(level: AttributeTargetLevel, id: number): Promise<ReadinessResult> {
    return http<ReadinessResult>(`/product-catalog/${level}/${id}/readiness`);
  },
  evaluateReadiness(level: AttributeTargetLevel, id: number): Promise<ReadinessResult> {
    return http<ReadinessResult>(`/product-catalog/${level}/${id}/evaluate-readiness`, {
      method: "POST",
    });
  },

  // ---- 入驻审核（null = 尚未有记录）----
  getOnboarding(level: AttributeTargetLevel, id: number): Promise<OnboardingReview | null> {
    return http<OnboardingReview | null>(`/product-catalog/${level}/${id}/onboarding`);
  },
  onboardingAction(
    level: AttributeTargetLevel,
    id: number,
    action: OnboardingActionPath,
    req: OnboardingActionRequest = {},
  ): Promise<OnboardingReview> {
    return http<OnboardingReview>(`/product-catalog/${level}/${id}/${action}`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  // ---- 易混淆产品关系 ----
  listConfusions(
    level: AttributeTargetLevel,
    id: number,
    includeArchived = false,
  ): Promise<{ items: ConfusionPair[]; total: number }> {
    const p = new URLSearchParams();
    if (includeArchived) p.set("include_archived", "true");
    return http<{ items: ConfusionPair[]; total: number }>(
      `/product-catalog/${level}/${id}/confusions?${p.toString()}`,
    );
  },
  createConfusionPair(req: ConfusionPairCreateRequest): Promise<ConfusionPair> {
    return http<ConfusionPair>(`/product-confusion-pairs`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  updateConfusionPair(id: number, req: ConfusionPairUpdateRequest): Promise<ConfusionPair> {
    return http<ConfusionPair>(`/product-confusion-pairs/${id}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    });
  },
  archiveConfusionPair(id: number): Promise<ConfusionPair> {
    return http<ConfusionPair>(`/product-confusion-pairs/${id}/archive`, { method: "POST" });
  },
  restoreConfusionPair(id: number): Promise<ConfusionPair> {
    return http<ConfusionPair>(`/product-confusion-pairs/${id}/restore`, { method: "POST" });
  },

  // ---- 变更历史（append-only 只读）----
  listNodeRevisions(
    level: CatalogLevel,
    id: number,
    query: { limit?: number; offset?: number } = {},
  ): Promise<{ items: CatalogRevision[]; total: number }> {
    const p = new URLSearchParams();
    if (query.limit != null) p.set("limit", String(query.limit));
    if (query.offset != null) p.set("offset", String(query.offset));
    return http<{ items: CatalogRevision[]; total: number }>(
      `/product-catalog/${level}/${id}/revisions?${p.toString()}`,
    );
  },

  // ===== PR-B 最终成片 / 使用血缘 =====
  listFinalVideos(query: FinalVideoListQuery): Promise<FinalVideoListResponse> {
    const p = new URLSearchParams();
    p.set("page", String(query.page));
    p.set("page_size", String(query.page_size));
    if (query.status) p.set("status", query.status);
    if (query.project_id != null) p.set("project_id", String(query.project_id));
    if (query.q) p.set("q", query.q);
    if (query.include_archived) p.set("include_archived", "true");
    return http<FinalVideoListResponse>(`/final-videos?${p.toString()}`);
  },
  createFinalVideo(payload: FinalVideoCreateRequest): Promise<FinalVideo> {
    return http<FinalVideo>(`/final-videos`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  getFinalVideo(id: number): Promise<FinalVideo> {
    return http<FinalVideo>(`/final-videos/${id}`);
  },
  updateFinalVideo(id: number, payload: FinalVideoUpdateRequest): Promise<FinalVideo> {
    return http<FinalVideo>(`/final-videos/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  archiveFinalVideo(id: number): Promise<FinalVideo> {
    return http<FinalVideo>(`/final-videos/${id}/archive`, { method: "POST" });
  },
  restoreFinalVideo(id: number): Promise<FinalVideo> {
    return http<FinalVideo>(`/final-videos/${id}/restore`, { method: "POST" });
  },
  getFinalVideoLineage(id: number): Promise<FinalVideoLineage> {
    return http<FinalVideoLineage>(`/final-videos/${id}/lineage`);
  },
  createUsage(finalVideoId: number, payload: UsageCreateRequest): Promise<FinalVideoUsage> {
    return http<FinalVideoUsage>(`/final-videos/${finalVideoId}/usages`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  proposeFromProject(finalVideoId: number): Promise<ProposeFromProjectResult> {
    return http<ProposeFromProjectResult>(
      `/final-videos/${finalVideoId}/propose-from-project`,
      { method: "POST", body: JSON.stringify({}) },
    );
  },
  usageAction(
    usageId: number,
    action: "confirm" | "reject" | "revoke" | "restore-proposal",
    payload: UsageActionRequest = {},
  ): Promise<FinalVideoUsage> {
    return http<FinalVideoUsage>(`/final-video-usages/${usageId}/${action}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  listUsageEvents(usageId: number): Promise<{ items: UsageEvent[] }> {
    return http<{ items: UsageEvent[] }>(`/final-video-usages/${usageId}/events`);
  },
  createOccurrence(
    usageId: number,
    payload: OccurrenceCreateRequest,
  ): Promise<UsageOccurrence> {
    return http<UsageOccurrence>(`/final-video-usages/${usageId}/occurrences`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  updateOccurrence(
    occurrenceId: number,
    payload: Partial<OccurrenceCreateRequest>,
  ): Promise<UsageOccurrence> {
    return http<UsageOccurrence>(`/final-video-usage-occurrences/${occurrenceId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  deleteOccurrence(occurrenceId: number): Promise<void> {
    return http<void>(`/final-video-usage-occurrences/${occurrenceId}`, {
      method: "DELETE",
    });
  },
  getShotUsageSummary(shotId: number): Promise<ShotUsageSummary> {
    return http<ShotUsageSummary>(`/shots/${shotId}/usage-summary`);
  },
  getShotUsageCounts(shotIds: number[]): Promise<{ items: ShotUsageCount[] }> {
    return http<{ items: ShotUsageCount[] }>(
      `/shot-usage-summaries?shot_ids=${shotIds.join(",")}`,
    );
  },
  getAssetUsageSummary(assetId: number): Promise<AssetUsageSummary> {
    return http<AssetUsageSummary>(`/assets/${assetId}/usage-summary`);
  },

  // ===== PR-C 素材身份 / 位置 / 指纹 / 代次 =====
  getAssetIdentity(assetId: number): Promise<AssetIdentity> {
    return http<AssetIdentity>(`/assets/${assetId}/identity`);
  },
  getAssetLocations(assetId: number): Promise<AssetLocationEntry[]> {
    return http<AssetLocationEntry[]>(`/assets/${assetId}/locations`);
  },
  requestFingerprint(assetId: number, kind: "quick" | "full"): Promise<FingerprintJob> {
    return http<FingerprintJob>(`/assets/${assetId}/fingerprint`, {
      method: "POST",
      body: JSON.stringify({ kind }),
    });
  },
  getFingerprintJob(jobId: number): Promise<FingerprintJob> {
    return http<FingerprintJob>(`/assets/fingerprint-jobs/${jobId}`);
  },
  getAnalysisGenerations(assetId: number): Promise<AnalysisGenerations> {
    return http<AnalysisGenerations>(`/assets/${assetId}/analysis-generations`);
  },
  listAssetShotsByGeneration(assetId: number, generation: number): Promise<PageResult<Shot>> {
    return http<PageResult<Shot>>(
      `/assets/${assetId}/shots?page=1&page_size=100&generation=${generation}`,
    );
  },

  // ===== PR-C Gate B 历史使用证据（弱证据；绝不影响 confirmed 统计） =====
  listLegacyRules(includeArchived = false): Promise<LegacyRuleListResponse> {
    return http<LegacyRuleListResponse>(
      `/legacy-usage-rules?include_archived=${includeArchived}`,
    );
  },
  createLegacyRule(payload: LegacyRuleCreateRequest): Promise<LegacyUsageRule> {
    return http<LegacyUsageRule>(`/legacy-usage-rules`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  updateLegacyRule(id: number, payload: LegacyRuleUpdateRequest): Promise<LegacyUsageRule> {
    return http<LegacyUsageRule>(`/legacy-usage-rules/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  legacyRuleAction(
    id: number,
    action: "enable" | "disable" | "archive" | "restore",
  ): Promise<LegacyUsageRule> {
    return http<LegacyUsageRule>(`/legacy-usage-rules/${id}/${action}`, {
      method: "POST",
    });
  },
  previewLegacyImport(payload: LegacyImportRequest): Promise<LegacyPreview> {
    return http<LegacyPreview>(`/legacy-usage-imports/preview`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  createLegacyImport(payload: LegacyImportRequest): Promise<LegacyImportRun> {
    return http<LegacyImportRun>(`/legacy-usage-imports`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  listLegacyImports(page = 1, pageSize = 20): Promise<LegacyImportRunListResponse> {
    return http<LegacyImportRunListResponse>(
      `/legacy-usage-imports?page=${page}&page_size=${pageSize}`,
    );
  },
  getLegacyImport(id: number): Promise<LegacyImportRun> {
    return http<LegacyImportRun>(`/legacy-usage-imports/${id}`);
  },
  cancelLegacyImport(id: number): Promise<LegacyImportRun> {
    return http<LegacyImportRun>(`/legacy-usage-imports/${id}/cancel`, {
      method: "POST",
    });
  },
  listLegacyEvidence(query: {
    page: number;
    page_size: number;
    review_status?: LegacyReviewStatus;
    asset_id?: number;
    rule_id?: number;
  }): Promise<LegacyEvidenceListResponse> {
    const p = new URLSearchParams();
    p.set("page", String(query.page));
    p.set("page_size", String(query.page_size));
    if (query.review_status) p.set("review_status", query.review_status);
    if (query.asset_id != null) p.set("asset_id", String(query.asset_id));
    if (query.rule_id != null) p.set("rule_id", String(query.rule_id));
    return http<LegacyEvidenceListResponse>(`/legacy-usage-evidence?${p.toString()}`);
  },
  legacyEvidenceAction(
    id: number,
    action: "accept" | "reject" | "mark-conflict" | "reset",
    payload: LegacyReviewActionRequest = {},
  ): Promise<LegacyEvidence> {
    return http<LegacyEvidence>(`/legacy-usage-evidence/${id}/${action}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  legacyBulkReview(
    action: "bulk-accept" | "bulk-reject",
    payload: LegacyBulkReviewRequest,
  ): Promise<LegacyBulkReviewResult> {
    return http<LegacyBulkReviewResult>(`/legacy-usage-evidence/${action}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  listLegacyEvidenceEvents(id: number): Promise<{ items: LegacyEvidenceEvent[] }> {
    return http<{ items: LegacyEvidenceEvent[] }>(`/legacy-usage-evidence/${id}/events`);
  },
  getAssetLegacySummary(assetId: number): Promise<AssetLegacySummary> {
    return http<AssetLegacySummary>(`/assets/${assetId}/legacy-usage-summary`);
  },

  // ===== PR-D 统一使用记录中心（只读投影 + typed bulk） =====
  getReviewSummary(): Promise<ReviewSummary> {
    return http<ReviewSummary>(`/usage-review/summary`);
  },
  listReviewItems(query: ReviewListQuery): Promise<ReviewListResponse> {
    const p = new URLSearchParams();
    p.set("page", String(query.page));
    p.set("page_size", String(query.page_size));
    if (query.item_type) p.set("item_type", query.item_type);
    if (query.review_group) p.set("review_group", query.review_group);
    if (query.source_strength) p.set("source_strength", query.source_strength);
    if (query.asset_id != null) p.set("asset_id", String(query.asset_id));
    if (query.final_video_id != null) p.set("final_video_id", String(query.final_video_id));
    if (query.source_directory_id != null)
      p.set("source_directory_id", String(query.source_directory_id));
    if (query.product_family_id != null)
      p.set("product_family_id", String(query.product_family_id));
    if (query.product_variant_id != null)
      p.set("product_variant_id", String(query.product_variant_id));
    if (query.q) p.set("q", query.q);
    if (query.sort) p.set("sort", query.sort);
    return http<ReviewListResponse>(`/usage-review/items?${p.toString()}`);
  },
  getReviewItemDetail(itemType: ReviewItemType, itemId: number): Promise<ReviewItemDetail> {
    return http<ReviewItemDetail>(`/usage-review/items/${itemType}/${itemId}`);
  },
  reviewBulk(payload: ReviewBulkRequest): Promise<ReviewBulkResult> {
    return http<ReviewBulkResult>(`/usage-review/bulk`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  // ===== PR-F 产品视觉识别实验（只读候选；绝不写产品归属）=====
  getVisualStatus(): Promise<VisualStatus> {
    return http<VisualStatus>(`/product-visual-experiments/status`);
  },
  getVisualCoverage(): Promise<VisualCoverage> {
    return http<VisualCoverage>(`/product-visual-experiments/reference-coverage`);
  },
  visualCandidatesForShot(
    shotId: number,
    payload: { top_k?: number; aggregation?: string },
  ): Promise<VisualCandidateResponse> {
    return http<VisualCandidateResponse>(
      `/product-visual-experiments/candidates/shot/${shotId}`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },
  // ===== PM 产品素材工作台 =====
  pmSummary(): Promise<FamilyMediaSummary[]> {
    return http<FamilyMediaSummary[]>(`/product-media/summary`);
  },
  pmFamilyItems(
    familyId: number,
    q: { kind: string; page?: number; include_historical?: boolean },
  ): Promise<ProductMediaPage> {
    const p = new URLSearchParams({ kind: q.kind, page: String(q.page ?? 1) });
    if (q.include_historical) p.set("include_historical", "true");
    return http<ProductMediaPage>(`/product-media/families/${familyId}/items?${p}`);
  },
  pmUnassigned(kind: string, page = 1): Promise<ProductMediaPage> {
    return http<ProductMediaPage>(`/product-media/unassigned?kind=${kind}&page=${page}`);
  },
  pmAssetLinks(assetId: number): Promise<ProductMediaLink[]> {
    return http<ProductMediaLink[]>(`/product-media/assets/${assetId}/links`);
  },
  pmShotLinks(shotId: number): Promise<ShotLinksView> {
    return http<ShotLinksView>(`/product-media/shots/${shotId}/links`);
  },
  pmSuggestions(targetType: string, targetId: number): Promise<ProductSuggestion[]> {
    return http<ProductSuggestion[]>(
      `/product-media/suggestions?target_type=${targetType}&target_id=${targetId}`,
    );
  },
  async searchByImage(file: File, kind: string): Promise<VisualSearchOut> {
    const fd = new FormData();
    fd.append("file", file);
    // 不手动设 Content-Type，浏览器自动带 multipart boundary
    const res = await fetch(`${BASE}/search/by-image?kind=${kind}`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body?.detail ?? detail;
      } catch {
        // 忽略非 JSON 错误体
      }
      throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return (await res.json()) as VisualSearchOut;
  },
  pmDismissVisualCandidate(candidateId: number): Promise<{ id: number; status: string }> {
    return http<{ id: number; status: string }>(
      `/product-media/visual-candidates/${candidateId}/dismiss`,
      { method: "POST" },
    );
  },
  pmCreateLink(body: Record<string, unknown>): Promise<ProductMediaLink> {
    return http<ProductMediaLink>(`/product-media/links`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  pmUpdateLink(linkId: number, body: Record<string, unknown>): Promise<ProductMediaLink> {
    return http<ProductMediaLink>(`/product-media/links/${linkId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },
  pmDeleteLink(linkId: number): Promise<void> {
    return http<void>(`/product-media/links/${linkId}`, { method: "DELETE" });
  },
  pmUnassignedGroups(kind: string, groupBy: string): Promise<UnassignedGroups> {
    return http<UnassignedGroups>(
      `/product-media/unassigned/groups?kind=${kind}&group_by=${groupBy}`,
    );
  },
  pmOperations(page = 1): Promise<{ total: number; items: PmOperation[] }> {
    return http<{ total: number; items: PmOperation[] }>(
      `/product-media/operations?page=${page}&page_size=20`,
    );
  },
  pmUndoOperation(operationId: number): Promise<Record<string, unknown>> {
    return http<Record<string, unknown>>(
      `/product-media/operations/${operationId}/undo`,
      { method: "POST" },
    );
  },
  pmBulkLink(body: Record<string, unknown>): Promise<PMBulkResult> {
    return http<PMBulkResult>(`/product-media/links/bulk`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  async visualCandidatesForImage(file: File): Promise<VisualCandidateResponse> {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${BASE}/product-visual-experiments/candidates/image`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(String((detail as { detail?: string }).detail || res.status));
    }
    return (await res.json()) as VisualCandidateResponse;
  },
};

// 目录列表 query → search params（跳过 undefined/空，产品值不进代码）
function buildCatalogQuery(
  query: CategoryListQuery & { category_id?: number; family_id?: number; variant_id?: number },
): string {
  const p = new URLSearchParams();
  if (query.q) p.set("q", query.q);
  if (query.status_filter) p.set("status_filter", query.status_filter);
  if (query.include_archived) p.set("include_archived", "true");
  if (query.category_id != null) p.set("category_id", String(query.category_id));
  if (query.family_id != null) p.set("family_id", String(query.family_id));
  if (query.variant_id != null) p.set("variant_id", String(query.variant_id));
  if (query.limit != null) p.set("limit", String(query.limit));
  if (query.offset != null) p.set("offset", String(query.offset));
  return p.toString();
}

// 属性定义列表 query → search params（布尔仅在显式提供时进参，避免误覆盖后端默认）
function buildAttributeDefQuery(query: AttributeDefinitionListQuery): string {
  const p = new URLSearchParams();
  if (query.category_id != null) p.set("category_id", String(query.category_id));
  if (query.include_global != null) p.set("include_global", String(query.include_global));
  if (query.status_filter) p.set("status_filter", query.status_filter);
  if (query.searchable != null) p.set("searchable", String(query.searchable));
  if (query.identity_relevant != null)
    p.set("identity_relevant", String(query.identity_relevant));
  if (query.include_archived) p.set("include_archived", "true");
  if (query.q) p.set("q", query.q);
  if (query.limit != null) p.set("limit", String(query.limit));
  if (query.offset != null) p.set("offset", String(query.offset));
  return p.toString();
}
