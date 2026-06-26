import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SemanticSearchView } from "@/components/search/SemanticSearchView";
import * as hooks from "@/lib/hooks";
import { EMPTY_SEARCH_FORM } from "@/lib/search";

import { makeItem, makeResponse, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useSemanticSearch: vi.fn(),
  useProducts: vi.fn(),
  useSourceDirectories: vi.fn(),
  useSearchSuggestions: vi.fn(),
}));

function lastReq() {
  const calls = vi.mocked(hooks.useSemanticSearch).mock.calls;
  return calls.at(-1)?.[0];
}

function renderView(props: Partial<React.ComponentProps<typeof SemanticSearchView>> = {}) {
  return render(
    <SemanticSearchView
      initialForm={EMPTY_SEARCH_FORM}
      initialPage={1}
      onCoreChange={vi.fn()}
      onOpenItem={vi.fn()}
      onPreview={vi.fn()}
      selectedShotId={null}
      {...props}
    />,
  );
}

beforeEach(() => {
  vi.mocked(hooks.useSemanticSearch).mockReturnValue(query());
  vi.mocked(hooks.useProducts).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useSourceDirectories).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useSearchSuggestions).mockReturnValue(query({ data: { items: [] } }));
});

describe("SemanticSearchView 初始与提交", () => {
  it("初始无 committed → 不发请求且显示初始空态", () => {
    renderView();
    expect(lastReq()).toBeNull();
    expect(screen.getByText("输入条件开始搜索")).toBeInTheDocument();
  });

  it("输入并提交 → 以 hybrid 组装请求", async () => {
    const user = userEvent.setup();
    renderView();
    await user.type(screen.getByTestId("search-input"), "桌面充电 竖屏");
    await user.click(screen.getByTestId("search-submit"));
    expect(lastReq()).toMatchObject({
      query: "桌面充电 竖屏",
      search_mode: "hybrid",
      sort: "relevance",
      page: 1,
      page_size: 24,
    });
  });

  it("Enter 与按钮一致触发搜索", async () => {
    const user = userEvent.setup();
    renderView();
    const input = screen.getByTestId("search-input");
    await user.type(input, "产品特写{Enter}");
    expect(lastReq()).toMatchObject({ query: "产品特写" });
  });

  it("切换 semantic / lexical / structured 模式写入请求", async () => {
    const user = userEvent.setup();
    renderView();
    await user.type(screen.getByTestId("search-input"), "x");
    await user.click(screen.getByTestId("mode-semantic"));
    await user.click(screen.getByTestId("search-submit"));
    expect(lastReq()).toMatchObject({ search_mode: "semantic" });
    await user.click(screen.getByTestId("mode-lexical"));
    await user.click(screen.getByTestId("search-submit"));
    expect(lastReq()).toMatchObject({ search_mode: "lexical" });
  });
});

describe("SemanticSearchView 高级筛选", () => {
  it("场景 + 风险排除 + 时长 + 画幅 + 仅人工确认 组装进请求", async () => {
    const user = userEvent.setup();
    renderView();
    await user.type(screen.getByTestId("search-input"), "产品");
    await user.click(screen.getByTestId("advanced-filters-toggle"));
    await user.type(screen.getByTestId("filter-scenes"), "桌面");
    await user.type(screen.getByTestId("filter-exclude-risks"), "blur");
    await user.type(screen.getByTestId("filter-duration-min"), "3");
    await user.click(screen.getByTestId("filter-aspect-9:16"));
    await user.click(screen.getByTestId("filter-confirmed-only"));
    await user.click(screen.getByTestId("filters-apply"));
    expect(lastReq()).toMatchObject({
      query: "产品",
      scenes: ["桌面"],
      exclude_risks: ["blur"],
      duration_min: 3,
      aspect_ratios: ["9:16"],
      confirmed_only: true,
    });
  });
});

