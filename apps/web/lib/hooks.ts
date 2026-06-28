"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api, type ShotSearchQuery } from "./api";
import type { AIRunStatus, AssetQuery, MediaRunStatus, ShotQuery } from "./types";
import type { ExportStatus, ReviewActionInput, ReviewActionKind, ScanStatus } from "./types";
import type { DescriptionMatchRequest, ShotSearchRequest } from "./types";
import type {
  ScriptCreateRequest,
  ScriptMatchRequest,
  SegmentLockRequest,
  SegmentMatchRequest,
  SegmentSelectRequest,
  SegmentUpdateRequest,
} from "./types";

const ACTIVE_SCAN: ScanStatus[] = ["queued", "scanning"];
const ACTIVE_RUN: MediaRunStatus[] = ["queued", "running"];
const ACTIVE_EXPORT: ExportStatus[] = ["queued", "running"];
const ACTIVE_AI: AIRunStatus[] = ["queued", "running"];

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

export function useUploadMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => api.uploadAsset(file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["assets"] });
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

// ===== PR-03A AI 理解分析 =====

export function useAiAnalysis(assetId: number | null) {
  return useQuery({
    queryKey: ["ai-analysis", assetId],
    queryFn: () => api.aiAnalysis(assetId as number),
    enabled: assetId != null,
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && ACTIVE_AI.includes(status) ? 2500 : false;
    },
  });
}

export function useShotAi(shotId: number | null, poll = false) {
  return useQuery({
    queryKey: ["shot-ai", shotId],
    queryFn: () => api.shotAi(shotId as number),
    enabled: shotId != null,
    // 触发分析后短时轮询，拿到结果即停
    refetchInterval: (q) => (poll && q.state.data?.has_analysis === false ? 2500 : false),
  });
}

export function useAnalyzeAiMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ assetId, retry }: { assetId: number; retry?: boolean }) =>
      retry ? api.retryAssetAi(assetId) : api.analyzeAssetAi(assetId),
    onSuccess: (_data, { assetId }) => {
      qc.invalidateQueries({ queryKey: ["assets"] });
      qc.invalidateQueries({ queryKey: ["ai-analysis", assetId] });
    },
  });
}

export function useAnalyzeShotAiMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (shotId: number) => api.analyzeShotAi(shotId),
    onSuccess: (_data, shotId) => {
      qc.invalidateQueries({ queryKey: ["shot-ai", shotId] });
      qc.invalidateQueries({ queryKey: ["assets"] });
    },
  });
}

// ===== PR-03B 审核 / 产品 / 汇总 / 筛选 =====

export function useEffectiveResult(shotId: number | null) {
  return useQuery({
    queryKey: ["effective-result", shotId],
    queryFn: () => api.effectiveResult(shotId as number),
    enabled: shotId != null,
  });
}

export function useReviewState(shotId: number | null) {
  return useQuery({
    queryKey: ["review-state", shotId],
    queryFn: () => api.reviewState(shotId as number),
    enabled: shotId != null,
  });
}

export function useReviewEvents(shotId: number | null) {
  return useQuery({
    queryKey: ["review-events", shotId],
    queryFn: () => api.reviewEvents(shotId as number),
    enabled: shotId != null,
  });
}

export function useProductCandidates(shotId: number | null) {
  return useQuery({
    queryKey: ["product-candidates", shotId],
    queryFn: () => api.productCandidates(shotId as number),
    enabled: shotId != null,
  });
}

export function useReviewSummary(assetId: number | null) {
  return useQuery({
    queryKey: ["review-summary", assetId],
    queryFn: () => api.reviewSummary(assetId as number),
    enabled: assetId != null,
  });
}

