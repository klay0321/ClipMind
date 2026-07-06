import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SearchWorkbench } from "@/components/search/SearchWorkbench";
import * as hooks from "@/lib/hooks";
import type { SearchUrlState } from "@/lib/search";

import { makeResponse, makeItem, query } from "./fixtures";

const replaceMock = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock("@/lib/hooks", () => ({
  useSemanticSearch: vi.fn(),
  useDescriptionMatch: vi.fn(),
  useProducts: vi.fn(),
  usePmSummary: vi.fn(),
  useAssetSearch: vi.fn(),
  useSourceDirectories: vi.fn(),
  useSearchSuggestions: vi.fn(),
  useSearchIndexStatus: vi.fn(),
  // PR-06B：SavedSearchPanel / BundleBar / FavoriteButton 依赖
  useSavedSearches: vi.fn(() => ({ data: { items: [], total: 0, page: 1, page_size: 50 } })),
  useCreateSavedSearch: vi.fn(() => ({ mutate: vi.fn(), isPending: false, error: null })),
  useUpdateSavedSearch: vi.fn(() => ({ mutate: vi.fn(), isPending: false, error: null })),
  useDeleteSavedSearch: vi.fn(() => ({ mutate: vi.fn(), isPending: false, error: null })),
  useCreateBundle: vi.fn(() => ({ mutate: vi.fn(), isPending: false, error: null })),
  useBundleStatus: vi.fn(() => ({ data: undefined })),
  useCreateFavorite: vi.fn(() => ({ mutate: vi.fn(), isPending: false, error: null })),
}));

const INITIAL: SearchUrlState = {
  mode: "search",
  query: "",
  searchMode: "hybrid",
  sort: "relevance",
  page: 1,
  productId: null,
};

beforeEach(() => {
  replaceMock.mockClear();
  vi.mocked(hooks.useSemanticSearch).mockReturnValue(query());
  vi.mocked(hooks.usePmSummary).mockReturnValue({ data: [], isLoading: false } as never);
  vi.mocked(hooks.useAssetSearch).mockReturnValue({ data: undefined, isLoading: false, isError: false, isFetching: false } as never);
  vi.mocked(hooks.useDescriptionMatch).mockReturnValue(query());
  vi.mocked(hooks.useProducts).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useSourceDirectories).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useSearchSuggestions).mockReturnValue(query({ data: { items: [] } }));
  vi.mocked(hooks.useSearchIndexStatus).mockReturnValue(query({ data: undefined }));
});

describe("SearchWorkbench", () => {
  it("默认素材语义搜索模式，含智能匹配标题与两个标签", () => {
    render(<SearchWorkbench initial={INITIAL} />);
    expect(screen.getByRole("heading", { name: "智能匹配" })).toBeInTheDocument();
    expect(screen.getByTestId("tab-search")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("tab-description")).toHaveAttribute("aria-selected", "false");
  });

  it("切到画面描述匹配并把 mode 写入 URL", async () => {
    const user = userEvent.setup();
    render(<SearchWorkbench initial={INITIAL} />);
    await user.click(screen.getByTestId("tab-description"));
    expect(screen.getByTestId("tab-description")).toHaveAttribute("aria-selected", "true");
    expect(replaceMock).toHaveBeenCalled();
    const url = replaceMock.mock.calls.at(-1)?.[0] as string;
    expect(url).toContain("mode=description");
  });

  it("按 URL 初始状态恢复（mode=description）", () => {
    render(<SearchWorkbench initial={{ ...INITIAL, mode: "description" }} />);
    expect(screen.getByTestId("tab-description")).toHaveAttribute("aria-selected", "true");
  });

  it("视频按需加载：初始无预览视频，点击预览后才挂载代理视频", async () => {
    vi.mocked(hooks.useSemanticSearch).mockReturnValue(
      query({ data: makeResponse([makeItem()]) }),
    );
    const user = userEvent.setup();
    render(<SearchWorkbench initial={{ ...INITIAL, query: "x" }} />);
    expect(screen.queryByTestId("preview-video")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("result-preview-btn"));
    expect(screen.getByTestId("preview-video")).toBeInTheDocument();
  });
});
