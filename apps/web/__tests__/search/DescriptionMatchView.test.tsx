import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DescriptionMatchView } from "@/components/search/DescriptionMatchView";
import * as hooks from "@/lib/hooks";

import { makeMatchItem, makeMatchResponse, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useDescriptionMatch: vi.fn(),
  useProducts: vi.fn(),
  usePmSummary: vi.fn(),
  useAssetSearch: vi.fn(),
}));

function lastReq() {
  return vi.mocked(hooks.useDescriptionMatch).mock.calls.at(-1)?.[0];
}

function renderView(props: Partial<React.ComponentProps<typeof DescriptionMatchView>> = {}) {
  return render(<DescriptionMatchView onOpenItem={vi.fn()} onPreview={vi.fn()} {...props} />);
}

beforeEach(() => {
  vi.mocked(hooks.useDescriptionMatch).mockReturnValue(query());
  vi.mocked(hooks.useProducts).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.usePmSummary).mockReturnValue({ data: [], isLoading: false } as never);
  vi.mocked(hooks.useAssetSearch).mockReturnValue({ data: undefined, isLoading: false, isError: false, isFetching: false } as never);
});

describe("DescriptionMatchView", () => {
  it("初始空态，不发请求", () => {
    renderView();
    expect(lastReq()).toBeNull();
    expect(screen.getByText("输入画面描述开始匹配")).toBeInTheDocument();
  });

  it("输入描述并匹配 → 组装 target_description + limit + 开关", async () => {
    const user = userEvent.setup();
    renderView();
    await user.type(screen.getByTestId("desc-input"), "桌面充电演示");
    // 取消"包含需人工确认/风险镜头" → confirmed_only=true
    await user.click(screen.getByTestId("desc-include-risky"));
    await user.click(screen.getByTestId("desc-match"));
    expect(lastReq()).toMatchObject({
      target_description: "桌面充电演示",
      limit: 10,
      confirmed_only: true,
      allow_similar_scene: true,
      allow_similar_action: true,
    });
  });

  it("minimum_score 滑块写入请求", async () => {
    const user = userEvent.setup();
    renderView();
    await user.type(screen.getByTestId("desc-input"), "x");
    fireEvent.change(screen.getByTestId("desc-min-score"), { target: { value: "40" } });
    await user.click(screen.getByTestId("desc-match"));
    expect(lastReq()).toMatchObject({ minimum_score: 0.4 });
  });

  it("空描述时匹配按钮禁用，不发请求", async () => {
    renderView();
    expect(screen.getByTestId("desc-match")).toBeDisabled();
  });

  it("结果行展示推荐等级与需人工确认，并回显 minimum_score 与已显示计数", async () => {
    vi.mocked(hooks.useDescriptionMatch).mockReturnValue(
      query({
        data: makeMatchResponse(
          [makeMatchItem({ recommendation_level: "high", requires_human_confirmation: true })],
          { total: 3, minimum_score: 0.5 },
        ),
      }),
    );
    const user = userEvent.setup();
    renderView();
    await user.type(screen.getByTestId("desc-input"), "桌面充电");
    await user.click(screen.getByTestId("desc-match"));
    const row = screen.getByTestId("match-result-row");
    expect(within(row).getByText("强烈推荐")).toBeInTheDocument();
    expect(within(row).getByText("需人工确认")).toBeInTheDocument();
    expect(screen.getByTestId("desc-meta")).toHaveTextContent("≥ 50%");
    expect(screen.getByText(/已显示 1\/3 个候选镜头/)).toBeInTheDocument();
  });

  it("点击行标题回调 onOpenItem", async () => {
    const onOpenItem = vi.fn();
    vi.mocked(hooks.useDescriptionMatch).mockReturnValue(query({ data: makeMatchResponse([makeMatchItem()]) }));
    const user = userEvent.setup();
    renderView({ onOpenItem });
    await user.type(screen.getByTestId("desc-input"), "桌面充电");
    await user.click(screen.getByTestId("desc-match"));
    await user.click(within(screen.getByTestId("match-result-row")).getByTitle("示例扫地机 X10"));
    expect(onOpenItem).toHaveBeenCalledWith(expect.objectContaining({ shot_id: 101 }));
  });

  it("无达阈值结果给出降低阈值建议", async () => {
    vi.mocked(hooks.useDescriptionMatch).mockReturnValue(query({ data: makeMatchResponse([], { total: 0 }) }));
    const user = userEvent.setup();
    renderView();
    await user.type(screen.getByTestId("desc-input"), "找不到的画面");
    await user.click(screen.getByTestId("desc-match"));
    expect(screen.getByText("没有达到匹配阈值的镜头")).toBeInTheDocument();
  });

  it("匹配失败显示错误态", async () => {
    vi.mocked(hooks.useDescriptionMatch).mockReturnValue(query({ isError: true, error: new Error("match boom") }));
    const user = userEvent.setup();
    renderView();
    await user.type(screen.getByTestId("desc-input"), "x");
    await user.click(screen.getByTestId("desc-match"));
    expect(screen.getByTestId("error")).toBeInTheDocument();
    expect(screen.getByText("match boom")).toBeInTheDocument();
  });
});