describe("SemanticSearchView 结果渲染", () => {
  it("展示元信息 total/filtered_total/truncated 与实际模式", () => {
    vi.mocked(hooks.useSemanticSearch).mockReturnValue(
      query({
        data: makeResponse([makeItem()], {
          total: 5,
          filtered_total: 42,
          truncated: true,
          search_mode_used: "lexical",
          elapsed_ms: 88,
        }),
      }),
    );
    renderView({ initialForm: { ...EMPTY_SEARCH_FORM, query: "x" } });
    const meta = screen.getByTestId("results-meta");
    expect(meta).toHaveTextContent("42");
    expect(meta).toHaveTextContent("5");
    expect(meta).toHaveTextContent("已截断");
    expect(meta).toHaveTextContent("lexical");
  });

  it("结果卡展示匹配理由与风险，degraded 标记", () => {
    vi.mocked(hooks.useSemanticSearch).mockReturnValue(
      query({
        data: makeResponse([
          makeItem({
            matched_reasons: ["场景匹配：桌面"],
            risk_warnings: ["competitor logo"],
            embedding_degraded: true,
          }),
        ]),
      }),
    );
    renderView({ initialForm: { ...EMPTY_SEARCH_FORM, query: "x" } });
    const card = screen.getByTestId("search-result-card");
    expect(within(card).getByText(/场景匹配：桌面/)).toBeInTheDocument();
    expect(within(card).getByTestId("card-risk")).toHaveTextContent("competitor logo");
    expect(within(card).getByText("语义降级")).toBeInTheDocument();
  });

  it("点击结果卡回调 onOpenItem", async () => {
    const onOpenItem = vi.fn();
    vi.mocked(hooks.useSemanticSearch).mockReturnValue(query({ data: makeResponse([makeItem()]) }));
    const user = userEvent.setup();
    renderView({ initialForm: { ...EMPTY_SEARCH_FORM, query: "x" }, onOpenItem });
    await user.click(within(screen.getByTestId("search-result-card")).getByTitle("查看匹配详情"));
    expect(onOpenItem).toHaveBeenCalledWith(expect.objectContaining({ shot_id: 101 }));
  });

  it("分页：下一页提交 page=2", async () => {
    vi.mocked(hooks.useSemanticSearch).mockReturnValue(
      query({ data: makeResponse([makeItem()], { total: 60, page_size: 24 }) }),
    );
    const user = userEvent.setup();
    renderView({ initialForm: { ...EMPTY_SEARCH_FORM, query: "x" } });
    await user.click(screen.getByTestId("page-next"));
    expect(lastReq()).toMatchObject({ page: 2 });
  });

  it("排序变更触发 page=1 + sort", async () => {
    vi.mocked(hooks.useSemanticSearch).mockReturnValue(query({ data: makeResponse([makeItem()]) }));
    const user = userEvent.setup();
    renderView({ initialForm: { ...EMPTY_SEARCH_FORM, query: "x" } });
    await user.selectOptions(screen.getByTestId("sort-select"), "latest");
    expect(lastReq()).toMatchObject({ sort: "latest", page: 1 });
  });

  it("切换排序基于已提交条件，不泄漏未提交的草稿查询", async () => {
    vi.mocked(hooks.useSemanticSearch).mockReturnValue(query({ data: makeResponse([makeItem()]) }));
    const user = userEvent.setup();
    renderView();
    await user.type(screen.getByTestId("search-input"), "充电");
    await user.click(screen.getByTestId("search-submit")); // 提交 query=充电
    await user.type(screen.getByTestId("search-input"), "额外词"); // 仅草稿，未提交
    await user.selectOptions(screen.getByTestId("sort-select"), "latest");
    // query 精确为已提交的"充电"，不含未提交草稿"额外词"
    expect(lastReq()).toMatchObject({ query: "充电", sort: "latest" });
  });

  it("当前页越界但仍有候选时，提示返回第 1 页而非误报无结果", () => {
    vi.mocked(hooks.useSemanticSearch).mockReturnValue(
      query({ data: makeResponse([], { total: 5, page_size: 24 }) }),
    );
    renderView({ initialForm: { ...EMPTY_SEARCH_FORM, query: "x" }, initialPage: 9 });
    expect(screen.getByText("本页没有结果")).toBeInTheDocument();
    expect(screen.getByTestId("back-to-first-page")).toBeInTheDocument();
    expect(screen.queryByText("没有匹配的镜头")).not.toBeInTheDocument();
  });
});

describe("SemanticSearchView 降级与异常状态", () => {
  it("parser degraded 显示提示", () => {
    vi.mocked(hooks.useSemanticSearch).mockReturnValue(
      query({ data: makeResponse([makeItem()], { parser_status: "degraded", degradation_reasons: ["parser_degraded"] }) }),
    );
    renderView({ initialForm: { ...EMPTY_SEARCH_FORM, query: "x" } });
    expect(screen.getByTestId("degraded-parser")).toBeInTheDocument();
  });

  it("embedding degraded 显示提示，但仍渲染结果", () => {
    vi.mocked(hooks.useSemanticSearch).mockReturnValue(
      query({ data: makeResponse([makeItem()], { embedding_status: "degraded" }) }),
    );
    renderView({ initialForm: { ...EMPTY_SEARCH_FORM, query: "x" } });
    expect(screen.getByTestId("degraded-embedding")).toBeInTheDocument();
    expect(screen.getByTestId("search-result-card")).toBeInTheDocument();
  });

  it("空结果给出放宽建议", () => {
    vi.mocked(hooks.useSemanticSearch).mockReturnValue(query({ data: makeResponse([]) }));
    renderView({ initialForm: { ...EMPTY_SEARCH_FORM, query: "x" } });
    expect(screen.getByText("没有匹配的镜头")).toBeInTheDocument();
  });

  it("API 错误显示错误态与重试", () => {
    const refetch = vi.fn(() => Promise.resolve());
    vi.mocked(hooks.useSemanticSearch).mockReturnValue(
      query({ isError: true, error: new Error("boom"), refetch }),
    );
    renderView({ initialForm: { ...EMPTY_SEARCH_FORM, query: "x" } });
    expect(screen.getByTestId("error")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });
});
