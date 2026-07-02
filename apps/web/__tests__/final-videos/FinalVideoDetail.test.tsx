import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinalVideoDetail } from "@/components/final-videos/FinalVideoDetail";
import { UsageCountBadge } from "@/components/final-videos/UsageCountBadge";
import * as hooks from "@/lib/hooks";

import { makeFinalVideo, makeLineage, makeUsage, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useFinalVideoLineage: vi.fn(),
  useFinalVideoLifecycle: vi.fn(),
  useProposeFromProject: vi.fn(),
  useUsageAction: vi.fn(),
  useCreateUsage: vi.fn(),
  useOccurrenceMutation: vi.fn(),
  useUsageEvents: vi.fn(),
  useAssets: vi.fn(),
  useShots: vi.fn(),
}));

const actionMut = mutation({ mutateAsync: vi.fn(() => Promise.resolve()) });
const proposeMut = mutation();
const lifecycleMut = mutation();
const createUsageMut = mutation();
const occMut = mutation();

beforeEach(() => {
  vi.clearAllMocks();
  actionMut.mutate.mockReset();
  actionMut.mutateAsync.mockReset();
  actionMut.mutateAsync.mockImplementation(() => Promise.resolve());
  vi.mocked(hooks.useFinalVideoLineage).mockReturnValue(query({ data: makeLineage() }));
  vi.mocked(hooks.useFinalVideoLifecycle).mockReturnValue(lifecycleMut);
  vi.mocked(hooks.useProposeFromProject).mockReturnValue(proposeMut);
  vi.mocked(hooks.useUsageAction).mockReturnValue(actionMut);
  vi.mocked(hooks.useCreateUsage).mockReturnValue(createUsageMut);
  vi.mocked(hooks.useOccurrenceMutation).mockReturnValue(occMut);
  vi.mocked(hooks.useUsageEvents).mockReturnValue(query({ data: { items: [] } }));
  vi.mocked(hooks.useAssets).mockReturnValue(query({ data: { items: [], total: 0 } }));
  vi.mocked(hooks.useShots).mockReturnValue(query({ data: { items: [], total: 0 } }));
});

