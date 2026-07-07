import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UsageReviewView } from "@/components/usage-review/UsageReviewView";
import { AssetUsagePanel } from "@/components/usage-review/AssetUsagePanel";
import * as hooks from "@/lib/hooks";

import {
  makeDetail,
  makeLegacyItem,
  makeReviewItem,
  makeSummary,
  mutation,
  query,
} from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useUsageReviewSummary: vi.fn(),
  useUsageReviewItems: vi.fn(),
  useUsageReviewItemDetail: vi.fn(),
  useUsageReviewBulk: vi.fn(),
  useAssetUsageSummary: vi.fn(),
  useFinalVideos: vi.fn(),
  useAnalysisGenerations: vi.fn(),
  useShotsByGeneration: vi.fn(),
  useCreateUsage: vi.fn(),
  // P2b 成片登记 Tab（FinalVideosPanel）依赖
  useAssets: vi.fn(),
  useCreateFinalVideo: vi.fn(),
  useProjects: vi.fn(),
}));

const bulkMut = mutation();
const createUsageMut = mutation();

function listData(items: ReturnType<typeof makeReviewItem>[], total = items.length) {
  return query({ data: { items, total, page: 1, page_size: 20 } });
}

beforeEach(() => {
  vi.clearAllMocks();
  bulkMut.mutate.mockReset();
  createUsageMut.mutate.mockReset();
  vi.mocked(hooks.useUsageReviewSummary).mockReturnValue(query({ data: makeSummary() }));
  vi.mocked(hooks.useUsageReviewItems).mockReturnValue(
    listData([makeReviewItem(), makeLegacyItem()]),
  );
  vi.mocked(hooks.useUsageReviewItemDetail).mockReturnValue(query({ data: makeDetail() }));
  vi.mocked(hooks.useUsageReviewBulk).mockReturnValue(bulkMut);
  vi.mocked(hooks.useFinalVideos).mockReturnValue(
    query({ data: { items: [{ id: 1, title: "六月投放成片" }], total: 1 } }),
  );
  vi.mocked(hooks.useAnalysisGenerations).mockReturnValue(
    query({ data: { asset_id: 10, current_generation: 1, items: [{ generation: 1 }] } }),
  );
  vi.mocked(hooks.useShotsByGeneration).mockReturnValue(
    query({
      data: {
        items: [
          { id: 201, sequence_no: 1, start_time: 0, end_time: 2 },
          { id: 202, sequence_no: 2, start_time: 2, end_time: 4 },
        ],
        total: 2,
      },
    }),
  );
  vi.mocked(hooks.useCreateUsage).mockReturnValue(createUsageMut);
  vi.mocked(hooks.useAssets).mockReturnValue(
    query({ data: { items: [], total: 0, page: 1, page_size: 20 } }),
  );
  vi.mocked(hooks.useCreateFinalVideo).mockReturnValue(mutation());
  vi.mocked(hooks.useProjects).mockReturnValue(
    query({ data: { items: [], total: 0, page: 1, page_size: 100 } }),
  );
});

describe("UsageReviewView 固定提示与总览", () => {
  it("固定双提示始终可见", () => {
    render(<UsageReviewView />);
    expect(screen.getByTestId("formal-count-notice")).toHaveTextContent(
      "正式使用次数只来自已确认的成片与镜头血缘。",
    );
    expect(screen.getByTestId("legacy-meaning-notice")).toHaveTextContent(
      "历史路径证据仅表示“可能曾使用，次数和成片未知”。",
    );
  });

  it("总览卡片分离展示，绝无混合总使用次数", async () => {
    const user = userEvent.setup();
    render(<UsageReviewView />);
    await user.click(screen.getByTestId("tab-overview"));
    expect(screen.getByTestId("card-confirmed")).toHaveTextContent("2");
    expect(screen.getByTestId("card-proposed")).toHaveTextContent("4"); // 3+1 suspected
    expect(screen.getByTestId("card-legacy-pending")).toHaveTextContent("4");
    expect(screen.getByTestId("card-legacy-accepted")).toHaveTextContent("2");
    expect(screen.getByTestId("card-needs-review")).toHaveTextContent("8");
    // 绝不出现 confirmed(2)+accepted(2)=4 的"总使用次数"
    expect(screen.queryByText(/总使用次数/)).toBeNull();
  });

  it("P2b 成片登记 Tab 内嵌成片工作台（登记入口与空态）", async () => {
    const user = userEvent.setup();
    vi.mocked(hooks.useFinalVideos).mockReturnValue(
      query({ data: { items: [], total: 0, page: 1, page_size: 20 } }),
    );
    render(<UsageReviewView />);
    await user.click(screen.getByTestId("tab-final-videos"));
    expect(screen.getByTestId("final-videos-panel")).toBeInTheDocument();
    expect(screen.getByTestId("toggle-create-final-video")).toBeInTheDocument();
    expect(screen.getByText("还没有成片记录")).toBeInTheDocument();
  });
});

