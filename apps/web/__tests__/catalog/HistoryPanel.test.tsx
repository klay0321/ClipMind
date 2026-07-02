import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HistoryPanel } from "@/components/catalog/HistoryPanel";
import * as hooks from "@/lib/hooks";

import { makeRevision, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useRevisions: vi.fn(),
}));

function stub(items: unknown[] = [], total = items.length) {
  vi.mocked(hooks.useRevisions).mockReturnValue(query({ data: { items, total } }));
}

beforeEach(() => {
  vi.clearAllMocks();
  stub();
});

function renderPanel() {
  render(<HistoryPanel level="family" targetId={10} />);
}

describe("HistoryPanel", () => {
  it("空态提示暂无变更记录", () => {
    stub([]);
    renderPanel();
    expect(screen.getByTestId("history-empty")).toBeInTheDocument();
  });

  it("行显示实体/动作中文、摘要、操作人与截短 correlation_id", () => {
    stub([
      makeRevision({
        id: 800,
        entity_type: "family",
        action: "update",
        change_summary: "更名：旧名称 → 新名称",
        actor_label: "运营A",
        correlation_id: "abcdef1234567890abcdef1234567890",
      }),
    ]);
    renderPanel();
    const row = screen.getByTestId("revision-row-800");
    expect(row).toHaveTextContent("产品");
    expect(row).toHaveTextContent("更新");
    expect(row).toHaveTextContent("更名：旧名称 → 新名称");
    expect(row).toHaveTextContent("by 运营A");
    // correlation_id 截短显示，title 保留全文
    expect(within(row).getByTitle("abcdef1234567890abcdef1234567890")).toHaveTextContent(
      "abcdef12",
    );
  });

  it("展开 update 行显示逐字段差异（仅变化字段：旧值→新值）", async () => {
    stub([
      makeRevision({
        id: 800,
        action: "update",
        before_data: { name_zh: "旧名称", status: "active", code: "fam-10" },
        after_data: { name_zh: "新名称", status: "active", code: "fam-10" },
      }),
    ]);
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("revision-toggle-800"));
    const diff = screen.getByTestId("revision-diff-800");
    // 变化字段显示旧值与新值
    expect(diff).toHaveTextContent("name_zh");
    expect(diff).toHaveTextContent("旧名称");
    expect(diff).toHaveTextContent("新名称");
    // 未变化字段不出现在 diff 表（code 值只在原始 JSON 折叠里）
    const table = within(diff).getByRole("table");
    expect(table).not.toHaveTextContent("code");
    expect(table).not.toHaveTextContent("status");
  });

  it("create 行只显示 after 字段（无变更前列）", async () => {
    stub([
      makeRevision({
        id: 801,
        action: "create",
        before_data: null,
        after_data: { name_zh: "新建产品", code: "fam-12" },
      }),
    ]);
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("revision-toggle-801"));
    const diff = screen.getByTestId("revision-diff-801");
    expect(diff).toHaveTextContent("新建产品");
    expect(within(diff).queryByText("变更前")).not.toBeInTheDocument();
  });

  it("提供原始 JSON 折叠但 diff 不以完整 JSON 为唯一展示", async () => {
    stub([makeRevision({ id: 800 })]);
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("revision-toggle-800"));
    const diff = screen.getByTestId("revision-diff-800");
    expect(within(diff).getByText("查看原始 JSON")).toBeInTheDocument();
    // 字段级表格存在（不是只有 JSON 块）
    expect(within(diff).getByRole("table")).toBeInTheDocument();
  });

  it("总数超过已显示时提供加载更多，点击后请求下一页", async () => {
    stub(
      Array.from({ length: 20 }, (_, i) => makeRevision({ id: 900 + i, revision_number: i + 1 })),
      45,
    );
    const user = userEvent.setup();
    renderPanel();
    expect(screen.getByText(/已显示 20 \/ 45 条/)).toBeInTheDocument();
    // 初始 page=1
    expect(vi.mocked(hooks.useRevisions)).toHaveBeenLastCalledWith("family", 10, 1);
    await user.click(screen.getByTestId("history-more"));
    expect(vi.mocked(hooks.useRevisions)).toHaveBeenLastCalledWith("family", 10, 2);
  });

  it("全部加载完不再显示加载更多", () => {
    stub([makeRevision({ id: 800 })], 1);
    renderPanel();
    expect(screen.queryByTestId("history-more")).not.toBeInTheDocument();
  });
});
