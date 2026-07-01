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
import type {
  CollectionCreateRequest,
  CollectionUpdateRequest,
  ProjectCreateRequest,
  ProjectShotsQuery,
  ProjectStatus,
  ProjectUpdateRequest,
} from "./types";
import type {
  BundleCreateRequest,
  DescriptionMatchResponse,
  DynamicCollectionCreateRequest,
  DynamicCollectionUpdateRequest,
  ExportCenterQuery,
  ExportKind,
  FavoriteCreateRequest,
  FavoriteTargetType,
  SavedSearchCreateRequest,
  SavedSearchKind,
  SavedSearchUpdateRequest,
  ScriptExportFormat,
  ShotSearchResponse,
} from "./types";
import type {
  CatalogAliasCreateRequest,
  CatalogAliasUpdateRequest,
  CatalogLevel,
  CatalogMergeRequest,
  CatalogNode,
  CatalogStatus,
  CategoryCreateRequest,
  CategoryListQuery,
  CategoryUpdateRequest,
  FamilyCreateRequest,
  FamilyListQuery,
  FamilyUpdateRequest,
  SkuCreateRequest,
  SkuListQuery,
  SkuUpdateRequest,
  VariantCreateRequest,
  VariantListQuery,
  VariantUpdateRequest,
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

// 每产品绑定计数（绑定素材/镜头/已确认），由 ProductsView 合并到行。
export function useProductStats() {
  return useQuery({
    queryKey: ["product-stats"],
    queryFn: () => api.productStats(),
    staleTime: 30_000,
    select: (data) => {
      const map: Record<number, { asset_count: number; shot_count: number; confirmed_shot_count: number }> = {};
      for (const s of data.items) {
        map[s.product_id] = {
          asset_count: s.asset_count,
          shot_count: s.shot_count,
          confirmed_shot_count: s.confirmed_shot_count,
        };
      }
      return map;
    },
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

export function useShotCompleteness() {
  return useQuery({
    queryKey: ["shot-completeness"],
    queryFn: () => api.shotCompleteness(),
    staleTime: 15_000,
  });
}

// 镜头筛选下拉选项：来自真实 /search/suggestions（产品/场景/动作/镜头类型/营销），按 type 分组。
export function useShotFilterOptions() {
  return useQuery({
    queryKey: ["shot-filter-options"],
    queryFn: () => api.searchSuggestions("", 60),
    staleTime: 60_000,
    select: (data): Record<string, string[]> => {
      const groups: Record<string, string[]> = {};
      for (const it of data.items) {
        const arr = (groups[it.type] ??= []);
        if (!arr.includes(it.value)) arr.push(it.value);
      }
      return groups;
    },
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

// ===== PR-06A 项目 / 静态镜头集合 =====
//
// 失效策略：列表/成员/统计精确失效，不整页刷新；reorder 返回新 lock_version → 失效 ["project",id]
// 让详情头部拿到新版本；归档/恢复后失效列表+详情+统计。成员变更同时失效统计（计数变化）。

function invalidateProjectAll(qc: ReturnType<typeof useQueryClient>, id: number) {
  qc.invalidateQueries({ queryKey: ["project", id] });
  qc.invalidateQueries({ queryKey: ["project-stats", id] });
  qc.invalidateQueries({ queryKey: ["projects"] });
}

export function useProjects(page = 1, pageSize = 20, status?: ProjectStatus) {
  return useQuery({
    queryKey: ["projects", page, pageSize, status ?? "all"],
    queryFn: () => api.listProjects(page, pageSize, status),
    placeholderData: keepPreviousData,
  });
}

export function useProject(id: number | null) {
  return useQuery({
    queryKey: ["project", id],
    queryFn: () => api.getProject(id as number),
    enabled: id != null,
  });
}

// 统计只在详情页加载（不在列表逐项目请求，避免 N+1）
export function useProjectStats(id: number | null, enabled = true) {
  return useQuery({
    queryKey: ["project-stats", id],
    queryFn: () => api.getProjectStats(id as number),
    enabled: enabled && id != null,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: ProjectCreateRequest) => api.createProject(req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useUpdateProject(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: ProjectUpdateRequest) => api.updateProject(id, req),
    onSuccess: () => invalidateProjectAll(qc, id),
  });
}

export function useArchiveProject(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (lockVersion: number) => api.archiveProject(id, lockVersion),
    onSuccess: () => invalidateProjectAll(qc, id),
  });
}

export function useUnarchiveProject(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (lockVersion: number) => api.unarchiveProject(id, lockVersion),
    onSuccess: () => invalidateProjectAll(qc, id),
  });
}

export function useProjectAssets(id: number | null, page: number, pageSize: number) {
  return useQuery({
    queryKey: ["project-assets", id, page, pageSize],
    queryFn: () => api.projectAssets(id as number, page, pageSize),
    enabled: id != null,
    placeholderData: keepPreviousData,
  });
}

export function useAddProjectAssets(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[]) => api.addProjectAssets(id, ids),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-assets", id] });
      qc.invalidateQueries({ queryKey: ["project-shots", id] });
      qc.invalidateQueries({ queryKey: ["project-stats", id] });
    },
  });
}

