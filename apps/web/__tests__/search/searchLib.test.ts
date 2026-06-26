import { describe, expect, it } from "vitest";

import {
  EMPTY_DESCRIPTION_FORM,
  EMPTY_SEARCH_FORM,
  buildDescriptionRequest,
  buildSearchRequest,
  countActiveFilters,
  decodeSearchUrl,
  degradationReasonLabel,
  deriveIndexHealth,
  encodeSearchUrl,
  formatAspect,
  formatMatchPercent,
  formatSubScore,
  hasSearchSignal,
  splitTerms,
} from "@/lib/search";
import type { SearchFormState } from "@/lib/search";
import type { SearchIndexStatus } from "@/lib/types";

function form(overrides: Partial<SearchFormState> = {}): SearchFormState {
  return { ...EMPTY_SEARCH_FORM, ...overrides };
}

describe("splitTerms", () => {
  it("按逗号/中文逗号/换行拆分并去空去重保序", () => {
    expect(splitTerms("a, b，b\nc; c")).toEqual(["a", "b", "c"]);
    expect(splitTerms("")).toEqual([]);
  });
});

describe("buildSearchRequest", () => {
  it("基本：仅 query + 默认模式/排序/分页", () => {
    const req = buildSearchRequest(form({ query: " 充电 不要人脸 " }), 1, 24);
    expect(req).toMatchObject({
      query: "充电 不要人脸",
      search_mode: "hybrid",
      sort: "relevance",
      page: 1,
      page_size: 24,
    });
    // 空字段不出现
    expect("brands" in req).toBe(false);
    expect("scenes" in req).toBe(false);
  });

  it("各搜索模式写入 search_mode", () => {
    expect(buildSearchRequest(form({ query: "x", mode: "semantic" }), 1, 24).search_mode).toBe("semantic");
    expect(buildSearchRequest(form({ query: "x", mode: "lexical" }), 1, 24).search_mode).toBe("lexical");
    expect(buildSearchRequest(form({ scenes: "室内", mode: "structured" }), 1, 24).search_mode).toBe("structured");
  });

  it("结构化筛选 + 风险包含/排除 + 产品 + 时长 + 画幅 + 审核状态", () => {
    const req = buildSearchRequest(
      form({
        query: "产品展示",
        productId: 7,
        scenes: "室内, 桌面",
        actions: "充电",
        includeRisks: "competitor",
        excludeRisks: "blur, 模糊",
        durationMin: "3",
        durationMax: "6",
        aspectRatios: ["9:16"],
        reviewStatuses: ["confirmed", "modified"],
        confirmedOnly: true,
        includeExcluded: true,
        stale: "true",
        sourceDirectoryId: 2,
        sort: "latest",
      }),
      2,
      24,
    );
    expect(req).toMatchObject({
      query: "产品展示",
      product_ids: [7],
      scenes: ["室内", "桌面"],
      actions: ["充电"],
      include_risks: ["competitor"],
      exclude_risks: ["blur", "模糊"],
      duration_min: 3,
      duration_max: 6,
      aspect_ratios: ["9:16"],
      review_statuses: ["confirmed", "modified"],
      confirmed_only: true,
      include_excluded: true,
      stale: true,
      source_directory_id: 2,
      sort: "latest",
      page: 2,
    });
  });

  it("created_from 取当日起点；created_to 取当日终点（含），同日跨度=86399999ms（时区无关）", () => {
    const req = buildSearchRequest(
      form({ query: "x", createdFrom: "2026-01-01", createdTo: "2026-01-01" }),
      1,
      24,
    );
    // created_to 必须是当日结束而非次日 00:00（否则后端 <= 上界会排除当天创建的镜头）
    const diff = new Date(req.created_to as string).getTime() - new Date(req.created_from as string).getTime();
    expect(diff).toBe(86_399_999);
  });
});

describe("hasSearchSignal / countActiveFilters", () => {
  it("空表单无信号", () => {
    expect(hasSearchSignal(EMPTY_SEARCH_FORM)).toBe(false);
    expect(countActiveFilters(EMPTY_SEARCH_FORM)).toBe(0);
  });
  it("仅 query 有信号；仅筛选也有信号", () => {
    expect(hasSearchSignal(form({ query: "a" }))).toBe(true);
    expect(hasSearchSignal(form({ scenes: "室内" }))).toBe(true);
    expect(hasSearchSignal(form({ confirmedOnly: true }))).toBe(true);
  });
  it("统计已启用筛选项数量", () => {
    expect(countActiveFilters(form({ productId: 1, scenes: "a", confirmedOnly: true }))).toBe(3);
  });
});

