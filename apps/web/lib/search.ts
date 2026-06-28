// PR-04 Gate C：语义搜索 / 画面描述匹配的纯逻辑（标签、格式化、请求组装、索引健康、URL 状态）。
// 无副作用、无 React，便于单测。所有匹配度/分项分只读后端值，绝不在前端重算 final_score。

import { ASPECT_RATIO_VALUES } from "./types";
import type {
  AspectRatioValue,
  DescriptionMatchRequest,
  RecommendationLevel,
  ReviewStatus,
  SearchIndexStatus,
  SearchMode,
  SearchSort,
  ShotSearchRequest,
  SuggestionType,
} from "./types";

// ---------------- 标签 ----------------

export const SEARCH_MODE_LABELS: Record<SearchMode, string> = {
  hybrid: "智能混合",
  semantic: "语义",
  lexical: "关键词",
  structured: "结构化",
};

export const SEARCH_MODE_HINTS: Record<SearchMode, string> = {
  hybrid: "向量 + 关键词 + 标签 + 产品综合召回（推荐）",
  semantic: "仅向量语义相似（不可用时自动降级为关键词）",
  lexical: "仅关键词 / 模糊匹配，不使用向量",
  structured: "仅结构化标签 / 产品 / 过滤，不按相似度排序",
};

export const SORT_LABELS: Record<SearchSort, string> = {
  relevance: "综合匹配度",
  latest: "最新创建",
  duration: "时长（短→长）",
  quality: "质量优先",
};

export const REVIEW_STATUS_LABELS: Record<string, string> = {
  unreviewed: "未审核",
  pending_review: "待审核",
  confirmed: "已确认",
  modified: "已修改",
  rejected: "已驳回",
  unable: "无法判断",
};

export const REVIEW_STATUS_TONE: Record<string, string> = {
  unreviewed: "bg-gray-100 text-gray-600",
  pending_review: "bg-amber-50 text-amber-700",
  confirmed: "bg-emerald-50 text-emerald-700",
  modified: "bg-emerald-50 text-emerald-700",
  rejected: "bg-red-50 text-red-700",
  unable: "bg-gray-100 text-gray-500",
};

export const RECOMMENDATION_LABELS: Record<RecommendationLevel, string> = {
  high: "强烈推荐",
  medium: "可用",
  low: "勉强相关",
  not_recommended: "不推荐",
};

export const RECOMMENDATION_TONE: Record<RecommendationLevel, string> = {
  high: "bg-emerald-100 text-emerald-700",
  medium: "bg-brand-light text-brand-dark",
  low: "bg-amber-50 text-amber-700",
  not_recommended: "bg-gray-100 text-gray-500",
};

export const SUGGESTION_TYPE_LABELS: Record<SuggestionType, string> = {
  product: "产品",
  brand: "品牌",
  scene: "场景",
  action: "动作",
  marketing: "营销用途",
  shot_type: "镜头类型",
  tag: "标签",
};

export const ASPECT_RATIO_OPTIONS = ASPECT_RATIO_VALUES;

// 搜索示例（静态示例，明确标注为示例，绝不冒充 suggestions API 返回）
export const SEARCH_EXAMPLES: string[] = [
  "找桌面上给手机充电的竖屏镜头，不要人脸",
  "Find a clean product shot in a car interior",
  "outdoor 安装产品的 close-up，exclude blurry shots",
  "酒店房间里手持产品展示，已人工确认，时长 3 到 6 秒",
];

export const DESCRIPTION_EXAMPLES: string[] = [
  "PowerGo 酒店桌面插墙充电，手机正在连接充电，画面要能直接做使用演示",
  "产品在车内中控台上的特写，干净背景，无competitor logo",
];

// ---------------- 格式化 ----------------

/** 匹配度：后端 match_percent（一位小数）→ 可读整数百分比；不增加虚假精度。 */
export function formatMatchPercent(matchPercent: number | null | undefined): string {
  if (matchPercent == null || Number.isNaN(matchPercent)) return "—";
  const clamped = Math.max(0, Math.min(100, matchPercent));
  return `${Math.round(clamped)}%`;
}