export function useRemoveProjectAsset(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (assetId: number) => api.removeProjectAsset(id, assetId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-assets", id] });
      qc.invalidateQueries({ queryKey: ["project-shots", id] });
      qc.invalidateQueries({ queryKey: ["project-stats", id] });
    },
  });
}

export function useReorderProjectAssets(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, lockVersion }: { ids: number[]; lockVersion: number }) =>
      api.reorderProjectAssets(id, ids, lockVersion),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-assets", id] });
      qc.invalidateQueries({ queryKey: ["project", id] });
    },
  });
}

export function useProjectShots(id: number | null, query: ProjectShotsQuery) {
  return useQuery({
    queryKey: ["project-shots", id, query],
    queryFn: () => api.projectShots(id as number, query),
    enabled: id != null,
    placeholderData: keepPreviousData,
  });
}

export function useAddProjectShots(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[]) => api.addProjectShots(id, ids),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-shots", id] });
      qc.invalidateQueries({ queryKey: ["project-stats", id] });
    },
  });
}

export function useRemoveProjectShot(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (shotId: number) => api.removeProjectShot(id, shotId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-shots", id] });
      qc.invalidateQueries({ queryKey: ["project-stats", id] });
    },
  });
}

export function useReorderProjectShots(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, lockVersion }: { ids: number[]; lockVersion: number }) =>
      api.reorderProjectShots(id, ids, lockVersion),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-shots", id] });
      qc.invalidateQueries({ queryKey: ["project", id] });
    },
  });
}

export function useProjectProducts(id: number | null, page: number, pageSize: number) {
  return useQuery({
    queryKey: ["project-products", id, page, pageSize],
    queryFn: () => api.projectProducts(id as number, page, pageSize),
    enabled: id != null,
    placeholderData: keepPreviousData,
  });
}

export function useAddProjectProducts(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[]) => api.addProjectProducts(id, ids),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-products", id] });
      qc.invalidateQueries({ queryKey: ["project-stats", id] });
    },
  });
}

export function useRemoveProjectProduct(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (productId: number) => api.removeProjectProduct(id, productId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-products", id] });
      qc.invalidateQueries({ queryKey: ["project-stats", id] });
    },
  });
}

export function useProjectScripts(id: number | null, page: number, pageSize: number) {
  return useQuery({
    queryKey: ["project-scripts", id, page, pageSize],
    queryFn: () => api.projectScripts(id as number, page, pageSize),
    enabled: id != null,
    placeholderData: keepPreviousData,
  });
}

export function useAttachProjectScript(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scriptId: number) => api.attachProjectScript(id, scriptId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-scripts", id] });
      qc.invalidateQueries({ queryKey: ["project-stats", id] });
      qc.invalidateQueries({ queryKey: ["scripts"] });
    },
  });
}

