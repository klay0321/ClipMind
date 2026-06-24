// 同源 API 客户端：浏览器只访问 /api/*，由 web 服务端代理到内部 api。

import type {
  Asset,
  AssetQuery,
  PageResult,
  ScanRun,
  ScanStatusResponse,
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
};
