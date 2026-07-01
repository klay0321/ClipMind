import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CatalogView } from "@/components/catalog/CatalogView";
import * as hooks from "@/lib/hooks";

import { makeTree, mutation, query } from "./fixtures";

// 只 mock 本页与内嵌 ProductsView 用到的 hooks；产品值全部由 mock 数据提供（无硬编码 seed）。
vi.mock("@/lib/hooks", () => ({
  useCatalogTree: vi.fn(),
  useCatalogSearch: vi.fn(),
  // 详情/子级（CatalogView 本身不直接用，但 EntityDetail 在选中时会用；本测试不选中）
  useCatalogNode: vi.fn(),
  useCatalogAliases: vi.fn(),
  useFamilies: vi.fn(),
  useVariants: vi.fn(),
  useSkus: vi.fn(),
  // 创建向导用到的一批
  useCategories: vi.fn(),
  useCreateCategory: vi.fn(),
  useCreateFamily: vi.fn(),
  useCreateVariant: vi.fn(),
  useCreateSku: vi.fn(),
  useCreateCatalogAlias: vi.fn(),
  useSetFamilyStatus: vi.fn(),
  // 内嵌扁平产品视图
  useProducts: vi.fn(),
  useProductStats: vi.fn(),
}));

function stubCommon() {
  vi.mocked(hooks.useCatalogSearch).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useCatalogAliases).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useFamilies).mockReturnValue(query({ data: { items: [], total: 0 } }));
  vi.mocked(hooks.useVariants).mockReturnValue(query({ data: { items: [], total: 0 } }));
  vi.mocked(hooks.useSkus).mockReturnValue(query({ data: { items: [], total: 0 } }));
  vi.mocked(hooks.useCategories).mockReturnValue(query({ data: { items: [], total: 0 } }));
  vi.mocked(hooks.useCreateCategory).mockReturnValue(mutation());
  vi.mocked(hooks.useCreateFamily).mockReturnValue(mutation());
  vi.mocked(hooks.useCreateVariant).mockReturnValue(mutation());
  vi.mocked(hooks.useCreateSku).mockReturnValue(mutation());
  vi.mocked(hooks.useCreateCatalogAlias).mockReturnValue(mutation());
  vi.mocked(hooks.useSetFamilyStatus).mockReturnValue(mutation());
  vi.mocked(hooks.useProducts).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useProductStats).mockReturnValue(query({ data: {} }));
}

beforeEach(() => {
  vi.clearAllMocks();
  stubCommon();
  vi.mocked(hooks.useCatalogTree).mockReturnValue(query({ data: makeTree() }));
});

describe("CatalogView", () => {
  it("加载态显示骨架", () => {
    vi.mocked(hooks.useCatalogTree).mockReturnValue(query({ isLoading: true }));
    render(<CatalogView />);
    expect(screen.getByTestId("loading")).toBeInTheDocument();
  });

  it("错误态显示错误并可重试", async () => {
    const refetch = vi.fn(() => Promise.resolve());
    vi.mocked(hooks.useCatalogTree).mockReturnValue(
      query({ isError: true, error: new Error("网络异常"), refetch }),
    );
    render(<CatalogView />);
    expect(screen.getByTestId("error")).toBeInTheDocument();
    await userEvent.click(screen.getByText("重试"));
    expect(refetch).toHaveBeenCalled();
  });

  it("空树显示空态与新建入口", () => {
    vi.mocked(hooks.useCatalogTree).mockReturnValue(query({ data: [] }));
    render(<CatalogView />);
    expect(screen.getByTestId("empty")).toBeInTheDocument();
    expect(screen.getByTestId("empty-create")).toBeInTheDocument();
  });

  it("渲染层级树（分类/产品/型号/SKU 全部来自 API）", () => {
    render(<CatalogView />);
    const tree = screen.getByTestId("catalog-tree");
    expect(within(tree).getByTestId("tree-node-category-1")).toHaveTextContent("示例分类");
    expect(within(tree).getByTestId("tree-node-family-10")).toHaveTextContent("示例产品");
    expect(within(tree).getByTestId("tree-node-variant-20")).toHaveTextContent("示例型号");
    expect(within(tree).getByTestId("tree-node-sku-30")).toHaveTextContent("示例 SKU");
  });

  it("状态计数来自真实树（active 3 / draft 1）", () => {
    render(<CatalogView />);
    const counts = screen.getByTestId("status-counts");
    expect(within(counts).getByTestId("count-active")).toHaveTextContent("3");
    expect(within(counts).getByTestId("count-draft")).toHaveTextContent("1");
  });

  it("状态筛选 draft 只保留命中路径", async () => {
    const user = userEvent.setup();
    render(<CatalogView />);
    await user.selectOptions(screen.getByTestId("catalog-status-filter"), "draft");
    const tree = screen.getByTestId("catalog-tree");
    // draft 的型号命中，其祖先分类/产品保留用于定位；无关的 active SKU 因不在命中链里被过滤
    expect(within(tree).getByTestId("tree-node-variant-20")).toBeInTheDocument();
    expect(within(tree).getByTestId("tree-node-category-1")).toBeInTheDocument();
  });

  it("显示后续版本说明，不伪造 AI 已识别", () => {
    render(<CatalogView />);
    expect(screen.getByTestId("catalog-future-notice")).toHaveTextContent("后续版本提供");
    expect(screen.queryByText(/AI 已识别/)).not.toBeInTheDocument();
  });

  it("Tab 与既有扁平产品视图共存", async () => {
    const user = userEvent.setup();
    render(<CatalogView />);
    expect(screen.getByTestId("tab-catalog")).toBeInTheDocument();
    await user.click(screen.getByTestId("tab-flat"));
    expect(screen.getByTestId("flat-products")).toBeInTheDocument();
    // 内嵌扁平产品视图仍用其自有搜索框（功能保留）
    expect(screen.getByTestId("product-search")).toBeInTheDocument();
  });

  it("点击新建打开创建向导", async () => {
    const user = userEvent.setup();
    render(<CatalogView />);
    await user.click(screen.getByTestId("open-create-wizard"));
    expect(screen.getByTestId("create-wizard")).toBeInTheDocument();
    expect(screen.getByTestId("wizard-step-category")).toBeInTheDocument();
  });

  it("超长中文名不破坏布局（truncate 类存在）", () => {
    const longName = "超".repeat(120);
    vi.mocked(hooks.useCatalogTree).mockReturnValue(
      query({
        data: [
          {
            level: "category",
            id: 1,
            code: "c",
            name_zh: longName,
            name_en: null,
            status: "active",
            children: [],
          },
        ],
      }),
    );
    render(<CatalogView />);
    const node = screen.getByTestId("tree-node-category-1");
    expect(node.querySelector(".truncate")).not.toBeNull();
  });
});