export function useDetachProjectScript(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scriptId: number) => api.detachProjectScript(id, scriptId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-scripts", id] });
      qc.invalidateQueries({ queryKey: ["project-stats", id] });
      qc.invalidateQueries({ queryKey: ["scripts"] });
    },
  });
}

export function useProjectCollections(projectId: number | null, page: number, pageSize: number) {
  return useQuery({
    queryKey: ["project-collections", projectId, page, pageSize],
    queryFn: () => api.listProjectCollections(projectId as number, page, pageSize),
    enabled: projectId != null,
    placeholderData: keepPreviousData,
  });
}

export function useCollection(id: number | null) {
  return useQuery({
    queryKey: ["collection", id],
    queryFn: () => api.getCollection(id as number),
    enabled: id != null,
  });
}

export function useCreateCollection(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: CollectionCreateRequest) => api.createCollection(projectId, req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-collections", projectId] });
      qc.invalidateQueries({ queryKey: ["project-stats", projectId] });
    },
  });
}

export function useUpdateCollection(id: number, projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: CollectionUpdateRequest) => api.updateCollection(id, req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["collection", id] });
      qc.invalidateQueries({ queryKey: ["project-collections", projectId] });
    },
  });
}

export function useDeleteCollection(id: number, projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.deleteCollection(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-collections", projectId] });
      qc.invalidateQueries({ queryKey: ["project-stats", projectId] });
      qc.invalidateQueries({ queryKey: ["project-shots", projectId] });
    },
  });
}

export function useCollectionShots(id: number | null, page: number, pageSize: number) {
  return useQuery({
    queryKey: ["collection-shots", id, page, pageSize],
    queryFn: () => api.collectionShots(id as number, page, pageSize),
    enabled: id != null,
    placeholderData: keepPreviousData,
  });
}

export function useAddCollectionShots(id: number, projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[]) => api.addCollectionShots(id, ids),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["collection-shots", id] });
      qc.invalidateQueries({ queryKey: ["collection", id] });
      qc.invalidateQueries({ queryKey: ["project-collections", projectId] });
      qc.invalidateQueries({ queryKey: ["project-stats", projectId] });
      qc.invalidateQueries({ queryKey: ["project-shots", projectId] });
    },
  });
}

export function useRemoveCollectionShot(id: number, projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (shotId: number) => api.removeCollectionShot(id, shotId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["collection-shots", id] });
      qc.invalidateQueries({ queryKey: ["collection", id] });
      qc.invalidateQueries({ queryKey: ["project-collections", projectId] });
      qc.invalidateQueries({ queryKey: ["project-stats", projectId] });
      qc.invalidateQueries({ queryKey: ["project-shots", projectId] });
    },
  });
}

export function useReorderCollectionShots(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, lockVersion }: { ids: number[]; lockVersion: number }) =>
      api.reorderCollectionShots(id, ids, lockVersion),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["collection-shots", id] });
      qc.invalidateQueries({ queryKey: ["collection", id] });
    },
  });
}

// ===== PR-06B 导出中心 / 多格式脚本导出 / ZIP 打包 / 保存搜索 / 收藏 / 动态集合 =====
//
// 失效策略：导出记录列表/单条精确失效；重试/删除后失效列表；保存搜索/收藏/动态集合各自
// 列表 + 单条失效；轮询有界（导出完成/失败即停）。所有匹配度/分项分仍只读后端。

// ---- 导出中心 ----

export function useExportCenter(query: ExportCenterQuery) {
  return useQuery({
    queryKey: ["export-center", query],
    queryFn: () => api.exportCenter(query),
    placeholderData: keepPreviousData,
    // 有任意行排队/运行时轮询，全部结束后停止
    refetchInterval: (q) => {
      const items = q.state.data?.items ?? [];
      const active = items.some((it) => ACTIVE_EXPORT.includes(it.status));
      return active ? 2000 : false;
    },
  });
}

export function useRetryExport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, id }: { kind: ExportKind; id: number }) => api.retryExportCenter(kind, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["export-center"] }),
  });
}

