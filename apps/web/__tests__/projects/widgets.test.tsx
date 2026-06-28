import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  ArchivedBanner,
  BatchResultNotice,
  ConfirmDialog,
  InlineError,
  ProjectStatusBadge,
} from "@/components/projects/widgets";
import { ApiError } from "@/lib/api";

describe("BatchResultNotice", () => {
  it("分别展示 completed/skipped/failed，且 skipped≠失败", () => {
    render(
      <BatchResultNotice result={{ completed: [1, 2], skipped: [3], failed: [{ id: 9, error: "x" }] }} />,
    );
    expect(screen.getByTestId("batch-completed")).toHaveTextContent("成功添加 2 项");
    expect(screen.getByTestId("batch-skipped")).toHaveTextContent("已存在并跳过 1 项");
    expect(screen.getByTestId("batch-failed")).toHaveTextContent("不存在或不可用 1 项");
    expect(screen.getByTestId("batch-result")).toHaveAttribute("role", "status");
  });

  it("全空时不渲染", () => {
    const { container } = render(
      <BatchResultNotice result={{ completed: [], skipped: [], failed: [] }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ProjectStatusBadge", () => {
  it("active/archived 文案", () => {
    const { rerender } = render(<ProjectStatusBadge status="active" />);
    expect(screen.getByTestId("project-status-active")).toHaveTextContent("进行中");
    rerender(<ProjectStatusBadge status="archived" />);
    expect(screen.getByTestId("project-status-archived")).toHaveTextContent("已归档");
  });
});

describe("InlineError", () => {
  it("409 显示冲突提示，role=alert", () => {
    render(<InlineError error={new ApiError(409, "项目已被更新，请刷新")} />);
    const el = screen.getByRole("alert");
    expect(el).toHaveTextContent("项目已被更新");
  });
  it("无错误不渲染", () => {
    const { container } = render(<InlineError error={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ArchivedBanner", () => {
  it("含文字说明（不只靠颜色）+ 恢复按钮", () => {
    const onUnarchive = vi.fn();
    render(<ArchivedBanner onUnarchive={onUnarchive} />);
    expect(screen.getByTestId("archived-banner")).toHaveTextContent("只读状态");
    fireEvent.click(screen.getByText("恢复项目"));
    expect(onUnarchive).toHaveBeenCalled();
  });
});

describe("ConfirmDialog", () => {
  it("确认/取消回调；Esc 取消", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog open title="删除集合" message="只删除集合和关联，不删除镜头。" onConfirm={onConfirm} onCancel={onCancel} />,
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("不删除镜头");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalled();
    fireEvent.click(screen.getByText("确认"));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("open=false 不渲染", () => {
    const { container } = render(
      <ConfirmDialog open={false} title="t" message="m" onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
