import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UnassignedWorkbench } from "@/components/product-media/UnassignedWorkbench";
import { api } from "@/lib/api";
import type { FamilyMediaSummary } from "@/lib/types";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const FAMILIES = [
  { family_id: 1, code: "FAM-A", name_zh: "产品甲", status: "active" },
  { family_id: 2, code: "FAM-B", name_zh: "产品乙", status: "active" },
] as unknown as FamilyMediaSummary[];

function unassignedPage(total: number, page: number, n: number) {
  return {
    kind: "image", total, page, page_size: 24,
    items: Array.from({ length: n }, (_, i) => ({
      type: "image", asset_id: (page - 1) * 24 + i + 1,
      filename: `img-${(page - 1) * 24 + i + 1}.png`, media_kind: "image",
      duration: null, status: "indexed",
    })),
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "pmUnassignedCounts").mockResolvedValue({
    image: 30, video: 117, shot: 5,
  } as never);
  vi.spyOn(api, "pmSuggestions").mockResolvedValue([] as never);
});

describe("UnassignedWorkbench 待归类工作台", () => {
  it("类型计数角标 + 翻页浏览全部未标注（真实事故回归：117 项只能看 24）", async () => {
    const list = vi
      .spyOn(api, "pmUnassigned")
      .mockImplementation(async (_k: string, page: number) =>
        unassignedPage(30, page, page === 1 ? 24 : 6) as never,
      );
    const user = userEvent.setup();
    wrap(<UnassignedWorkbench families={FAMILIES} />);
    await waitFor(() =>
      expect(screen.getByTestId("unassigned-total")).toHaveTextContent("共 30 项"),
    );
    // 计数角标（视频 117 可见即未标注全量对用户透明）
    expect(screen.getByTestId("unassigned-tab-video")).toHaveTextContent("117");
    // 翻页到第 2 页
    await user.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(list).toHaveBeenLastCalledWith("image", 2));
  });

  it("多选 + 搜索式选产品 + 绑定（成功后提示可撤销）", async () => {
    vi.spyOn(api, "pmUnassigned").mockResolvedValue(unassignedPage(3, 1, 3) as never);
    const bulk = vi.spyOn(api, "pmBulkLink").mockResolvedValue({
      completed: [{ link_id: 1 }, { link_id: 2 }], skipped: [], failed: [],
      operation_id: 9,
    } as never);
    const user = userEvent.setup();
    wrap(<UnassignedWorkbench families={FAMILIES} />);
    await waitFor(() => expect(screen.getByTestId("select-all-page")).toBeInTheDocument());
    await user.click(screen.getByTestId("select-all-page"));
    expect(screen.getByTestId("selected-count")).toHaveTextContent("已选 3 项");
    // 搜索式选择产品
    await user.type(screen.getByTestId("bulk-family"), "乙");
    await user.click(await screen.findByTestId("bulk-family-option-2"));
    expect(screen.getByTestId("bulk-family-picked")).toHaveTextContent("产品乙");
    await user.click(screen.getByTestId("bulk-assign"));
    await waitFor(() => expect(bulk).toHaveBeenCalled());
    const payload = bulk.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.family_id).toBe(2);
    expect((payload.items as unknown[]).length).toBe(3);
    await waitFor(() =>
      expect(screen.getByTestId("bulk-result")).toHaveTextContent("成功 2"),
    );
    expect(screen.getByTestId("bulk-result")).toHaveTextContent("撤销");
  });

  it("换页清空选择（避免看不见的已选被误绑定）", async () => {
    vi.spyOn(api, "pmUnassigned").mockImplementation(async (_k: string, page: number) =>
      unassignedPage(30, page, page === 1 ? 24 : 6) as never,
    );
    const user = userEvent.setup();
    wrap(<UnassignedWorkbench families={FAMILIES} />);
    await waitFor(() => expect(screen.getByTestId("select-all-page")).toBeInTheDocument());
    await user.click(screen.getByTestId("select-all-page"));
    expect(screen.getByTestId("selected-count")).toHaveTextContent("已选 24 项");
    await user.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() =>
      expect(screen.getByTestId("selected-count")).toHaveTextContent("已选 0 项"),
    );
  });

  it("视频/镜头类型显示继承说明", async () => {
    vi.spyOn(api, "pmUnassigned").mockResolvedValue(
      { ...unassignedPage(1, 1, 1), kind: "video" } as never,
    );
    const user = userEvent.setup();
    wrap(<UnassignedWorkbench families={FAMILIES} />);
    await user.click(screen.getByTestId("unassigned-tab-video"));
    await waitFor(() =>
      expect(screen.getByText(/镜头自动继承/)).toBeInTheDocument(),
    );
  });
});