export function useDeleteExport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, id }: { kind: ExportKind; id: number }) =>
      api.deleteExportCenter(kind, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["export-center"] }),
  });
}

// ---- ZIP 打包导出 ----

export function useCreateBundle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: BundleCreateRequest) => api.createBundle(req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["export-center"] }),
  });
}

export function useBundleStatus(bundleId: number | null) {
  return useQuery({
    queryKey: ["bundle", bundleId],
    queryFn: () => api.getBundle(bundleId as number),
    enabled: bundleId != null,
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && ACTIVE_EXPORT.includes(status) ? 1500 : false;
    },
  });
}

// ---- 多格式脚本导出（创建；状态复用 useScriptExportStatus）----

export function useCreateScriptExport(scriptId: number) {
  return useMutation({
    mutationFn: (format: ScriptExportFormat) => api.createScriptExport(scriptId, format),
  });
}

// ---- 保存搜索 ----

export function useSavedSearches(
  projectId?: number,
  searchKind?: SavedSearchKind,
  page = 1,
  pageSize = 20,
) {
  return useQuery({
    queryKey: ["saved-searches", projectId ?? null, searchKind ?? "all", page, pageSize],
    queryFn: () => api.listSavedSearches(projectId, searchKind, page, pageSize),
    placeholderData: keepPreviousData,
  });
}

export function useSavedSearch(id: number | null) {
  return useQuery({
    queryKey: ["saved-search", id],
    queryFn: () => api.getSavedSearch(id as number),
    enabled: id != null,
  });
}

export function useCreateSavedSearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: SavedSearchCreateRequest) => api.createSavedSearch(req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-searches"] }),
  });
}

export function useUpdateSavedSearch(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: SavedSearchUpdateRequest) => api.updateSavedSearch(id, req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["saved-searches"] });
      qc.invalidateQueries({ queryKey: ["saved-search", id] });
    },
  });
}

export function useDeleteSavedSearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteSavedSearch(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-searches"] }),
  });
}

// run 返回 ShotSearchResponse 或 DescriptionMatchResponse（按 search_kind）。
export function useRunSavedSearch() {
  return useMutation({
    mutationFn: ({ id, page, pageSize }: { id: number; page?: number; pageSize?: number }) =>
      api.runSavedSearch<ShotSearchResponse | DescriptionMatchResponse>(id, page, pageSize),
  });
}

// ---- 收藏 ----

export function useFavorites(targetType?: FavoriteTargetType, page = 1, pageSize = 24) {
  return useQuery({
    queryKey: ["favorites", targetType ?? "all", page, pageSize],
    queryFn: () => api.listFavorites(targetType, page, pageSize),
    placeholderData: keepPreviousData,
  });
}

export function useCreateFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: FavoriteCreateRequest) => api.createFavorite(req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["favorites"] }),
  });
}

export function useDeleteFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteFavorite(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["favorites"] }),
  });
}

// ---- 动态集合 ----

export function useDynamicCollections(projectId: number | null, page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["dynamic-collections", projectId, page, pageSize],
    queryFn: () => api.listDynamicCollections(projectId as number, page, pageSize),
    enabled: projectId != null,
    placeholderData: keepPreviousData,
  });
}

export function useDynamicCollection(id: number | null) {
  return useQuery({
    queryKey: ["dynamic-collection", id],
    queryFn: () => api.getDynamicCollection(id as number),
    enabled: id != null,
  });
}

export function useCreateDynamicCollection(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: DynamicCollectionCreateRequest) =>
      api.createDynamicCollection(projectId, req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dynamic-collections", projectId] });
      qc.invalidateQueries({ queryKey: ["project-stats", projectId] });
    },
  });
}

export function useUpdateDynamicCollection(id: number, projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: DynamicCollectionUpdateRequest) => api.updateDynamicCollection(id, req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dynamic-collection", id] });
      qc.invalidateQueries({ queryKey: ["dynamic-collections", projectId] });
    },
  });
}