describe("UsageReviewView 待审核列表", () => {
  it("默认待审核 Tab；两类记录并列且类型标签明显不同", () => {
    render(<UsageReviewView />);
    const formal = screen.getByTestId("review-row-final_video_usage-11");
    const legacy = screen.getByTestId("review-row-legacy_usage_evidence-21");
    expect(formal).toHaveTextContent("正式血缘候选");
    expect(formal).toHaveTextContent("项目候选");
    expect(legacy).toHaveTextContent("历史弱证据");
    expect(legacy).toHaveTextContent("历史证据·待审");
  });

  it("legacy 行 Shot 与成片为空占位（不造假对象）", () => {
    render(<UsageReviewView />);
    const legacy = screen.getByTestId("review-row-legacy_usage_evidence-21");
    const cells = legacy.querySelectorAll("td");
    // 镜头列与成片列均为 —
    expect(legacy.textContent).toContain("—");
    expect(cells.length).toBeGreaterThan(5);
  });

  it("混合类型选择时批量禁用并说明原因", async () => {
    const user = userEvent.setup();
    render(<UsageReviewView />);
    await user.click(screen.getByTestId("select-final_video_usage-11"));
    await user.click(screen.getByTestId("select-legacy_usage_evidence-21"));
    expect(screen.getByTestId("mixed-type-warning")).toHaveTextContent(
      "请分开批量处理",
    );
    expect(screen.queryByTestId("bulk-confirm")).toBeNull();
  });

  it("同类型选择出现批量按钮，经二次确认后携带显式 items 调用", async () => {
    const user = userEvent.setup();
    render(<UsageReviewView />);
    await user.click(screen.getByTestId("select-final_video_usage-11"));
    await user.click(screen.getByTestId("bulk-confirm"));
    // 二次确认对话框
    await user.click(screen.getByRole("button", { name: "确认执行" }));
    expect(bulkMut.mutate).toHaveBeenCalledWith(
      {
        items: [{ item_type: "final_video_usage", item_id: 11 }],
        action: "confirm",
      },
      expect.anything(),
    );
  });

  it("批量结果展示成功/跳过/失败", async () => {
    const user = userEvent.setup();
    bulkMut.mutate.mockImplementation(
      (_p: unknown, opts?: { onSuccess?: (r: unknown) => void }) =>
        opts?.onSuccess?.({ succeeded: 1, skipped: 1, failed: 0, results: [] }),
    );
    render(<UsageReviewView />);
    await user.click(screen.getByTestId("select-final_video_usage-11"));
    await user.click(screen.getByTestId("bulk-confirm"));
    await user.click(screen.getByRole("button", { name: "确认执行" }));
    expect(screen.getByTestId("bulk-result")).toHaveTextContent("成功 1，跳过 1，失败 0");
  });

  it("legacy 行提供「建立正式成片血缘」入口", () => {
    render(<UsageReviewView />);
    expect(screen.getByTestId("clue-21")).toBeInTheDocument();
    // formal 行没有该入口
    expect(
      screen.getByTestId("review-row-final_video_usage-11").textContent,
    ).not.toContain("建立正式成片血缘");
  });

  it("空态", () => {
    vi.mocked(hooks.useUsageReviewItems).mockReturnValue(listData([]));
    render(<UsageReviewView />);
    expect(screen.getByTestId("empty")).toBeInTheDocument();
  });

  it("长名称正常渲染", () => {
    const long = "很长的成片标题".repeat(20);
    vi.mocked(hooks.useUsageReviewItems).mockReturnValue(
      listData([makeReviewItem({ final_video_title: long })]),
    );
    render(<UsageReviewView />);
    expect(screen.getByTestId("review-row-final_video_usage-11")).toHaveTextContent(
      "很长的成片标题",
    );
  });
});

