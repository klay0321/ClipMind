import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SavedSearchPanel } from "@/components/search/SavedSearchPanel";
import * as hooks from "@/lib/hooks";

import { makeSavedSearch, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useSavedSearches: vi.fn(),
  useCreateSavedSearch: vi.fn(),
  useUpdateSavedSearch: vi.fn(),
  useDeleteSavedSearch: vi.fn(),
}));

function renderC(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hooks.useSavedSearches).mockReturnValue(
    query({ data: { items: [makeSavedSearch()], total: 1, page: 1, page_size: 50 } }),
  );
  vi.mocked(hooks.useCreateSavedSearch).mockReturnValue(mutation());
  vi.mocked(hooks.useUpdateSavedSearch).mockReturnValue(mutation());
  vi.mocked(hooks.useDeleteSavedSearch).mockReturnValue(mutation());
});

describe("SavedSearchPanel", () => {
  it("保存当前搜索：填名称 → 调创建并带序列化 query", async () => {
    const create = mutation();
    vi.mocked(hooks.useCreateSavedSearch).mockReturnValue(create);
    const user = userEvent.setup();
    renderC(
      <SavedSearchPanel
        searchKind="shot_search"
        currentQuery={{ query: "竖屏 产品", search_mode: "hybrid" }}
        canSave
        onLoad={vi.fn()}
      />,
    );
    await user.click(screen.getByTestId("save-search"));
    await user.type(screen.getByLabelText("搜索名称"), "我的搜索");
    await user.click(screen.getByTestId("confirm-save-search"));
    expect(create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "我的搜索",
        search_kind: "shot_search",
        query: { query: "竖屏 产品", search_mode: "hybrid" },
      }),
      expect.anything(),
    );
  });

  it("无可保存条件时保存按钮禁用", () => {
    renderC(
      <SavedSearchPanel searchKind="shot_search" currentQuery={null} canSave={false} onLoad={vi.fn()} />,
    );
    expect(screen.getByTestId("save-search")).toBeDisabled();
  });

  it("加载保存的搜索 → 触发 onLoad 回调还原条件", async () => {
    const onLoad = vi.fn();
    const user = userEvent.setup();
    renderC(
      <SavedSearchPanel searchKind="shot_search" currentQuery={null} canSave={false} onLoad={onLoad} />,
    );
    await user.click(screen.getByTestId("load-saved-1"));
    expect(onLoad).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
  });

  it("运行按钮也触发 onLoad（重跑）", async () => {
    const onLoad = vi.fn();
    const user = userEvent.setup();
    renderC(
      <SavedSearchPanel searchKind="shot_search" currentQuery={null} canSave={false} onLoad={onLoad} />,
    );
    await user.click(screen.getByTestId("run-saved-1"));
    expect(onLoad).toHaveBeenCalled();
  });

  it("删除保存的搜索 → 确认后调 mutate", async () => {
    const del = mutation();
    vi.mocked(hooks.useDeleteSavedSearch).mockReturnValue(del);
    const user = userEvent.setup();
    renderC(
      <SavedSearchPanel searchKind="shot_search" currentQuery={null} canSave={false} onLoad={vi.fn()} />,
    );
    await user.click(screen.getByTestId("delete-saved-1"));
    await user.click(screen.getByTestId("confirm-ok"));
    expect(del.mutate).toHaveBeenCalledWith(1, expect.anything());
  });

  it("重命名 → 调 update 带 lock_version", async () => {
    const update = mutation();
    vi.mocked(hooks.useUpdateSavedSearch).mockReturnValue(update);
    const user = userEvent.setup();
    renderC(
      <SavedSearchPanel searchKind="shot_search" currentQuery={null} canSave={false} onLoad={vi.fn()} />,
    );
    await user.click(screen.getByTestId("rename-saved-1"));
    const input = screen.getByLabelText("重命名搜索");
    await user.clear(input);
    await user.type(input, "新名称");
    await user.click(screen.getByText("保存"));
    expect(update.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ name: "新名称", lock_version: 0 }),
      expect.anything(),
    );
  });
});
