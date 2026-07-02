import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReadinessPanel } from "@/components/catalog/ReadinessPanel";
import { ApiError } from "@/lib/api";
import * as hooks from "@/lib/hooks";

import { makePolicy, makeReadiness, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useReadiness: vi.fn(),
  useEvaluateReadiness: vi.fn(),
  useReadinessPolicies: vi.fn(),
  useCreateReadinessPolicy: vi.fn(),
  useActivateReadinessPolicy: vi.fn(),
}));

const evaluate = mutation();
const createPolicy = mutation();
const activatePolicy = mutation();

function stub(readiness: unknown = makeReadiness(), policies: unknown[] = []) {
  vi.mocked(hooks.useReadiness).mockReturnValue(query({ data: readiness }));
  vi.mocked(hooks.useEvaluateReadiness).mockReturnValue(evaluate);
  vi.mocked(hooks.useReadinessPolicies).mockReturnValue(
    query({ data: { items: policies, total: policies.length } }),
  );
  vi.mocked(hooks.useCreateReadinessPolicy).mockReturnValue(createPolicy);
  vi.mocked(hooks.useActivateReadinessPolicy).mockReturnValue(activatePolicy);
}

beforeEach(() => {
  vi.clearAllMocks();
  [evaluate, createPolicy, activatePolicy].forEach((m) => m.mutate.mockReset());
  stub();
});

function renderPanel(props?: Partial<Parameters<typeof ReadinessPanel>[0]>) {
  render(<ReadinessPanel level="family" targetId={10} categoryId={1} {...props} />);
}

describe("ReadinessPanel", () => {
  it("渲染总分 / 完整徽标 / 系统默认策略版本（不只显示一个百分比）", () => {
    stub(makeReadiness({ score: 100, complete: true, policy_version: 0 }));
    renderPanel();
    expect(screen.getByTestId("readiness-score")).toHaveTextContent("100");
    expect(screen.getByTestId("readiness-complete")).toHaveTextContent("资料完整");
    expect(screen.getByTestId("readiness-policy-version")).toHaveTextContent("系统默认策略");
    // 检查表逐项渲染（不只显示分数）
    expect(screen.getByTestId("readiness-check-name_zh")).toHaveTextContent("中文名称");
    expect(screen.getByTestId("readiness-check-minimum_references")).toHaveTextContent(
      "参考图数量",
    );
  });

  it("检查表显示 current/required 与通过/未通过标记", () => {
    stub(
      makeReadiness({
        score: 50,
        complete: false,
        checks: [
          { key: "minimum_references", passed: false, current: 1, required: 3 },
          { key: "name_zh", passed: true, current: true, required: true },
        ],
        missing_items: [{ key: "minimum_references", current: 1, required: 3 }],
      }),
    );
    renderPanel();
    const row = screen.getByTestId("readiness-check-minimum_references");
    expect(row).toHaveTextContent("1");
    expect(row).toHaveTextContent("3");
    expect(within(row).getByLabelText("未通过")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("readiness-check-name_zh")).getByLabelText("通过"),
    ).toBeInTheDocument();
  });

  it("缺失项逐条列出中文标签与当前/要求值", () => {
    stub(
      makeReadiness({
        complete: false,
        missing_items: [
          { key: "minimum_references", current: 0, required: 3 },
          { key: "identity_attributes", current: 0, required: 1 },
        ],
      }),
    );
    renderPanel();
    const missing = screen.getByTestId("readiness-missing");
    expect(missing).toHaveTextContent("参考图数量");
    expect(missing).toHaveTextContent("身份关键属性");
    expect(missing).toHaveTextContent("当前 0，要求 3");
  });

  it("阻塞项醒目逐条显示后端 detail", () => {
    stub(
      makeReadiness({
        complete: false,
        blocking_items: [
          { key: "invalid_references", detail: "存在 2 张被标记无效的参考图（错产品/重复/已拒绝），请处理" },
        ],
      }),
    );
    renderPanel();
    const blocking = screen.getByTestId("readiness-blocking");
    expect(blocking).toHaveTextContent("无效参考图");
    expect(blocking).toHaveTextContent("存在 2 张被标记无效的参考图");
  });

  it("重新评估按钮触发 POST evaluate-readiness", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("readiness-evaluate"));
    expect(evaluate.mutate).toHaveBeenCalled();
  });

  it("分类无 active 策略时提示系统默认策略，可创建策略（带 category_id）", async () => {
    stub(makeReadiness(), []);
    const user = userEvent.setup();
    renderPanel();
    expect(screen.getByTestId("policy-default-notice")).toBeInTheDocument();
    await user.click(screen.getByTestId("policy-create-open"));
    expect(screen.getByTestId("policy-create-dialog")).toBeInTheDocument();
    // 勾选一个必备角度并提交
    await user.click(screen.getByTestId("policy-angle-front"));
    await user.click(screen.getByTestId("policy-create-submit"));
    expect(createPolicy.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        category_id: 1,
        min_reference_count: 3,
        required_angles: ["front"],
      }),
      expect.anything(),
    );
  });

  it("draft 策略提供激活按钮并调用 activate", async () => {
    stub(makeReadiness(), [makePolicy({ id: 501, status: "draft", version: 2 })]);
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("policy-activate-501"));
    expect(activatePolicy.mutate).toHaveBeenCalledWith(501);
  });

  it("已有 active 策略时显示生效中而非默认策略提示", () => {
    stub(
      makeReadiness({ policy_id: 502, policy_version: 3 }),
      [makePolicy({ id: 502, status: "active", version: 3, name: "分类策略" })],
    );
    renderPanel();
    expect(screen.queryByTestId("policy-default-notice")).not.toBeInTheDocument();
    expect(screen.getByTestId("policy-active")).toHaveTextContent("分类策略");
    expect(screen.getByTestId("readiness-policy-version")).toHaveTextContent("策略版本 v3");
  });

  it("未归属分类时不提供策略配置入口", () => {
    renderPanel({ categoryId: null });
    expect(screen.getByTestId("policy-no-category")).toBeInTheDocument();
    expect(screen.queryByTestId("policy-create-open")).not.toBeInTheDocument();
  });

  it("加载失败显示可读错误", () => {
    vi.mocked(hooks.useReadiness).mockReturnValue(
      query({ isError: true, error: new ApiError(422, "未知层级") }),
    );
    renderPanel();
    expect(screen.getByTestId("catalog-error")).toHaveTextContent("未知层级");
  });

  it("只读（归档节点）不显示新建/激活策略入口", () => {
    stub(makeReadiness(), [makePolicy({ id: 501, status: "draft" })]);
    renderPanel({ readOnly: true });
    expect(screen.queryByTestId("policy-create-open")).not.toBeInTheDocument();
    expect(screen.queryByTestId("policy-activate-501")).not.toBeInTheDocument();
  });
});