/** 分项分（[0,1] 或 null）→ 整数百分比；null 表示通道缺失，返回占位（绝不当 0）。 */
export function formatSubScore(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "—";
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`;
}

/** 画幅展示：优先后端 orientation，其次由宽高推断，否则原始比。 */
export function formatAspect(
  width: number | null | undefined,
  height: number | null | undefined,
  orientation: string | null | undefined,
): string {
  const label =
    orientation === "portrait"
      ? "竖屏"
      : orientation === "landscape"
        ? "横屏"
        : orientation === "square"
          ? "方形"
          : "";
  if (label) return label;
  if (width && height) {
    if (Math.abs(width / height - 9 / 16) < 0.06) return "竖屏";
    if (Math.abs(width / height - 16 / 9) < 0.06) return "横屏";
    if (Math.abs(width / height - 1) < 0.06) return "方形";
  }
  return "—";
}

// ---------------- 文本 → 词条 ----------------

/** 把逗号/中文逗号/换行/分号分隔的文本拆为去空去重词条（保序）。 */
export function splitTerms(text: string): string[] {
  if (!text) return [];
  const parts = text
    .split(/[,，;；\n\r]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const p of parts) {
    const k = p.toLowerCase();
    if (!seen.has(k)) {
      seen.add(k);
      out.push(p);
    }
  }
  return out;
}

function parseNum(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

// ---------------- 表单状态 ----------------

export type StaleFilter = "" | "true" | "false";

export interface SearchFormState {
  query: string;
  mode: SearchMode;
  sort: SearchSort;
  productId: number | null;
  brands: string;
  models: string;
  skus: string;
  scenes: string;
  actions: string;
  shotTypes: string;
  marketingUses: string;
  qualityLevels: string;
  includeRisks: string;
  excludeRisks: string;
  durationMin: string;
  durationMax: string;
  aspectRatios: AspectRatioValue[];
  reviewStatuses: ReviewStatus[];
  confirmedOnly: boolean;
  stale: StaleFilter;
  sourceDirectoryId: number | null;
  createdFrom: string;
  createdTo: string;
  includeExcluded: boolean;
}

export const EMPTY_SEARCH_FORM: SearchFormState = {
  query: "",
  mode: "hybrid",
  sort: "relevance",
  productId: null,
  brands: "",
  models: "",
  skus: "",
  scenes: "",
  actions: "",
  shotTypes: "",
  marketingUses: "",
  qualityLevels: "",
  includeRisks: "",
  excludeRisks: "",
  durationMin: "",
  durationMax: "",
  aspectRatios: [],
  reviewStatuses: [],
  confirmedOnly: false,
  stale: "",
  sourceDirectoryId: null,
  createdFrom: "",
  createdTo: "",
  includeExcluded: false,
};

/** 是否填写了除排序/分页外的任意可检索信号（决定是否允许发起搜索）。 */
export function hasSearchSignal(f: SearchFormState): boolean {
  return Boolean(
    f.query.trim() ||
      f.productId != null ||
      splitTerms(f.brands).length ||
      splitTerms(f.models).length ||
      splitTerms(f.skus).length ||
      splitTerms(f.scenes).length ||
      splitTerms(f.actions).length ||
      splitTerms(f.shotTypes).length ||
      splitTerms(f.marketingUses).length ||
      splitTerms(f.qualityLevels).length ||
      splitTerms(f.includeRisks).length ||
      splitTerms(f.excludeRisks).length ||
      f.aspectRatios.length ||
      f.reviewStatuses.length ||
      f.confirmedOnly ||
      f.stale !== "" ||
      f.sourceDirectoryId != null ||
      f.createdFrom ||
      f.createdTo ||
      parseNum(f.durationMin) != null ||
      parseNum(f.durationMax) != null,
  );
}

/** 计数已启用的高级筛选项（用于折叠面板上的徽标）。 */
export function countActiveFilters(f: SearchFormState): number {
  let n = 0;
  if (f.productId != null) n++;
  for (const t of [
    f.brands,
    f.models,
    f.skus,
    f.scenes,
    f.actions,
    f.shotTypes,
    f.marketingUses,
    f.qualityLevels,
    f.includeRisks,
    f.excludeRisks,
  ]) {
    if (splitTerms(t).length) n++;
  }
  if (f.aspectRatios.length) n++;
  if (f.reviewStatuses.length) n++;
  if (f.confirmedOnly) n++;
  if (f.stale !== "") n++;
  if (f.sourceDirectoryId != null) n++;
  if (f.createdFrom) n++;
  if (f.createdTo) n++;
  if (parseNum(f.durationMin) != null || parseNum(f.durationMax) != null) n++;
  if (f.includeExcluded) n++;
  return n;
}

/** 由表单 + 分页组装搜索请求；空字段一律省略，保证 query key 稳定。 */
export function buildSearchRequest(
  f: SearchFormState,
  page: number,
  pageSize: number,
): ShotSearchRequest {
  const req: ShotSearchRequest = {
    search_mode: f.mode,
    sort: f.sort,
    page,
    page_size: pageSize,
  };
  const q = f.query.trim();
  if (q) req.query = q;
  if (f.productId != null) req.product_ids = [f.productId];
  const setList = (key: keyof ShotSearchRequest, text: string) => {
    const arr = splitTerms(text);
    if (arr.length) (req[key] as string[]) = arr;
  };
  setList("brands", f.brands);
  setList("models", f.models);
  setList("skus", f.skus);
  setList("scenes", f.scenes);
  setList("actions", f.actions);
  setList("shot_types", f.shotTypes);
  setList("marketing_uses", f.marketingUses);
  setList("quality_levels", f.qualityLevels);
  setList("include_risks", f.includeRisks);
  setList("exclude_risks", f.excludeRisks);
  const dmin = parseNum(f.durationMin);
  const dmax = parseNum(f.durationMax);
  if (dmin != null) req.duration_min = dmin;
  if (dmax != null) req.duration_max = dmax;
  if (f.aspectRatios.length) req.aspect_ratios = f.aspectRatios;
  if (f.reviewStatuses.length) req.review_statuses = f.reviewStatuses;
  if (f.confirmedOnly) req.confirmed_only = true;
  if (f.includeExcluded) req.include_excluded = true;
  if (f.stale === "true") req.stale = true;
  else if (f.stale === "false") req.stale = false;
  if (f.sourceDirectoryId != null) req.source_directory_id = f.sourceDirectoryId;
  // <input type=date> 给出纯日期串；按**本地时区**取当日起点/终点，避免 UTC 午夜导致
  // created_to 把当天创建的镜头全部排除（后端用 created_at <= created_to 含上界）。
  if (f.createdFrom) req.created_from = new Date(`${f.createdFrom}T00:00:00`).toISOString();
  if (f.createdTo) req.created_to = new Date(`${f.createdTo}T23:59:59.999`).toISOString();
  return req;
}

/** 由保存的搜索请求（序列化 ShotSearchRequest）还原为表单状态，用于「加载保存的搜索」。
 *  与 buildSearchRequest 互逆：空字段回退到 EMPTY_SEARCH_FORM 默认值。 */
export function requestToForm(req: Partial<ShotSearchRequest>): SearchFormState {
  const joinList = (arr: string[] | undefined): string => (arr && arr.length ? arr.join("、") : "");
  const isoToDate = (iso: string | null | undefined): string => {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const pad = (n: number) => n.toString().padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  };
  return {
    ...EMPTY_SEARCH_FORM,
    query: req.query ?? "",
    mode: (req.search_mode as SearchMode) ?? "hybrid",
    sort: (req.sort as SearchSort) ?? "relevance",
    productId: req.product_ids && req.product_ids.length ? req.product_ids[0] : null,
    brands: joinList(req.brands),
    models: joinList(req.models),
    skus: joinList(req.skus),
    scenes: joinList(req.scenes),
    actions: joinList(req.actions),
    shotTypes: joinList(req.shot_types),
    marketingUses: joinList(req.marketing_uses),
    qualityLevels: joinList(req.quality_levels),
    includeRisks: joinList(req.include_risks),
    excludeRisks: joinList(req.exclude_risks),
    durationMin: req.duration_min != null ? String(req.duration_min) : "",
    durationMax: req.duration_max != null ? String(req.duration_max) : "",
    aspectRatios: req.aspect_ratios ?? [],
    reviewStatuses: req.review_statuses ?? [],
    confirmedOnly: req.confirmed_only ?? false,
    stale: req.stale === true ? "true" : req.stale === false ? "false" : "",
    sourceDirectoryId: req.source_directory_id ?? null,
    createdFrom: isoToDate(req.created_from),
    createdTo: isoToDate(req.created_to),
    includeExcluded: req.include_excluded ?? false,
  };
}

// ---------------- 画面描述匹配表单 ----------------

export interface DescriptionFormState {
  target: string;
  productId: number | null;
  limit: number;
  minimumScore: number; // 0..1
  excludeRisks: string;
  confirmedOnly: boolean;
  allowSimilarScene: boolean;
  allowSimilarAction: boolean;
  durationMin: string;
  durationMax: string;
  aspectRatios: AspectRatioValue[];
}

export const EMPTY_DESCRIPTION_FORM: DescriptionFormState = {
  target: "",
  productId: null,
  limit: 10,
  minimumScore: 0,
  excludeRisks: "",
  confirmedOnly: false,
  allowSimilarScene: true,
  allowSimilarAction: true,
  durationMin: "",
  durationMax: "",
  aspectRatios: [],
};

export function buildDescriptionRequest(f: DescriptionFormState): DescriptionMatchRequest {
  const req: DescriptionMatchRequest = {
    target_description: f.target.trim(),
    limit: f.limit,
    minimum_score: f.minimumScore,
    confirmed_only: f.confirmedOnly,
    allow_similar_scene: f.allowSimilarScene,
    allow_similar_action: f.allowSimilarAction,
  };
  if (f.productId != null) req.product_id = f.productId;
  const risks = splitTerms(f.excludeRisks);
  if (risks.length) req.exclude_risks = risks;
  const dmin = parseNum(f.durationMin);
  const dmax = parseNum(f.durationMax);
  if (dmin != null) req.duration_min = dmin;
  if (dmax != null) req.duration_max = dmax;
  if (f.aspectRatios.length) req.aspect_ratios = f.aspectRatios;
  return req;
}

// ---------------- 降级原因友好文案 ----------------

/** 把后端 degradation_reasons 代码映射为简短中文说明（未知代码原样返回）。 */
export function degradationReasonLabel(reason: string): string {
  if (reason === "parser_degraded") return "AI 查询理解暂时不可用，已用规则解析";
  if (reason.startsWith("embedding_provider_unhealthy")) return "语义向量服务暂不可用";
  if (reason.startsWith("query_embedding_failed")) return "查询向量化失败";
  return reason;
}

// ---------------- 索引健康（简化态）----------------

export type IndexHealthLevel = "ok" | "building" | "partial" | "error";

export interface IndexHealth {
  level: IndexHealthLevel;
  label: string;
  hint: string;
}

/** 由 index status 推导给普通用户的简化健康态。 */
export function deriveIndexHealth(s: SearchIndexStatus | null | undefined): IndexHealth {
  if (!s) return { level: "ok", label: "—", hint: "" };
  if (!s.provider_healthy || s.failed_embeddings > 0) {
    return {
      level: s.failed_embeddings > 0 ? "error" : "partial",
      label: s.failed_embeddings > 0 ? "异常" : "部分降级",
      hint: s.failed_embeddings > 0 ? "部分镜头嵌入失败，可重建索引" : "语义向量服务暂不可用，已退化为关键词检索",
    };
  }
  if (s.pending_embeddings > 0 || s.embedding_version_mismatched > 0) {
    return {
      level: "building",
      label: "建设中",
      hint: "部分新素材仍在建立索引，当前结果可能不完整",
    };
  }
  if (s.degraded_embeddings > 0) {
    return { level: "partial", label: "部分降级", hint: "部分镜头未参与语义召回（关键词仍可用）" };
  }
  // 空索引（无可检索文档）绝不谎报"正常"：尚无任何镜头/文档时显示"未建立索引"。
  if (s.total_shots === 0 || s.indexed_documents === 0) {
    return {
      level: "building",
      label: "未建立索引",
      hint: "尚无可检索的镜头文档，请先完成镜头分析 / 索引构建",
    };
  }
  return { level: "ok", label: "正常", hint: "检索索引正常" };
}

export const INDEX_HEALTH_TONE: Record<IndexHealthLevel, string> = {
  ok: "bg-emerald-100 text-emerald-700",
  building: "bg-blue-100 text-blue-700",
  partial: "bg-amber-100 text-amber-800",
  error: "bg-red-100 text-red-700",
};

// ---------------- URL 核心状态（不含敏感信息）----------------

export interface SearchUrlState {
  mode: "search" | "description";
  query: string;
  searchMode: SearchMode;
  sort: SearchSort;
  page: number;
  productId: number | null;
}

const SEARCH_MODES: SearchMode[] = ["hybrid", "semantic", "lexical", "structured"];
const SORTS: SearchSort[] = ["relevance", "latest", "duration", "quality"];

export function encodeSearchUrl(s: SearchUrlState): URLSearchParams {
  const p = new URLSearchParams();
  if (s.mode === "description") p.set("mode", "description");
  if (s.query.trim()) p.set("q", s.query.trim());
  if (s.searchMode !== "hybrid") p.set("sm", s.searchMode);
  if (s.sort !== "relevance") p.set("sort", s.sort);
  if (s.page > 1) p.set("page", String(s.page));
  if (s.productId != null) p.set("product", String(s.productId));
  return p;
}

export function decodeSearchUrl(params: URLSearchParams | Record<string, string | undefined>): SearchUrlState {
  const get = (k: string): string | undefined =>
    params instanceof URLSearchParams ? (params.get(k) ?? undefined) : params[k];
  const sm = get("sm");
  const sort = get("sort");
  const pageRaw = Number(get("page"));
  const productRaw = Number(get("product"));
  return {
    mode: get("mode") === "description" ? "description" : "search",
    query: get("q") ?? "",
    searchMode: SEARCH_MODES.includes(sm as SearchMode) ? (sm as SearchMode) : "hybrid",
    sort: SORTS.includes(sort as SearchSort) ? (sort as SearchSort) : "relevance",
    page: Number.isFinite(pageRaw) && pageRaw >= 1 ? Math.floor(pageRaw) : 1,
    productId: Number.isFinite(productRaw) && productRaw > 0 ? Math.floor(productRaw) : null,
  };
}
