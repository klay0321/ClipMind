import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingPanel } from "@/components/catalog/OnboardingPanel";
import { ApiError } from "@/lib/api";
import * as hooks from "@/lib/hooks";

import { makeOnboarding, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useOnboarding: vi.fn(),
  useOnboardingAction: vi.fn(),
}));

const action = mutation();

function stub(review: unknown = null) {
  vi.mocked(hooks.useOnboarding).mockReturnValue(query({ data: review }));
  vi.mocked(hooks.useOnboardingAction).mockReturnValue(action);
}

beforeEach(() => {
  vi.clearAllMocks();
  action.mutate.mockReset();
  stub();
});

function renderPanel(props?: Partial<Parameters<typeof OnboardingPanel>[0]>) {
  render(<OnboardingPanel level="family" targetId={10} {...props} />);
}

describe("OnboardingPanel", () => {
  it("必须显示可信内网人工审核权限提示", () => {
    renderPanel();
    expect(screen.getByTestId("onboarding-permission-notice")).toHaveTextContent(
      "当前为可信内网人工审核，尚未启用用户权限。",
    );
  });

  it("无记录时显示未提交状态与提交审核按钮", async () => {
    stub(null);
    const user = userEvent.setup();
    renderPanel();
    expect(screen.getByTestId("onboarding-status")).toHaveTextContent("未提交");
    expect(screen.getByTestId("onboarding-empty")).toBeInTheDocument();
    await user.click(screen.getByTestId("onboarding-submit"));
    expect(action.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ action: "submit" }),
      expect.anything(),
    );
  });

  it("提交审核 422（资料不完整）时显示后端中文缺失详情", () => {
    stub(null);
    vi.mocked(hooks.useOnboardingAction).mockReturnValue(
      mutation({
        error: new ApiError(422, "资料未达当前策略要求，无法提交审核（缺失: minimum_references）"),
      }),
    );
    renderPanel();
    expect(screen.getByTestId("catalog-error")).toHaveTextContent(
      "资料未达当前策略要求，无法提交审核",
    );
  });

  it("ready_for_review 显示待审核状态与批准/退回按钮", async () => {
    stub(makeOnboarding({ status: "ready_for_review", readiness_score: 100 }));
    const user = userEvent.setup();
    renderPanel();
    expect(screen.getByTestId("onboarding-status")).toHaveTextContent("待人工审核");
    expect(screen.getByTestId("onboarding-score")).toHaveTextContent("100/100");
    // 不显示提交按钮
    expect(screen.queryByTestId("onboarding-submit")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("onboarding-approve"));
    expect(action.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ action: "approve" }),
      expect.anything(),
    );
  });

  it("退回修改可携带审核意见 note", async () => {
    stub(makeOnboarding({ status: "ready_for_review" }));
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByTestId("onboarding-note"), "请补充正面参考图");
    await user.click(screen.getByTestId("onboarding-request-changes"));
    expect(action.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "request",
        req: expect.objectContaining({ note: "请补充正面参考图" }),
      }),
      expect.anything(),
    );
  });

  it("needs_changes 显示需修改状态、审核意见与再次提交入口", () => {
    stub(
      makeOnboarding({
        status: "needs_changes",
        reviewer_note: "参考图角度不足",
        reviewed_at: "2026-06-30T01:00:00Z",
      }),
    );
    renderPanel();
    expect(screen.getByTestId("onboarding-status")).toHaveTextContent("需修改");
    expect(screen.getByTestId("onboarding-reviewer-note")).toHaveTextContent("参考图角度不足");
    expect(screen.getByTestId("onboarding-submit")).toBeInTheDocument();
  });

  it("阻止使用需确认后才调用 block", async () => {
    stub(makeOnboarding({ status: "approved" }));
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("onboarding-block"));
    expect(action.mutate).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "确认阻止" }));
    expect(action.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ action: "block" }),
      expect.anything(),
    );
  });

  it("blocked 状态不再显示阻止按钮", () => {
    stub(makeOnboarding({ status: "blocked" }));
    renderPanel();
    expect(screen.getByTestId("onboarding-status")).toHaveTextContent("已阻止使用");
    expect(screen.queryByTestId("onboarding-block")).not.toBeInTheDocument();
  });

  it("无记录时没有阻止按钮（后端要求已有审核记录）", () => {
    stub(null);
    renderPanel();
    expect(screen.queryByTestId("onboarding-block")).not.toBeInTheDocument();
  });

  it("操作人显示名随动作提交（明示非登录身份）", async () => {
    stub(null);
    const user = userEvent.setup();
    renderPanel();
    const actor = screen.getByTestId("onboarding-actor");
    await user.type(actor, "运营A");
    await user.click(screen.getByTestId("onboarding-submit"));
    expect(action.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        req: expect.objectContaining({ actor_label: "运营A" }),
      }),
      expect.anything(),
    );
  });

  it("只读（归档节点）不显示任何操作按钮", () => {
    stub(makeOnboarding({ status: "ready_for_review" }));
    renderPanel({ readOnly: true });
    expect(screen.queryByTestId("onboarding-submit")).not.toBeInTheDocument();
    expect(screen.queryByTestId("onboarding-approve")).not.toBeInTheDocument();
    expect(screen.queryByTestId("onboarding-block")).not.toBeInTheDocument();
  });
});
