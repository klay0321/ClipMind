import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectCollectionsTab } from "@/components/projects/tabs";
import * as hooks from "@/lib/hooks";

import { makeProject } from "../projects/fixtures";
import { makeDynamicCollection, mutation, query } from "./fixtures";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual };
});

vi.mock("@/lib/hooks", () => ({
  useProjectCollections: vi.fn(),
  useCreateCollection: vi.fn(),
  useDeleteCollection: vi.fn(),
  useDynamicCollections: vi.fn(),
  useCreateDynamicCollection: vi.fn(),
  useDeleteDynamicCollection: vi.fn(),
  useUpdateDynamicCollection: vi.fn(),
  useDynamicCollectionShots: vi.fn(),
}));

function renderC(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const empty = () => query({ data: { items: [], total: 0, page: 1, page_size: 20 } });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hooks.useProjectCollections).mockReturnValue(empty());
  vi.mocked(hooks.useCreateCollection).mockReturnValue(mutation());
  vi.mocked(hooks.useDeleteCollection).mockReturnValue(mutation());
  vi.mocked(hooks.useDynamicCollections).mockReturnValue(empty());
  vi.mocked(hooks.useCreateDynamicCollection).mockReturnValue(mutation());
  vi.mocked(hooks.useDeleteDynamicCollection).mockReturnValue(mutation());
  vi.mocked(hooks.useUpdateDynamicCollection).mockReturnValue(mutation());
  vi.mocked(hooks.useDynamicCollectionShots).mockReturnValue(query());
});

describe("ProjectCollectionsTab 静态/动态分区", () => {
  it("同时渲染静态集合与动态集合两个区块", () => {
    renderC(<ProjectCollectionsTab project={makeProject()} />);
    expect(screen.getByTestId("static-collections")).toBeInTheDocument();
    expect(screen.getByTestId("dynamic-collections")).toBeInTheDocument();
  });

  it("动态集合区块展示「实时更新，不保存固定镜头成员」说明", () => {
    renderC(<ProjectCollectionsTab project={makeProject()} />);
    expect(
      screen.getByText(/动态集合会根据当前素材和搜索索引实时更新，不保存固定镜头成员/),
    ).toBeInTheDocument();
  });

  it("创建动态集合 → 调 mutate 带 search_kind + query", async () => {
    const create = mutation();
    vi.mocked(hooks.useCreateDynamicCollection).mockReturnValue(create);
    const user = userEvent.setup();
    renderC(<ProjectCollectionsTab project={makeProject()} />);
    await user.click(screen.getByTestId("create-dynamic-collection"));
    await user.type(screen.getByLabelText("动态集合名称"), "实时特写");
    await user.type(screen.getByTestId("dynamic-query"), "竖屏 特写");
    await user.click(screen.getByTestId("submit-dynamic-collection"));
    expect(create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "实时特写",
        search_kind: "shot_search",
        query: { query: "竖屏 特写" },
      }),
      expect.anything(),
    );
  });

  it("归档项目禁用新建动态集合", () => {
    renderC(<ProjectCollectionsTab project={makeProject({ status: "archived" })} />);
    expect(screen.getByTestId("create-dynamic-collection")).toBeDisabled();
  });

  it("打开动态集合 → 渲染实时镜头区块", async () => {
    vi.mocked(hooks.useDynamicCollections).mockReturnValue(
      query({ data: { items: [makeDynamicCollection()], total: 1, page: 1, page_size: 20 } }),
    );
    const user = userEvent.setup();
    renderC(<ProjectCollectionsTab project={makeProject()} />);
    expect(screen.getByTestId("dynamic-collection-1")).toBeInTheDocument();
    await user.click(screen.getByTestId("open-dynamic-1"));
    expect(screen.getByTestId("dynamic-collection-shots")).toBeInTheDocument();
  });

  it("删除动态集合 → 确认后调 mutate", async () => {
    const del = mutation();
    vi.mocked(hooks.useDeleteDynamicCollection).mockReturnValue(del);
    vi.mocked(hooks.useDynamicCollections).mockReturnValue(
      query({ data: { items: [makeDynamicCollection()], total: 1, page: 1, page_size: 20 } }),
    );
    const user = userEvent.setup();
    renderC(<ProjectCollectionsTab project={makeProject()} />);
    await user.click(screen.getByTestId("delete-dynamic-1"));
    await user.click(screen.getByTestId("confirm-ok"));
    expect(del.mutate).toHaveBeenCalledWith(1, expect.anything());
  });
});
