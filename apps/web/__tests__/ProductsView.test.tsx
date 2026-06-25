import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProductsView } from "@/components/ProductsView";
import * as hooks from "@/lib/hooks";

vi.mock("@/lib/hooks", () => ({ useProducts: vi.fn() }));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function query(overrides: Record<string, any> = {}): any {
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

beforeEach(() => {
  vi.mocked(hooks.useProducts).mockReturnValue(query({ data: [] }));
});

describe("ProductsView", () => {
  it("空态提示录入产品", () => {
    render(<ProductsView />);
    expect(screen.getByTestId("empty")).toBeInTheDocument();
    expect(screen.getByText("产品库为空")).toBeInTheDocument();
  });

  it("加载态显示骨架", () => {
    vi.mocked(hooks.useProducts).mockReturnValue(query({ isLoading: true }));
    render(<ProductsView />);
    expect(screen.getByTestId("loading")).toBeInTheDocument();
  });

  it("渲染产品表格", () => {
    vi.mocked(hooks.useProducts).mockReturnValue(
      query({
        data: [
          {
            id: 1, brand: "小米", name: "扫地机器人", model: "X10", sku: "SKU-1",
            selling_points: ["大吸力", "自清洁"], status: "active", created_at: "", updated_at: "",
          },
        ],
      }),
    );
    render(<ProductsView />);
    expect(screen.getByTestId("product-table")).toBeInTheDocument();
    expect(screen.getAllByTestId("product-row")).toHaveLength(1);
    expect(screen.getByText("扫地机器人")).toBeInTheDocument();
    expect(screen.getByText("大吸力")).toBeInTheDocument();
  });

  it("搜索框输入更新值", async () => {
    const user = userEvent.setup();
    render(<ProductsView />);
    const input = screen.getByTestId("product-search");
    await user.type(input, "小米");
    expect(input).toHaveValue("小米");
  });
});