export function useDeleteDynamicCollection(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteDynamicCollection(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dynamic-collections", projectId] });
      qc.invalidateQueries({ queryKey: ["project-stats", projectId] });
    },
  });
}

export function useDynamicCollectionShots(id: number | null, page = 1, pageSize = 24) {
  return useQuery({
    queryKey: ["dynamic-collection-shots", id, page, pageSize],
    queryFn: () =>
      api.dynamicCollectionShots<ShotSearchResponse | DescriptionMatchResponse>(
        id as number,
        page,
        pageSize,
      ),
    enabled: id != null,
    placeholderData: keepPreviousData,
  });
}

// ===== PR-A1 通用产品目录（Category / Family / Variant / SKU / Alias + tree/search）=====
//
// 失效策略：任一实体的创建/更名/状态/归档/恢复/合并/别名变更后，统一失效 catalog 相关查询
// （tree + 各层列表 + 该实体别名）。这样左侧树与右侧详情/子级列表都能拿到最新数据，
// 不整页刷新、不在前端重算任何产品信息。

// 广谱失效：任一目录写操作后刷新树 + 全部层列表 + 搜索/解析。
function invalidateCatalog(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["catalog-tree"] });
  qc.invalidateQueries({ queryKey: ["catalog-categories"] });
  qc.invalidateQueries({ queryKey: ["catalog-families"] });
  qc.invalidateQueries({ queryKey: ["catalog-variants"] });
  qc.invalidateQueries({ queryKey: ["catalog-skus"] });
  qc.invalidateQueries({ queryKey: ["catalog-search"] });
  qc.invalidateQueries({ queryKey: ["catalog-node"] });
}

// ---- 树 / 搜索 ----

export function useCatalogTree(includeArchived = false) {
  return useQuery({
    queryKey: ["catalog-tree", includeArchived],
    queryFn: () => api.catalogTree(includeArchived),
  });
}

export function useCatalogSearch(q: string, enabled = true) {
  const term = q.trim();
  return useQuery({
    queryKey: ["catalog-search", term],
    queryFn: () => api.catalogSearch(term),
    enabled: enabled && term.length > 0,
    placeholderData: keepPreviousData,
  });
}

// ---- 列表（各层）----

export function useCategories(query: CategoryListQuery = {}) {
  return useQuery({
    queryKey: ["catalog-categories", query],
    queryFn: () => api.listCategories(query),
    placeholderData: keepPreviousData,
  });
}

export function useFamilies(query: FamilyListQuery = {}, enabled = true) {
  return useQuery({
    queryKey: ["catalog-families", query],
    queryFn: () => api.listFamilies(query),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useVariants(query: VariantListQuery = {}, enabled = true) {
  return useQuery({
    queryKey: ["catalog-variants", query],
    queryFn: () => api.listVariants(query),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useSkus(query: SkuListQuery = {}, enabled = true) {
  return useQuery({
    queryKey: ["catalog-skus", query],
    queryFn: () => api.listSkus(query),
    enabled,
    placeholderData: keepPreviousData,
  });
}

// ---- 单实体详情（按 level 分派）----

export function useCatalogNode(level: CatalogLevel | null, id: number | null) {
  return useQuery<CatalogNode>({
    queryKey: ["catalog-node", level, id],
    queryFn: (): Promise<CatalogNode> => {
      switch (level) {
        case "category":
          return api.getCategory(id as number);
        case "family":
          return api.getFamily(id as number);
        case "variant":
          return api.getVariant(id as number);
        case "sku":
          return api.getSku(id as number);
        default:
          return Promise.reject(new Error("未知层级"));
      }
    },
    enabled: level != null && id != null,
  });
}

// ---- 别名（按目标实体）----

export function useCatalogAliases(level: CatalogLevel | null, targetId: number | null) {
  return useQuery({
    queryKey: ["catalog-aliases", level, targetId],
    queryFn: () => api.listCatalogAliases(level as CatalogLevel, targetId as number),
    enabled: level != null && targetId != null,
  });
}

// ---- 创建 ----

export function useCreateCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: CategoryCreateRequest) => api.createCategory(req),
    onSuccess: () => invalidateCatalog(qc),
  });
}

export function useCreateFamily() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: FamilyCreateRequest) => api.createFamily(req),
    onSuccess: () => invalidateCatalog(qc),
  });
}

