import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardView } from "@/components/dashboard/DashboardView";
import * as hooks from "@/lib/hooks";

import { query } from "../search/fixtures";

vi.mock("@/lib/hooks", () => ({
  useProcessingOverview: vi.fn(),
  usePmSummary: vi.fn(),
  usePmUnassigned: vi.fn(),
  useUsageReviewSummary: vi.fn(),
}));

function makeOverview() {
  return {
    scan: { queued: 0, running: 0 },
    shots: { queued: 1, running: 1 },
    ai: { queued: 0, running: 1 },
    totals: {
      videos_total: 342,
      videos_with_shots: 331,
      shots_ready: 1888,
      shots_ai_labeled: 1500,
      images_total: 81,
      searchable_docs: 407,
    },
    config: {
      auto_analyze_on_scan: true,
      auto_ai_after_shots: true,
      scan_interval_minutes: 30,
      ai_daily_budget: 0,
      ai_spent_today: 0,
    },
  };
}

function makeFamily(over: Record<string, unknown> = {}) {
  return {
    family_id: 1,
    code: "FAM-1",
    name_zh: "示例产品",
    status: "active",
    onboarding_status: null,
    variant_count: 1,
    reference_count: 2,
    image_count: 10,
    video_count: 5,
    shot_link_count: 3,
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hooks.useProcessingOverview).mockReturnValue(query({ data: makeOverview() }));
  vi.mocked(hooks.usePmSummary).mockReturnValue(
    query({
      data: [
        makeFamily(),
        makeFamily({ family_id: 2, image_count: 0, video_count: 0, shot_link_count: 0 }),
      ],
    }),
  );
  vi.mocked(hooks.usePmUnassigned).mockReturnValue(
    query({ data: { kind: "image", total: 7, page: 1, page_size: 1, items: [] } }),
  );
  vi.mocked(hooks.useUsageReviewSummary).mockReturnValue(
    query({
      data: {
        formal: { confirmed: 2, proposed: 3, suspected: 1, rejected: 0, revoked: 0 },
        legacy: { pending: 4, accepted: 2, rejected: 0, conflict: 0 },
        needs_review_total: 8,
      },
    }),
  );
});

describe("DashboardView 运营仪表盘", () => {
  it("三大区块渲染真实 API 数字", () => {
    render(<DashboardView />);
    // 处理管线
    expect(screen.getByTestId("dash-videos-total")).toHaveTextContent("342");
    expect(screen.getByTestId("dash-active-jobs")).toHaveTextContent("3 个任务处理中");
    // 产品覆盖：2 个产品，1 个有素材
    expect(screen.getByTestId("dash-family-count")).toHaveTextContent("2");
    // 使用记录待办
    expect(screen.getByTestId("dash-needs-review")).toHaveTextContent("8");
  });

  it("未归类素材显示直达链接（image+video 两次调用合计）", () => {
    render(<DashboardView />);
    // usePmUnassigned 被 image/video 各调一次，桩统一返回 total=7 → 合计 14
    expect(screen.getByTestId("dash-unassigned")).toHaveTextContent("还有 14 条素材未归类到产品");
  });

  it("快捷入口含 6 个主工作台", () => {
    render(<DashboardView />);
    const links = screen.getByTestId("dash-quick-links");
    for (const label of ["素材库", "搜索", "镜头库", "产品", "项目", "使用记录"]) {
      expect(links).toHaveTextContent(label);
    }
  });

  it("单区块接口失败独立降级，不影响其他区块", () => {
    vi.mocked(hooks.usePmSummary).mockReturnValue(query({ isError: true, error: new Error("x") }));
    render(<DashboardView />);
    expect(screen.getByText("产品覆盖统计暂不可用")).toBeInTheDocument();
    // 其他区块仍正常
    expect(screen.getByTestId("dash-videos-total")).toHaveTextContent("342");
    expect(screen.getByTestId("dash-needs-review")).toHaveTextContent("8");
  });

  it("管线空闲态与全部归类态", () => {
    const idle = makeOverview();
    idle.shots = { queued: 0, running: 0 };
    idle.ai = { queued: 0, running: 0 };
    vi.mocked(hooks.useProcessingOverview).mockReturnValue(query({ data: idle }));
    vi.mocked(hooks.usePmUnassigned).mockReturnValue(
      query({ data: { kind: "image", total: 0, page: 1, page_size: 1, items: [] } }),
    );
    render(<DashboardView />);
    expect(screen.getByTestId("dash-active-jobs")).toHaveTextContent("管线空闲");
    expect(screen.getByTestId("dash-unassigned")).toHaveTextContent("素材已全部归类到产品");
  });
});
