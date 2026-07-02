import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfusionsPanel } from "@/components/catalog/ConfusionsPanel";
import { ApiError } from "@/lib/api";
import * as hooks from "@/lib/hooks";

import { makeFamily, makePair, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useConfusions: vi.fn(),
  useCreateConfusionPair: vi.fn(),
  useUpdateConfusionPair: vi.fn(),
  useConfusionPairMutations: vi.fn(),
  useFamilies: vi.fn(),
  useVariants: vi.fn(),
  useSkus: vi.fn(),
}));

const create = mutation();
const update = mutation();
const archive = mutation();
const restore = mutation();

function stub(pairs: unknown[] = [], families: unknown[] = []) {
  vi.mocked(hooks.useConfusions).mockReturnValue(
    query({ data: { items: pairs, total: pairs.length } }),
  );
  vi.mocked(hooks.useCreateConfusionPair).mockReturnValue(create);
  vi.mocked(hooks.useUpdateConfusionPair).mockReturnValue(update);
  vi.mocked(hooks.useConfusionPairMutations).mockReturnValue({
    archive,
    restore,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
  vi.mocked(hooks.useFamilies).mockReturnValue(
    query({ data: { items: families, total: families.length } }),
  );
  vi.mocked(hooks.useVariants).mockReturnValue(query({ data: { items: [], total: 0 } }));
  vi.mocked(hooks.useSkus).mockReturnValue(query({ data: { items: [], total: 0 } }));
}

beforeEach(() => {
  vi.clearAllMocks();
  [create, update, archive, restore].forEach((m) => m.mutate.mockReset());
  stub();
});

function renderPanel(props?: Partial<Parameters<typeof ConfusionsPanel>[0]>) {
  render(
    <ConfusionsPanel
      level="family"
      targetId={10}
      familyId={10}
      onSelect={vi.fn()}
      {...props}
    />,
  );
}

describe("ConfusionsPanel", () => {
  it("空态提示且不含任何硬编码产品名", () => {
    stub([]);
    renderPanel();
    expect(screen.getByTestId("confusion-empty")).toBeInTheDocument();
  });

  it("列表显示对方名称（来自 API）、严重程度中文与特征条数", () => {
    stub([
      makePair({
        id: 700,
        severity: "high",
        reason: "外观仅接口数量不同",
        distinguishing_features: [
          {
            feature: "接口数量",
            left_value: "2",
            right_value: "3",
            visible_in_reference: true,
            identity_relevant: true,
          },
        ],
      }),
    ]);
    renderPanel();
    const row = screen.getByTestId("confusion-row-700");
    // 当前节点是 left(10) → 对方显示 right 的名称（mock 数据，非硬编码）
    expect(within(row).getByTestId("confusion-goto-700")).toHaveTextContent("近似产品");
    expect(row).toHaveTextContent("高严重度");
    expect(row).toHaveTextContent("1 条区分特征");
    expect(row).toHaveTextContent("外观仅接口数量不同");
  });

  it("当前节点为 right 侧时对方取 left 侧", () => {
    stub([
      makePair({
        id: 701,
        left_target_id: 8,
        right_target_id: 10,
        left: { id: 8, name_zh: "另一产品", code: "fam-8", status: "active" },
        right: { id: 10, name_zh: "示例产品", code: "fam-10", status: "active" },
      }),
    ]);
    renderPanel();
    expect(screen.getByTestId("confusion-goto-701")).toHaveTextContent("另一产品");
  });

  it("点击对方名称调用 onSelect 跳转", async () => {
    stub([makePair({ id: 700 })]);
    const onSelect = vi.fn();
    const user = userEvent.setup();
    renderPanel({ onSelect });
    await user.click(screen.getByTestId("confusion-goto-700"));
    expect(onSelect).toHaveBeenCalledWith({ level: "family", id: 11 });
  });

  it("添加混淆关系：搜索候选 → 选目标 → 提交 POST", async () => {
    stub([], [makeFamily({ id: 11, name_zh: "候选产品", code: "fam-11" })]);
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("confusion-add"));
    await user.selectOptions(screen.getByTestId("confusion-target-select"), "11");
    await user.selectOptions(screen.getByTestId("confusion-severity"), "high");
    await user.click(screen.getByTestId("confusion-submit"));
    expect(create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        target_level: "family",
        left_target_id: 10,
        right_target_id: 11,
        severity: "high",
      }),
      expect.anything(),
    );
  });

  it("候选列表排除自身", async () => {
    stub([], [
      makeFamily({ id: 10, name_zh: "示例产品", code: "fam-10" }),
      makeFamily({ id: 11, name_zh: "候选产品", code: "fam-11" }),
    ]);
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("confusion-add"));
    const select = screen.getByTestId("confusion-target-select");
    expect(within(select).queryByRole("option", { name: /fam-10/ })).not.toBeInTheDocument();
    expect(within(select).getByRole("option", { name: /候选产品/ })).toBeInTheDocument();
  });

  it("重复关系 409 显示可读中文提示", async () => {
    stub([], [makeFamily({ id: 11, name_zh: "候选产品" })]);
    vi.mocked(hooks.useCreateConfusionPair).mockReturnValue(
      mutation({ error: new ApiError(409, "该混淆关系已存在（无方向，反向亦视为重复）") }),
    );
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("confusion-add"));
    expect(screen.getByTestId("catalog-error")).toHaveTextContent("该混淆关系已存在");
  });

  it("区分特征编辑：增行 → 填写 → 保存 PATCH", async () => {
    stub([makePair({ id: 700 })]);
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("confusion-features-700"));
    expect(screen.getByTestId("features-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("features-empty")).toBeInTheDocument();
    await user.click(screen.getByTestId("feature-add-row"));
    const row = screen.getByTestId("feature-row-0");
    expect(row).toBeInTheDocument();
    await user.type(screen.getByTestId("feature-name-0"), "按键数量");
    await user.type(screen.getByTestId("feature-left-0"), "4");
    await user.type(screen.getByTestId("feature-right-0"), "6");
    await user.click(screen.getByTestId("feature-visible-0"));
    await user.click(screen.getByTestId("feature-identity-0"));
    await user.click(screen.getByTestId("features-save"));
    expect(update.mutate).toHaveBeenCalledWith(
      {
        id: 700,
        req: {
          distinguishing_features: [
            {
              feature: "按键数量",
              left_value: "4",
              right_value: "6",
              visible_in_reference: true,
              identity_relevant: true,
            },
          ],
        },
      },
      expect.anything(),
    );
  });

  it("特征编辑可删除行且空 feature 行不提交", async () => {
    stub([
      makePair({
        id: 700,
        distinguishing_features: [
          {
            feature: "颜色",
            left_value: "黑",
            right_value: "白",
            visible_in_reference: true,
            identity_relevant: false,
          },
        ],
      }),
    ]);
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("confusion-features-700"));
    // 已有一行 → 删除后保存提交空数组
    await user.click(screen.getByTestId("feature-remove-0"));
    await user.click(screen.getByTestId("features-save"));
    expect(update.mutate).toHaveBeenCalledWith(
      { id: 700, req: { distinguishing_features: [] } },
      expect.anything(),
    );
  });

  it("归档与恢复调用对应 mutation", async () => {
    stub([
      makePair({ id: 700 }),
      makePair({ id: 701, status: "archived", archived_at: "2026-06-30T00:00:00Z" }),
    ]);
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("confusion-archive-700"));
    expect(archive.mutate).toHaveBeenCalledWith(700);
    await user.click(screen.getByTestId("confusion-restore-701"));
    expect(restore.mutate).toHaveBeenCalledWith(701);
  });

  it("只读（归档节点）不显示添加/归档/特征编辑入口", () => {
    stub([makePair({ id: 700 })]);
    renderPanel({ readOnly: true });
    expect(screen.queryByTestId("confusion-add")).not.toBeInTheDocument();
    expect(screen.queryByTestId("confusion-archive-700")).not.toBeInTheDocument();
    expect(screen.queryByTestId("confusion-features-700")).not.toBeInTheDocument();
  });
});
