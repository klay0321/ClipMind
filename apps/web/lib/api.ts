// 同源 API 客户端：浏览器只访问 /api/*，由 web 服务端代理到内部 api。

import type {
  Asset,
  AssetQuery,
  ExportItem,
  PageResult,
  ScanRun,
  ScanStatusResponse,
  Shot,
  ShotAnalysis,
  ShotDetail,
  ShotQuery,
  SourceDirectory,
  SourceDirectoryCreate,
} from "./types";

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
