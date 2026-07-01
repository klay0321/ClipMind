// 同源 API 客户端：浏览器只访问 /api/*，由 web 服务端代理到内部 api。

import type {
  AIAnalysis,
  Asset,
  AssetQuery,
  AssetReviewSummary,
  DescriptionMatchRequest,
  DescriptionMatchResponse,
  EffectiveResult,
  ExportItem,
  PageResult,
  Product,
  ProductCandidate,
  ProductStatsListResponse,
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
  catalogResolve(value: string): Promise<CatalogSearchNode | null> {
    const p = new URLSearchParams();
    p.set("value", value);
    return http<CatalogSearchNode | null>(`/product-catalog/resolve?${p.toString()}`);
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
