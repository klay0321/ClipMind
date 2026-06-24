"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api } from "./api";
import type { AssetQuery, MediaRunStatus, ShotQuery } from "./types";
import type { ExportStatus, ScanStatus } from "./types";

const ACTIVE_SCAN: ScanStatus[] = ["queued", "scanning"];
const ACTIVE_RUN: MediaRunStatus[] = ["queued", "running"];
const ACTIVE_EXPORT: ExportStatus[] = ["queued", "running"];

export function useAssets(query: AssetQuery) {
  return useQuery({
    queryKey: ["assets", query],
    queryFn: () => api.listAssets(query),
    placeholderData: keepPreviousData,
    // 有素材正在分析时轮询，结束后停止
    refetchInterval: (q) => {
      const items = q.state.data?.items ?? [];
      const active = items.some(
        (a) =>
          a.status === "processing" ||
          (a.analysis_status != null && ACTIVE_RUN.includes(a.analysis_status)),
      );
      return active ? 2500 : false;
    },
  });
}

export function useSourceDirectories() {
  return useQuery({
    queryKey: ["source-directories"],
    queryFn: () => api.listSourceDirectories(),
  });
}

export function useScanStatus(sourceDirectoryId: number | null) {
  return useQuery({
    queryKey: ["scan-status", sourceDirectoryId],
    queryFn: () => api.scanStatus(sourceDirectoryId as number),
    enabled: sourceDirectoryId != null,
    // 扫描进行中时轮询，完成/失败后停止
    refetchInterval: (query) => {
      const status = query.state.data?.scan_status;
      return status && ACTIVE_SCAN.includes(status) ? 2000 : false;
    },
  });
}

export function useScanMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceDirectoryId: number) => api.scan(sourceDirectoryId),
    onSuccess: (_data, sourceDirectoryId) => {
      qc.invalidateQueries({ queryKey: ["scan-status", sourceDirectoryId] });
      qc.invalidateQueries({ queryKey: ["source-directories"] });
      qc.invalidateQueries({ queryKey: ["assets"] });
    },
  });
}

export function useRescanMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (assetId: number) => api.rescanAsset(assetId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["assets"] });
    },
  });
}

export function useCreateSourceDirectory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createSourceDirectory,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["source-directories"] });
    },
  });
}

// ===== PR-02 镜头分析 / 镜头 / 导出 =====

export function useShotAnalysis(assetId: number | null) {
  return useQuery({
    queryKey: ["shot-analysis", assetId],
    queryFn: () => api.shotAnalysis(assetId as number),
    enabled: assetId != null,
    // 分析进行中时轮询，完成/失败后停止
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && ACTIVE_RUN.includes(status) ? 2000 : false;
    },
  });
}

export function useAssetShots(assetId: number | null, page: number, pageSize: number) {
  return useQuery({
    queryKey: ["asset-shots", assetId, page, pageSize],
    queryFn: () => api.assetShots({ asset_id: assetId as number, page, page_size: pageSize }),
    enabled: assetId != null,
    placeholderData: keepPreviousData,
  });
}

export function useShots(query: ShotQuery, enabled = true) {
  return useQuery({
    queryKey: ["shots", query],
    queryFn: () => api.listShots(query),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useShot(shotId: number | null) {
  return useQuery({
    queryKey: ["shot", shotId],
    queryFn: () => api.getShot(shotId as number),
    enabled: shotId != null,
  });
}

export function useAnalyzeMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ assetId, retry }: { assetId: number; retry?: boolean }) =>
      retry ? api.retryShotAnalysis(assetId) : api.analyzeShots(assetId),
    onSuccess: (_data, { assetId }) => {
      qc.invalidateQueries({ queryKey: ["assets"] });
      qc.invalidateQueries({ queryKey: ["shot-analysis", assetId] });
    },
  });
}

export function useExportMutation() {
  return useMutation({
    mutationFn: ({ shotId, mode }: { shotId: number; mode?: string }) =>
      api.exportShot(shotId, mode),
  });
}

export function useExportStatus(exportId: number | null) {
  return useQuery({
    queryKey: ["export", exportId],
    queryFn: () => api.getExport(exportId as number),
    enabled: exportId != null,
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && ACTIVE_EXPORT.includes(status) ? 1500 : false;
    },
  });
}