export function useShotSearch(query: ShotSearchQuery, enabled = true) {
  return useQuery({
    queryKey: ["shot-search", query],
    queryFn: () => api.shotSearch(query),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useProducts(q?: string) {
  return useQuery({
    queryKey: ["products", q ?? ""],
    queryFn: () => api.listProducts(q),
  });
}

// ===== PR-04 Gate B 语义搜索 / 画面描述匹配 =====
//
// 注意：与已有 useShotSearch（/shot-search，PR-03B 结构化筛选）不同，这里是 Gate B
// 语义搜索（/search/shots、/match/description）。req=null 时不发起请求（初始空态）。
// queryFn 接 TanStack 的 signal → fetch abort，保证旧请求被新请求取消、无竞态覆盖。

export function useSemanticSearch(req: ShotSearchRequest | null, enabled = true) {
  return useQuery({
    queryKey: ["semantic-search", req],
    queryFn: ({ signal }) => api.searchShots(req as ShotSearchRequest, signal),
    enabled: enabled && req != null,
    placeholderData: keepPreviousData,
  });
}

export function useDescriptionMatch(req: DescriptionMatchRequest | null, enabled = true) {
  return useQuery({
    queryKey: ["description-match", req],
    queryFn: ({ signal }) => api.matchDescription(req as DescriptionMatchRequest, signal),
    enabled: enabled && req != null,
    placeholderData: keepPreviousData,
  });
}

export function useSearchSuggestions(q: string, enabled = true) {
  const term = q.trim();
  return useQuery({
    queryKey: ["search-suggestions", term],
    queryFn: () => api.searchSuggestions(term, 12),
    enabled,
    // 建议变化频繁但服务端开销小：短缓存避免重复请求，组件侧再做 debounce
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useSearchIndexStatus() {
  return useQuery({
    queryKey: ["search-index-status"],
    queryFn: () => api.searchIndexStatus(),
    // 默认不频繁刷新；仅在索引建设/降级时轮询，正常态停止，避免重复请求
    staleTime: 30_000,
    refetchInterval: (q) => {
      const d = q.state.data;
      if (!d) return false;
      const building =
        d.pending_embeddings > 0 ||
        d.failed_embeddings > 0 ||
        d.embedding_version_mismatched > 0 ||
        !d.provider_healthy;
      return building ? 15_000 : false;
    },
  });
}

export function useReviewActionMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      shotId,
      action,
      body,
    }: {
      shotId: number;
      action: ReviewActionKind;
      body: ReviewActionInput;
    }) => api.reviewAction(shotId, action, body),
    onSuccess: (_data, { shotId }) => {
      qc.invalidateQueries({ queryKey: ["effective-result", shotId] });
      qc.invalidateQueries({ queryKey: ["review-state", shotId] });
      qc.invalidateQueries({ queryKey: ["review-events", shotId] });
      qc.invalidateQueries({ queryKey: ["shot-ai", shotId] });
      qc.invalidateQueries({ queryKey: ["shot-search"] });
      qc.invalidateQueries({ queryKey: ["review-summary"] });
    },
  });
}

// ===== PR-05 脚本匹配与剪辑清单 =====
//
// 失效策略：parse/match/select/lock/unlock 后局部失效 script 详情 + match-status +
// edit-list + 受影响段候选，而非整页刷新；轮询有界（export 完成即停）。

export function useScripts(page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["scripts", page, pageSize],
    queryFn: () => api.listScripts(page, pageSize),
    placeholderData: keepPreviousData,
  });
}

export function useScriptProject(scriptId: number | null) {
  return useQuery({
    queryKey: ["script", scriptId],
    queryFn: () => api.getScript(scriptId as number),
    enabled: scriptId != null,
  });
}

export function useSegmentCandidates(
  scriptId: number | null,
  segmentId: number | null,
  generation?: number,
) {
  return useQuery({
    queryKey: ["script-candidates", scriptId, segmentId, generation ?? "current"],
    queryFn: () => api.segmentCandidates(scriptId as number, segmentId as number, generation),
    enabled: scriptId != null && segmentId != null,
    placeholderData: keepPreviousData,
  });
}

export function useScriptMatchStatus(scriptId: number | null) {
  return useQuery({
    queryKey: ["script-match-status", scriptId],
    queryFn: () => api.scriptMatchStatus(scriptId as number),
    enabled: scriptId != null,
  });
}

export function useScriptEditList(scriptId: number | null, enabled = true) {
  return useQuery({
    queryKey: ["script-edit-list", scriptId],
    queryFn: () => api.scriptEditList(scriptId as number),
    enabled: enabled && scriptId != null,
    placeholderData: keepPreviousData,
  });
}

export function useScriptExportStatus(scriptId: number | null, exportId: number | null) {
  return useQuery({
    queryKey: ["script-export", scriptId, exportId],
    queryFn: () => api.scriptExportStatus(scriptId as number, exportId as number),
    enabled: scriptId != null && exportId != null,
    // 导出进行中轮询，完成/失败即停（页面卸载后 TanStack 自动停止）
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && ACTIVE_EXPORT.includes(status) ? 1500 : false;
    },
  });
}