describe("ClueLineageDialog 补录流程", () => {
  it("不默认选择 Shot 与成片；选齐前提交禁用；成功后提示需再次确认", async () => {
    const user = userEvent.setup();
    render(<UsageReviewView />);
    await user.click(screen.getByTestId("clue-21"));
    const submit = screen.getByTestId("clue-submit");
    expect(submit).toBeDisabled(); // 未选任何目标
    await user.click(screen.getByTestId("clue-fv-option-1"));
    expect(submit).toBeDisabled(); // 仍未选 Shot（绝不默认选第一个）
    await user.click(screen.getByTestId("clue-shot-202"));
    expect(submit).toBeEnabled();

    createUsageMut.mutate.mockImplementation(
      (_p: unknown, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.(),
    );
    await user.click(submit);
    expect(createUsageMut.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ source_shot_id: 202 }),
      expect.anything(),
    );
    // 创建的是 proposed——明确提示尚未计入正式次数、需再次确认
    expect(screen.getByTestId("clue-created")).toHaveTextContent("尚未计入正式使用次数");
  });

  it("已有关系冲突（409）时显示已有关系提示", async () => {
    const user = userEvent.setup();
    const { ApiError } = await import("@/lib/api");
    vi.mocked(hooks.useCreateUsage).mockReturnValue(
      mutation({ isError: true, error: new ApiError(409, "该成片已引用该镜头") }),
    );
    render(<UsageReviewView />);
    await user.click(screen.getByTestId("clue-21"));
    expect(screen.getByTestId("clue-error")).toHaveTextContent("已存在使用关系");
  });
});

describe("详情抽屉", () => {
  it("legacy 详情：无 Shot/成片说明 + 事件时间线", async () => {
    const user = userEvent.setup();
    render(<UsageReviewView />);
    await user.click(screen.getByTestId("detail-legacy_usage_evidence-21"));
    expect(screen.getByTestId("detail-shot")).toHaveTextContent("历史证据无法定位镜头");
    expect(screen.getByTestId("detail-final-video")).toHaveTextContent(
      "历史证据无法定位成片",
    );
    const events = screen.getByTestId("detail-events");
    expect(events).toHaveTextContent("首次检测");
    expect(events).toHaveTextContent("再次观察");
  });
});

describe("AssetUsagePanel 集成", () => {
  it("并列摘要；历史上用过（次数未知）不显示数字", () => {
    vi.mocked(hooks.useAssetUsageSummary).mockReturnValue(
      query({
        data: {
          asset_id: 10,
          confirmed_usage_count: 2,
          pending_legacy_evidence_count: 1,
          conflict_legacy_evidence_count: 0,
          legacy_usage_state: "legacy_used_unknown",
        },
      }),
    );
    vi.mocked(hooks.useUsageReviewItems).mockReturnValue(listData([], 3));
    render(<AssetUsagePanel assetId={10} />);
    expect(screen.getByTestId("usage-formal-confirmed")).toHaveTextContent("2");
    expect(screen.getByTestId("usage-formal-proposed")).toHaveTextContent("3");
    expect(screen.getByTestId("usage-legacy-pending")).toHaveTextContent("1");
    const unknown = screen.getByTestId("usage-legacy-unknown");
    expect(unknown).toHaveTextContent("历史上用过（次数未知）");
    expect(unknown.textContent).not.toMatch(/\d/); // 绝不带数字次数
  });
});
