import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { SegmentList } from "@/components/script/SegmentList";
import * as hooks from "@/lib/hooks";

import { makeSegment, mutation } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useUpdateSegment: vi.fn(),
  useMatchSegment: vi.fn(),
  useReorderSegments: vi.fn(),
}));

const updateMut = mutation();
const matchMut = mutation();
const reorderMut = mutation();

const segs = [
  makeSegment({ id: 1, order_index: 0, segment_text: "段一", match_status: "matched" }),
  makeSegment({ id: 2, order_index: 1, segment_text: "段二", match_status: "pending", locked_shot_id: 55 }),
];

function renderList(props = {}) {
  return render(
    <SegmentList scriptId={1} segments={segs} products={[]} selectedSegmentId={1} onSelect={vi.fn()} {...props} />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  [updateMut, matchMut, reorderMut].forEach((m) => m.mutate.mockReset());
  vi.mocked(hooks.useUpdateSegment).mockReturnValue(updateMut);
  vi.mocked(hooks.useMatchSegment).mockReturnValue(matchMut);
  vi.mocked(hooks.useReorderSegments).mockReturnValue(reorderMut);
});

describe("SegmentList", () => {
  it("渲染段落、序号、匹配状态与锁定标识", () => {
    renderList();
    const rows = screen.getAllByTestId("segment-row");
    expect(within(rows[0]).getByText("1")).toBeInTheDocument();
    expect(within(rows[0]).getByText("已匹配")).toBeInTheDocument();
    expect(within(rows[1]).getByTestId("seg-locked")).toBeInTheDocument();
  });

  it("单段匹配 → onSelect + matchSegment", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    renderList({ onSelect });
    await user.click(within(screen.getAllByTestId("segment-row")[0]).getByTestId("seg-match"));
    expect(onSelect).toHaveBeenCalledWith(1);
    expect(matchMut.mutate).toHaveBeenCalledWith({ segmentId: 1 });
  });

  it("编辑保存 → updateSegment 带 lock_version", async () => {
    const user = userEvent.setup();
    renderList();
    await user.click(within(screen.getAllByTestId("segment-row")[0]).getByTestId("seg-edit"));
    await user.click(screen.getByTestId("seg-save"));
    expect(updateMut.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ segmentId: 1, req: expect.objectContaining({ lock_version: 0 }) }),
      expect.anything(),
    );
  });

  it("保存 409 → 冲突提示", async () => {
    updateMut.mutate.mockImplementation(
      (_v: unknown, opts?: { onError?: (e: unknown) => void }) => opts?.onError?.(new ApiError(409, "stale")),
    );
    const user = userEvent.setup();
    renderList();
    await user.click(within(screen.getAllByTestId("segment-row")[0]).getByTestId("seg-edit"));
    await user.click(screen.getByTestId("seg-save"));
    await waitFor(() => expect(screen.getByTestId("seg-conflict")).toBeInTheDocument());
  });

  it("下移段落 → reorderSegments 交换 id 顺序", async () => {
    const user = userEvent.setup();
    renderList();
    await user.click(within(screen.getAllByTestId("segment-row")[0]).getByLabelText("下移段落"));
    expect(reorderMut.mutate).toHaveBeenCalledWith([2, 1]);
  });
});
