import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { CandidatePanel } from "@/components/script/CandidatePanel";
import * as hooks from "@/lib/hooks";

import { makeCandidate, makeCandidatesResponse, makeSegment, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useSegmentCandidates: vi.fn(),
  useMatchSegment: vi.fn(),
  useSelectCandidate: vi.fn(),
  useLockCandidate: vi.fn(),
  useUnlockSegment: vi.fn(),
}));

const matchMut = mutation();
const selectMut = mutation();
const lockMut = mutation();
const unlockMut = mutation();

function setup(candidatesOverride = {}) {
  vi.mocked(hooks.useSegmentCandidates).mockReturnValue(
    query({ data: makeCandidatesResponse(candidatesOverride) }),
  );
  vi.mocked(hooks.useMatchSegment).mockReturnValue(matchMut);
  vi.mocked(hooks.useSelectCandidate).mockReturnValue(selectMut);
  vi.mocked(hooks.useLockCandidate).mockReturnValue(lockMut);
  vi.mocked(hooks.useUnlockSegment).mockReturnValue(unlockMut);
}

function renderPanel() {
  return render(
    <CandidatePanel scriptId={1} segment={makeSegment()} segmentIndex={0} onPreview={vi.fn()} />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  matchMut.mutate.mockReset();
  selectMut.mutate.mockReset();
  lockMut.mutate.mockReset();
  unlockMut.mutate.mockReset();
});

describe("CandidatePanel", () => {
  it("无选中段落显示提示", () => {
    setup();
    render(<CandidatePanel scriptId={1} segment={null} segmentIndex={null} onPreview={vi.fn()} />);
    expect(screen.getByText("选择左侧段落")).toBeInTheDocument();
  });

  it("渲染候选卡，rank0 标系统推荐", () => {
    setup();
    renderPanel();
    const cards = screen.getAllByTestId("candidate-card");
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByText("系统推荐")).toBeInTheDocument();
    expect(cards[0]).toHaveAttribute("data-state", "recommended");
  });

  it("选择 → 带 lock_version 调 select；不自动锁定", async () => {
    setup({ lock_version: 3 });
    const user = userEvent.setup();
    renderPanel();
    await user.click(within(screen.getAllByTestId("candidate-card")[0]).getByTestId("candidate-select"));
    expect(selectMut.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ segmentId: 1, req: { shot_id: 101, lock_version: 3 } }),
      expect.anything(),
    );
    expect(lockMut.mutate).not.toHaveBeenCalled();
  });

  it("锁定（无既有锁）force=false；已选中标识", async () => {
    setup({ selected_shot_id: 101 });
    const user = userEvent.setup();
    renderPanel();
    const first = screen.getAllByTestId("candidate-card")[0];
    expect(first).toHaveAttribute("data-state", "selected");
    await user.click(within(screen.getAllByTestId("candidate-card")[1]).getByTestId("candidate-lock"));
    expect(lockMut.mutate.mock.calls[0][0].req).toMatchObject({ shot_id: 102, force: false });
  });

  it("已锁定其它镜头 → 其余卡显示替换锁定且 force=true", async () => {
    setup({ locked_shot_id: 999 });
    const user = userEvent.setup();
    renderPanel();
    const lockBtn = within(screen.getAllByTestId("candidate-card")[0]).getByTestId("candidate-lock");
    expect(lockBtn).toHaveTextContent("替换锁定");
    await user.click(lockBtn);
    expect(lockMut.mutate.mock.calls[0][0].req).toMatchObject({ shot_id: 101, force: true });
  });

  it("已锁定 → 显示锁定横幅与解锁", async () => {
    setup({ locked_shot_id: 101 });
    const user = userEvent.setup();
    renderPanel();
    expect(screen.getByTestId("locked-banner")).toHaveTextContent("#101");
    await user.click(screen.getByTestId("unlock-btn"));
    expect(unlockMut.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ segmentId: 1, lockVersion: 0 }),
    );
  });

  it("缺口 → 展示 gap_reasons 与补拍建议，不渲染候选", () => {
    setup({
      match_status: "gap",
      candidate_count: 0,
      candidates: [],
      gap_reasons: ["无符合产品硬约束的镜头：吹风机"],
      reshoot_recommendation: ["补拍产品「吹风机」的特写"],
      requires_human_confirmation: true,
    });
    renderPanel();
    expect(screen.getByTestId("gap-notice")).toHaveTextContent("吹风机");
    expect(screen.getByTestId("reshoot")).toHaveTextContent("补拍产品「吹风机」的特写");
    expect(screen.queryByTestId("candidate-card")).not.toBeInTheDocument();
  });

  it("详情抽屉显示分项分，null 通道显示未参与（不当 0）", async () => {
    setup({ candidates: [makeCandidate({ product_score: null, semantic_score: 0.8 })] });
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTitle("查看候选详情与分项得分"));
    const drawer = screen.getByTestId("candidate-drawer");
    const productRow = within(drawer).getByText("产品").closest("div")!;
    expect(within(productRow).getByText("未参与")).toBeInTheDocument();
  });

  it("select 返回 409 → 冲突提示", async () => {
    setup({ lock_version: 1 });
    selectMut.mutate.mockImplementation(
      (_vars: unknown, opts?: { onError?: (e: unknown) => void }) => opts?.onError?.(new ApiError(409, "conflict")),
    );
    const user = userEvent.setup();
    renderPanel();
    await user.click(within(screen.getAllByTestId("candidate-card")[0]).getByTestId("candidate-select"));
    await waitFor(() => expect(screen.getByTestId("pick-conflict")).toBeInTheDocument());
  });

  it("多代次 → 切到历史代次显示只读提示且选择被拦截", async () => {
    setup({ current_generation: 2 });
    const user = userEvent.setup();
    renderPanel();
    await user.click(within(screen.getByTestId("gen-switcher")).getByText("1"));
    expect(screen.getByTestId("history-note")).toBeInTheDocument();
    selectMut.mutate.mockClear();
    await user.click(within(screen.getAllByTestId("candidate-card")[0]).getByTestId("candidate-select"));
    expect(selectMut.mutate).not.toHaveBeenCalled();
  });
});