describe("buildDescriptionRequest", () => {
  it("组装描述匹配请求并映射开关", () => {
    const req = buildDescriptionRequest({
      ...EMPTY_DESCRIPTION_FORM,
      target: "  桌面充电演示  ",
      productId: 3,
      limit: 15,
      minimumScore: 0.4,
      excludeRisks: "competitor",
      confirmedOnly: true,
      allowSimilarScene: false,
      allowSimilarAction: true,
      durationMin: "2",
      aspectRatios: ["16:9"],
    });
    expect(req).toMatchObject({
      target_description: "桌面充电演示",
      product_id: 3,
      limit: 15,
      minimum_score: 0.4,
      exclude_risks: ["competitor"],
      confirmed_only: true,
      allow_similar_scene: false,
      allow_similar_action: true,
      duration_min: 2,
      aspect_ratios: ["16:9"],
    });
  });
});

describe("deriveIndexHealth", () => {
  function status(o: Partial<SearchIndexStatus> = {}): SearchIndexStatus {
    return {
      total_shots: 10,
      indexed_documents: 10,
      excluded_documents: 0,
      completed_embeddings: 10,
      degraded_embeddings: 0,
      failed_embeddings: 0,
      pending_embeddings: 0,
      current_embedding_version: "e5@v1",
      embedding_version_matched: 10,
      embedding_version_mismatched: 0,
      stale_documents: 0,
      last_indexed_at: null,
      provider_healthy: true,
      provider_detail: "",
      ...o,
    };
  }
  it("全就绪 → 正常", () => {
    expect(deriveIndexHealth(status()).level).toBe("ok");
  });
  it("待嵌入 → 建设中", () => {
    expect(deriveIndexHealth(status({ pending_embeddings: 3 })).level).toBe("building");
  });
  it("provider 不健康 → 部分降级", () => {
    expect(deriveIndexHealth(status({ provider_healthy: false })).level).toBe("partial");
  });
  it("嵌入失败 → 异常", () => {
    expect(deriveIndexHealth(status({ failed_embeddings: 2 })).level).toBe("error");
  });
  it("无数据不谎报正常（label 为占位）", () => {
    expect(deriveIndexHealth(null).label).toBe("—");
  });
  it("空索引（计数全 0 但 provider 健康）不谎报正常", () => {
    const h = deriveIndexHealth(status({ total_shots: 0, indexed_documents: 0, completed_embeddings: 0 }));
    expect(h.level).not.toBe("ok");
    expect(h.label).not.toContain("正常");
  });
});

describe("URL 核心状态编解码", () => {
  it("round-trip 恢复 mode/q/搜索模式/排序/页/产品", () => {
    const params = encodeSearchUrl({
      mode: "description",
      query: "桌面充电",
      searchMode: "semantic",
      sort: "latest",
      page: 3,
      productId: 5,
    });
    const decoded = decodeSearchUrl(params);
    expect(decoded).toEqual({
      mode: "description",
      query: "桌面充电",
      searchMode: "semantic",
      sort: "latest",
      page: 3,
      productId: 5,
    });
  });
  it("默认值不写 URL / 非法值回落默认", () => {
    expect(encodeSearchUrl({ mode: "search", query: "", searchMode: "hybrid", sort: "relevance", page: 1, productId: null }).toString()).toBe("");
    const d = decodeSearchUrl({ sm: "bogus", sort: "nope", page: "-2" });
    expect(d.searchMode).toBe("hybrid");
    expect(d.sort).toBe("relevance");
    expect(d.page).toBe(1);
  });
});

describe("格式化", () => {
  it("匹配度取整百分比，不增加虚假精度", () => {
    expect(formatMatchPercent(64.3)).toBe("64%");
    expect(formatMatchPercent(null)).toBe("—");
    expect(formatMatchPercent(120)).toBe("100%");
  });
  it("分项分缺失为占位（绝不当 0）", () => {
    expect(formatSubScore(null)).toBe("—");
    expect(formatSubScore(0.5)).toBe("50%");
  });
  it("画幅由 orientation/宽高推断", () => {
    expect(formatAspect(1080, 1920, "portrait")).toBe("竖屏");
    expect(formatAspect(1920, 1080, null)).toBe("横屏");
    expect(formatAspect(null, null, null)).toBe("—");
  });
  it("降级原因映射友好文案", () => {
    expect(degradationReasonLabel("parser_degraded")).toContain("AI 查询理解");
    expect(degradationReasonLabel("embedding_provider_unhealthy:foo")).toContain("语义向量");
    expect(degradationReasonLabel("unknown_code")).toBe("unknown_code");
  });
});