describe("FinalVideoDetail", () => {
  it("渲染成片信息与血缘行", () => {
    render(<FinalVideoDetail finalVideoId={1} />);
    expect(screen.getByTestId("fv-title")).toHaveTextContent("产品宣传片 6 月投放版");
    const row = screen.getByTestId("usage-row");
    expect(row).toHaveTextContent("镜头 #3");
    expect(row).toHaveTextContent("raw_a.mp4");
    expect(row).toHaveTextContent("候选待确认");
    expect(row).toHaveTextContent("人工添加");
  });

  it("proposed 行显示确认/驳回；不显示为正式使用", () => {
    render(<FinalVideoDetail finalVideoId={1} />);
    expect(screen.getByTestId("usage-confirm-11")).toBeInTheDocument();
    expect(screen.getByTestId("usage-reject-11")).toBeInTheDocument();
    expect(screen.queryByText("已确认使用")).not.toBeInTheDocument();
  });

  it("确认按钮触发 confirm 动作", async () => {
    const user = userEvent.setup();
    render(<FinalVideoDetail finalVideoId={1} />);
    await user.click(screen.getByTestId("usage-confirm-11"));
    expect(actionMut.mutate).toHaveBeenCalledWith(
      { usageId: 11, action: "confirm" },
      expect.anything(),
    );
  });

  it("confirmed 行只提供撤销", () => {
    vi.mocked(hooks.useFinalVideoLineage).mockReturnValue(
      query({
        data: makeLineage({
          usages: [makeUsage({ status: "confirmed", confirmed_at: "2026-07-01T02:00:00Z" })],
        }),
      }),
    );
    render(<FinalVideoDetail finalVideoId={1} />);
    expect(screen.getByTestId("usage-revoke-11")).toBeInTheDocument();
    expect(screen.queryByTestId("usage-confirm-11")).not.toBeInTheDocument();
    expect(screen.getByTestId("usage-row")).toHaveTextContent("已确认使用");
  });

  it("rejected/revoked 行提供恢复候选", () => {
    vi.mocked(hooks.useFinalVideoLineage).mockReturnValue(
      query({ data: makeLineage({ usages: [makeUsage({ status: "revoked" })] }) }),
    );
    render(<FinalVideoDetail finalVideoId={1} />);
    expect(screen.getByTestId("usage-restore-11")).toBeInTheDocument();
  });

  it("批量确认仅对选中的 proposed 生效", async () => {
    const user = userEvent.setup();
    vi.mocked(hooks.useFinalVideoLineage).mockReturnValue(
      query({
        data: makeLineage({
          usages: [
            makeUsage({ id: 11, source_shot_id: 201 }),
            makeUsage({ id: 12, source_shot_id: 202, shot: null }),
            makeUsage({ id: 13, source_shot_id: 203, status: "confirmed", shot: null }),
          ],
        }),
      }),
    );
    render(<FinalVideoDetail finalVideoId={1} />);
    const batchBtn = screen.getByTestId("fv-batch-confirm");
    expect(batchBtn).toBeDisabled();
    await user.click(screen.getByTestId("usage-select-11"));
    await user.click(screen.getByTestId("usage-select-12"));
    await user.click(screen.getByTestId("usage-select-13")); // confirmed，不参与批量确认
    expect(batchBtn).toHaveTextContent("批量确认（2）");
    await user.click(batchBtn);
    expect(actionMut.mutateAsync).toHaveBeenCalledTimes(2);
    expect(actionMut.mutateAsync).toHaveBeenCalledWith({ usageId: 11, action: "confirm" });
    expect(actionMut.mutateAsync).toHaveBeenCalledWith({ usageId: 12, action: "confirm" });
  });

  it("展开显示 occurrence 与事件；多段出现不改变确认计数展示", async () => {
    const user = userEvent.setup();
    vi.mocked(hooks.useFinalVideoLineage).mockReturnValue(
      query({
        data: makeLineage({
          final_video: makeFinalVideo({
            usage_stats: {
              source_shot_count: 1,
              confirmed_count: 1,
              proposed_count: 0,
              suspected_count: 0,
              rejected_count: 0,
              revoked_count: 0,
            },
          }),
          usages: [
            makeUsage({
              status: "confirmed",
              occurrence_count: 2,
              occurrences: [
                {
                  id: 31,
                  usage_id: 11,
                  occurrence_index: 0,
                  source_start_ms: 4000,
                  source_end_ms: 6000,
                  final_start_ms: 0,
                  final_end_ms: 2000,
                  created_at: "2026-07-01T00:00:00Z",
                  updated_at: "2026-07-01T00:00:00Z",
                },
                {
                  id: 32,
                  usage_id: 11,
                  occurrence_index: 1,
                  source_start_ms: 7000,
                  source_end_ms: 9000,
                  final_start_ms: 30000,
                  final_end_ms: 32000,
                  created_at: "2026-07-01T00:00:00Z",
                  updated_at: "2026-07-01T00:00:00Z",
                },
              ],
            }),
          ],
        }),
      }),
    );
    vi.mocked(hooks.useUsageEvents).mockReturnValue(
      query({
        data: {
          items: [
            {
              id: 1,
              usage_id: 11,
              action: "manual_add",
              before_status: null,
              after_status: "proposed",
              actor_label: "小袁",
              note: null,
              created_at: "2026-07-01T00:00:00Z",
            },
            {
              id: 2,
              usage_id: 11,
              action: "confirm",
              before_status: "proposed",
              after_status: "confirmed",
              actor_label: null,
              note: null,
              created_at: "2026-07-01T01:00:00Z",
            },
          ],
        },
      }),
    );
    render(<FinalVideoDetail finalVideoId={1} />);
    // 统计条：2 个 occurrence 仍只算 1 条已确认
    expect(screen.getByTestId("fv-usage-stats")).toHaveTextContent("已确认 1");
    await user.click(screen.getByTestId("usage-occ-toggle-11"));
    const occRows = screen.getAllByTestId(/occ-row-/);
    expect(occRows).toHaveLength(2);
    const events = screen.getByTestId("usage-events-11");
    expect(within(events).getByText("人工添加")).toBeInTheDocument();
    expect(within(events).getByText("确认使用")).toBeInTheDocument();
  });

  it("归档成片：操作按钮禁用", () => {
    vi.mocked(hooks.useFinalVideoLineage).mockReturnValue(
      query({
        data: makeLineage({
          final_video: makeFinalVideo({ status: "archived", archived_at: "2026-07-01T03:00:00Z" }),
        }),
      }),
    );
    render(<FinalVideoDetail finalVideoId={1} />);
    expect(screen.getByTestId("fv-add-shot")).toBeDisabled();
    expect(screen.getByTestId("fv-propose")).toBeDisabled();
    expect(screen.getByTestId("usage-confirm-11")).toBeDisabled();
    expect(screen.getByTestId("fv-restore")).toBeInTheDocument();
  });

  it("从项目生成候选：展示统计结果", async () => {
    const user = userEvent.setup();
    proposeMut.mutate.mockImplementation((_: unknown, opts: { onSuccess: (r: unknown) => void }) =>
      opts.onSuccess({
        created: 2,
        existing: 1,
        skipped_unavailable: 0,
        conflicts: 0,
        segments_scanned: 3,
        created_usage_ids: [21, 22],
      }),
    );
    render(<FinalVideoDetail finalVideoId={1} />);
    await user.click(screen.getByTestId("fv-propose"));
    const result = screen.getByTestId("propose-result");
    expect(result).toHaveTextContent("新增 2");
    expect(result).toHaveTextContent("已存在 1");
  });

  it("动作 409 冲突展示错误", async () => {
    const user = userEvent.setup();
    actionMut.mutate.mockImplementation(
      (_: unknown, opts: { onError: (e: Error) => void }) =>
        opts.onError(new Error("已驳回/已撤销的引用须先恢复为 proposed 再确认")),
    );
    render(<FinalVideoDetail finalVideoId={1} />);
    await user.click(screen.getByTestId("usage-confirm-11"));
    expect(screen.getByTestId("usage-action-error")).toBeInTheDocument();
  });

  it("空血缘显示空态", () => {
    vi.mocked(hooks.useFinalVideoLineage).mockReturnValue(
      query({ data: makeLineage({ usages: [] }) }),
    );
    render(<FinalVideoDetail finalVideoId={1} />);
    expect(screen.getByTestId("empty")).toBeInTheDocument();
  });
});

describe("UsageCountBadge", () => {
  it("confirmed>0 显示使用次数", () => {
    render(
      <UsageCountBadge count={{ shot_id: 1, confirmed_usage_count: 3, proposed_count: 1 }} />,
    );
    expect(screen.getByTestId("usage-count-badge")).toHaveTextContent("使用 3 次");
  });

  it("仅候选时显示候选标记，不显示为正式使用", () => {
    render(
      <UsageCountBadge count={{ shot_id: 1, confirmed_usage_count: 0, proposed_count: 2 }} />,
    );
    const badge = screen.getByTestId("usage-count-badge");
    expect(badge).toHaveTextContent("候选 2");
    expect(badge).not.toHaveTextContent("使用");
  });

  it("无任何引用时不渲染", () => {
    render(
      <UsageCountBadge count={{ shot_id: 1, confirmed_usage_count: 0, proposed_count: 0 }} />,
    );
    expect(screen.queryByTestId("usage-count-badge")).not.toBeInTheDocument();
  });
});
