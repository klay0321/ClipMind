import { vi } from "vitest";

import type {
  DescriptionMatchItem,
  DescriptionMatchResponse,
  ParsedSearchQuery,
  SearchResultItem,
  ShotSearchResponse,
} from "@/lib/types";

// TanStack Query 结果桩（与现有测试一致的形状）
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function query(overrides: Record<string, any> = {}): any {
  return {
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    isFetching: false,
    refetch: vi.fn(() => Promise.resolve()),
    ...overrides,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function mutation(overrides: Record<string, any> = {}): any {
  return { mutate: vi.fn(), isPending: false, error: null, ...overrides };
}

export function makeItem(overrides: Partial<SearchResultItem> = {}): SearchResultItem {
  return {
    shot_id: 101,
    asset_id: 10,
    sequence_no: 1,
    start_time: 25,
    end_time: 30,
    duration: 5,
    status: "ready",
    asset: {
      id: 10,
      filename: "ci_demo.mp4",
      duration: 30,
      width: 1080,
      height: 1920,
      orientation: "portrait",
      source_directory_id: 1,
    },
    preview_url: "/api/shots/101/preview",
    thumbnail_url: "/api/shots/101/thumbnail",
    keyframe_url: "/api/shots/101/keyframe",
    download_url: "/api/shots/101/preview",
    product: { id: 3, name: "示例扫地机 X10", brand: "示例品牌", model: "X10", sku: "SP-X10", match_kind: "sku" },
    score: 0.64,
    match_percent: 64.3,
    semantic_score: 0.7,
    lexical_score: 0.5,
    tag_score: 0.4,
    product_score: 0.9,
    quality_score: 0.05,
    review_bonus: 0.08,
    risk_penalty: 0.0,
    matched_reasons: ["产品匹配：示例扫地机 X10", "场景匹配：桌面"],
    unmatched_requirements: [],
    risk_warnings: [],
    review_status: "confirmed",
    review_is_stale: false,
    embedding_degraded: false,
    ...overrides,
  };
}

function parsed(overrides: Partial<ParsedSearchQuery> = {}): ParsedSearchQuery {
  return {
    original_query: "",
    normalized_query: "",
    positive_terms: [],
    negative_terms: [],
    products: [],
    brands: [],
    models: [],
    skus: [],
    scenes: [],
    actions: [],
    shot_types: [],
    marketing_uses: [],
    people: [],
    objects: [],
    quality_requirements: [],
    required_risks: [],
    excluded_risks: [],
    min_duration: null,
    max_duration: null,
    aspect_ratios: [],
    review_statuses: [],
    confirmed_only: false,
    include_excluded: false,
    allow_similar_scene: true,
    allow_similar_action: true,
    semantic_text: "",
    parser_provider: "rulebased",
    parser_model: "",
    parser_status: "ok",
    parser_warnings: [],
    ...overrides,
  };
}

export function makeResponse(
  items: SearchResultItem[],
  overrides: Partial<ShotSearchResponse> = {},
): ShotSearchResponse {
  return {
    items,
    total: items.length,
    filtered_total: items.length,
    truncated: false,
    page: 1,
    page_size: 24,
    search_mode_used: "hybrid",
    parser_status: "ok",
    parser_provider: "rulebased",
    embedding_status: "ok",
    degraded: false,
    degradation_reasons: [],
    elapsed_ms: 42,
    query_plan_summary: {},
    parsed_query: parsed(),
    ...overrides,
  };
}

export function makeMatchItem(overrides: Partial<DescriptionMatchItem> = {}): DescriptionMatchItem {
  return {
    ...makeItem(),
    target_requirements: ["产品：示例扫地机 X10", "场景：桌面"],
    matched_requirements: ["产品匹配：示例扫地机 X10"],
    requires_human_confirmation: false,
    recommendation_level: "high",
    ...overrides,
  };
}

export function makeMatchResponse(
  items: DescriptionMatchItem[],
  overrides: Partial<DescriptionMatchResponse> = {},
): DescriptionMatchResponse {
  return {
    items,
    total: items.length,
    filtered_total: items.length,
    truncated: false,
    minimum_score: 0,
    target_requirements: ["产品：示例扫地机 X10"],
    search_mode_used: "hybrid",
    parser_status: "ok",
    embedding_status: "ok",
    degraded: false,
    degradation_reasons: [],
    elapsed_ms: 33,
    ...overrides,
  };
}