export function useCreateScript() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: ScriptCreateRequest) => api.createScript(req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scripts"] }),
  });
}

export function useRenameScript(scriptId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.renameScript(scriptId, name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["script", scriptId] });
      qc.invalidateQueries({ queryKey: ["scripts"] });
    },
  });
}

// 失效整个脚本的匹配相关查询（parse/全脚本 match 后用）
function invalidateScriptAll(qc: ReturnType<typeof useQueryClient>, scriptId: number) {
  qc.invalidateQueries({ queryKey: ["script", scriptId] });
  qc.invalidateQueries({ queryKey: ["script-match-status", scriptId] });
  qc.invalidateQueries({ queryKey: ["script-edit-list", scriptId] });
  qc.invalidateQueries({ queryKey: ["script-candidates", scriptId] });
}

export function useParseScript(scriptId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ parser, force }: { parser?: string; force?: boolean } = {}) =>
      api.parseScript(scriptId, parser, force),
    onSuccess: () => invalidateScriptAll(qc, scriptId),
  });
}

export function useUpdateSegment(scriptId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ segmentId, req }: { segmentId: number; req: SegmentUpdateRequest }) =>
      api.updateSegment(scriptId, segmentId, req),
    onSuccess: (_data, { segmentId }) => {
      qc.invalidateQueries({ queryKey: ["script", scriptId] });
      qc.invalidateQueries({ queryKey: ["script-candidates", scriptId, segmentId] });
      qc.invalidateQueries({ queryKey: ["script-match-status", scriptId] });
    },
  });
}

export function useReorderSegments(scriptId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (segmentIds: number[]) => api.reorderSegments(scriptId, segmentIds),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["script", scriptId] });
      qc.invalidateQueries({ queryKey: ["script-edit-list", scriptId] });
    },
  });
}

export function useMatchScript(scriptId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: ScriptMatchRequest = {}) => api.matchScript(scriptId, req),
    onSuccess: () => invalidateScriptAll(qc, scriptId),
  });
}

export function useMatchSegment(scriptId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ segmentId, req }: { segmentId: number; req?: SegmentMatchRequest }) =>
      api.matchSegment(scriptId, segmentId, req ?? {}),
    onSuccess: (_data, { segmentId }) => {
      qc.invalidateQueries({ queryKey: ["script", scriptId] });
      qc.invalidateQueries({ queryKey: ["script-candidates", scriptId, segmentId] });
      qc.invalidateQueries({ queryKey: ["script-match-status", scriptId] });
      qc.invalidateQueries({ queryKey: ["script-edit-list", scriptId] });
    },
  });
}

// 选择后局部刷新该段候选 + 详情 + 状态 + 清单（不整页刷新）
function invalidateSegmentPick(
  qc: ReturnType<typeof useQueryClient>,
  scriptId: number,
  segmentId: number,
) {
  qc.invalidateQueries({ queryKey: ["script", scriptId] });
  qc.invalidateQueries({ queryKey: ["script-candidates", scriptId, segmentId] });
  qc.invalidateQueries({ queryKey: ["script-match-status", scriptId] });
  qc.invalidateQueries({ queryKey: ["script-edit-list", scriptId] });
}

export function useSelectCandidate(scriptId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ segmentId, req }: { segmentId: number; req: SegmentSelectRequest }) =>
      api.selectCandidate(scriptId, segmentId, req),
    onSuccess: (_data, { segmentId }) => invalidateSegmentPick(qc, scriptId, segmentId),
  });
}

export function useLockCandidate(scriptId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ segmentId, req }: { segmentId: number; req: SegmentLockRequest }) =>
      api.lockCandidate(scriptId, segmentId, req),
    onSuccess: (_data, { segmentId }) => invalidateSegmentPick(qc, scriptId, segmentId),
  });
}

export function useUnlockSegment(scriptId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ segmentId, lockVersion }: { segmentId: number; lockVersion: number }) =>
      api.unlockSegment(scriptId, segmentId, lockVersion),
    onSuccess: (_data, { segmentId }) => invalidateSegmentPick(qc, scriptId, segmentId),
  });
}

export function useCreateScriptCsvExport(scriptId: number) {
  return useMutation({
    mutationFn: () => api.createScriptCsvExport(scriptId),
  });
}
