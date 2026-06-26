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
  RebuildAcceptedResponse,
  ReviewActionInput,
  ReviewActionKind,
  ReviewEvent,
  ReviewState,
  ScanRun,
  ScanStatusResponse,
  SearchIndexStatus,
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
};