export function useCreateVariant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: VariantCreateRequest) => api.createVariant(req),
    onSuccess: () => invalidateCatalog(qc),
  });
}

export function useCreateSku() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: SkuCreateRequest) => api.createSku(req),
    onSuccess: () => invalidateCatalog(qc),
  });
}

// ---- 更新 / 更名 ----

export function useUpdateCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, req }: { id: number; req: CategoryUpdateRequest }) =>
      api.updateCategory(id, req),
    onSuccess: () => invalidateCatalog(qc),
  });
}

export function useUpdateFamily() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, req }: { id: number; req: FamilyUpdateRequest }) =>
      api.updateFamily(id, req),
    onSuccess: () => invalidateCatalog(qc),
  });
}

export function useUpdateVariant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, req }: { id: number; req: VariantUpdateRequest }) =>
      api.updateVariant(id, req),
    onSuccess: () => invalidateCatalog(qc),
  });
}

export function useUpdateSku() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, req }: { id: number; req: SkuUpdateRequest }) => api.updateSku(id, req),
    onSuccess: () => invalidateCatalog(qc),
  });
}

// ---- 生命周期：状态 / 归档 / 恢复 / 合并 ----
//
// 各层参数化：以 level 分派到对应 api 方法，避免为每层重复 8 个 hook。

type LevelMut = { level: CatalogLevel; id: number };

export function useSetFamilyStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: number; status: CatalogStatus }) =>
      api.setFamilyStatus(id, status),
    onSuccess: () => invalidateCatalog(qc),
  });
}

export function useArchiveCatalogNode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ level, id }: LevelMut): Promise<CatalogNode> => {
      switch (level) {
        case "category":
          return api.archiveCategory(id);
        case "family":
          return api.archiveFamily(id);
        case "variant":
          return api.archiveVariant(id);
        case "sku":
          return api.archiveSku(id);
        default:
          return Promise.reject(new Error("未知层级"));
      }
    },
    onSuccess: () => invalidateCatalog(qc),
  });
}

export function useRestoreCatalogNode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ level, id }: LevelMut): Promise<CatalogNode> => {
      switch (level) {
        case "category":
          return api.restoreCategory(id);
        case "family":
          return api.restoreFamily(id);
        case "variant":
          return api.restoreVariant(id);
        case "sku":
          return api.restoreSku(id);
        default:
          return Promise.reject(new Error("未知层级"));
      }
    },
    onSuccess: () => invalidateCatalog(qc),
  });
}

// 合并仅 family / variant / sku 支持（category 无 merge）
export function useMergeCatalogNode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ level, id, req }: LevelMut & { req: CatalogMergeRequest }): Promise<CatalogNode> => {
      switch (level) {
        case "family":
          return api.mergeFamily(id, req);
        case "variant":
          return api.mergeVariant(id, req);
        case "sku":
          return api.mergeSku(id, req);
        default:
          return Promise.reject(new Error("该层级不支持合并"));
      }
    },
    onSuccess: () => invalidateCatalog(qc),
  });
}

// ---- 别名写操作 ----

export function useCreateCatalogAlias() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: CatalogAliasCreateRequest) => api.createCatalogAlias(req),
    onSuccess: (_data, req) => {
      qc.invalidateQueries({ queryKey: ["catalog-aliases", req.target_level, req.target_id] });
    },
  });
}

export function useUpdateCatalogAlias(level: CatalogLevel, targetId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, req }: { id: number; req: CatalogAliasUpdateRequest }) =>
      api.updateCatalogAlias(id, req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["catalog-aliases", level, targetId] });
    },
  });
}

export function useDeleteCatalogAlias(level: CatalogLevel, targetId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteCatalogAlias(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["catalog-aliases", level, targetId] });
    },
  });
}
