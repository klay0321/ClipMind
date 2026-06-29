import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditListTab } from "@/components/script/EditListTab";
import * as hooks from "@/lib/hooks";

import { makeEditList, makeEditRow, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useScriptEditList: vi.fn(),
  useCreateScriptCsvExport: vi.fn(),
  useScriptExportStatus: vi.fn(),
  // PR-06B：ScriptMultiExportPanel 依赖
  useCreateScriptExport: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hooks.useCreateScriptCsvExport).mockReturnValue(mutation());
  vi.mocked(hooks.useScriptExportStatus).mockReturnValue(query());
  vi.mocked(hooks.useCreateScriptExport).mockReturnValue(mutation());
});

function renderTab(rows = [makeEditRow()]) {
  vi.mocked(hooks.useScriptEditList).mockReturnValue(query({ data: makeEditList(rows) }));
  return render(<EditListTab scriptId={1} active onPreview={vi.fn()} />);
}

describe("EditListTab", () => {
  it("展示摘要统计", () => {
    renderTab([makeEditRow(), makeEditRow({ segment_id: 2, segment_order: 2, match_status: "gap", shot_id: null, selection_status: "none" })]);
    const summary = screen.getByTestId("editlist-summary");
    expect(summary).toHaveTextContent("段落总数 2");
    expect(summary).toHaveTextContent("缺口 1");
  });

  it("推荐行标系统推荐，绝不标人工已确认", () => {
    renderTab([makeEditRow({ selection_status: "recommended" })]);
    const row = screen.getByTestId("editlist-row");
    expect(row).toHaveAttribute("data-selection", "recommended");
    expect(within(row).getByText("系统推荐")).toBeInTheDocument();
    expect(within(row).queryByText("人工已确认")).not.toBeInTheDocument();
  });

  it("缺口段保留成行并展示缺口原因/补拍", () => {
    renderTab([
      makeEditRow({
        match_status: "gap",
        shot_id: null,
        selection_status: "none",
        gap_reasons: ["缺少要求场景：室外"],
        reshoot_recommendation: ["补拍场景：室外"],
      }),
    ]);
    expect(screen.getByTestId("row-gap")).toBeInTheDocument();
    const row = screen.getByTestId("editlist-row");
    expect(row).toHaveTextContent("缺少要求场景：室外");
    expect(row).toHaveTextContent("补拍场景：室外");
  });

  it("重复/失效镜头醒目标识", () => {
    renderTab([makeEditRow({ reused: true, shot_invalid: true })]);
    expect(screen.getByTestId("row-reused")).toBeInTheDocument();
    expect(screen.getByTestId("row-invalid")).toBeInTheDocument();
  });

  it("时长建议展示状态", () => {
    renderTab([makeEditRow({ duration_status: "too_long" })]);
    expect(screen.getByTestId("editlist-row")).toHaveTextContent("偏长");
  });

  it("空清单显示空态", () => {
    vi.mocked(hooks.useScriptEditList).mockReturnValue(query({ data: makeEditList([]) }));
    render(<EditListTab scriptId={1} active onPreview={vi.fn()} />);
    expect(screen.getByText("还没有剪辑清单")).toBeInTheDocument();
  });
});
