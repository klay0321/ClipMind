import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExportCenterView } from "@/components/exports/ExportCenterView";
import * as hooks from "@/lib/hooks";

import { makeExportItem, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useExportCenter: vi.fn(),
  useRetryExport: vi.fn(),
  useDeleteExport: vi.fn(),
}));

function renderC(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function listResponse(items = [makeExportItem()], total = items.length) {
  return query({ data: { items, total, page: 1, page_size: 20 } });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hooks.useExportCenter).mockReturnValue(listResponse());
  vi.mocked(hooks.useRetryExport).mockReturnValue(mutation());
  vi.mocked(hooks.useDeleteExport).mockReturnValue(mutation());
});

describe("ExportCenterView", () => {
  it("渲染导出行 + 下载直链", () => {
    renderC(<ExportCenterView />);
    expect(screen.getByTestId("export-center")).toBeInTheDocument();
    expect(screen.getByTestId("export-row-clip-1")).toBeInTheDocument();
    expect(screen.getByTestId("download-1")).toHaveAttribute("href", "/api/exports/1/download");
    expect(screen.getByTestId("download-count-1")).toHaveTextContent("已下载 2 次");
  });

  it("仅 failed 显示重试按钮", () => {
    vi.mocked(hooks.useExportCenter).mockReturnValue(
      listResponse([makeExportItem({ status: "completed" })]),
    );
    renderC(<ExportCenterView />);
    expect(screen.queryByTestId("retry-1")).not.toBeInTheDocument();
  });

  it("failed 行：展示错误信息 + 重试调用 mutate", async () => {
    const retry = mutation();
    vi.mocked(hooks.useRetryExport).mockReturnValue(retry);
    vi.mocked(hooks.useExportCenter).mockReturnValue(
      listResponse([
        makeExportItem({ status: "failed", error_message: "ffmpeg 退出码 1", has_file: false }),
      ]),
    );
    const user = userEvent.setup();
    renderC(<ExportCenterView />);
    expect(screen.getByTestId("export-error-1")).toHaveTextContent("ffmpeg 退出码 1");
    await user.click(screen.getByTestId("retry-1"));
    expect(retry.mutate).toHaveBeenCalledWith({ kind: "clip", id: 1 });
  });

  it("删除确认对话框文案明确「不删除源视频和素材」", async () => {
    const del = mutation();
    vi.mocked(hooks.useDeleteExport).mockReturnValue(del);
    const user = userEvent.setup();
    renderC(<ExportCenterView />);
    await user.click(screen.getByTestId("delete-1"));
    expect(
      screen.getByText(/只删除导出记录和派生导出文件，不删除源视频和素材/),
    ).toBeInTheDocument();
    await user.click(screen.getByTestId("confirm-ok"));
    expect(del.mutate).toHaveBeenCalledWith({ kind: "clip", id: 1 });
  });

  it("queued/running 不显示删除按钮", () => {
    vi.mocked(hooks.useExportCenter).mockReturnValue(
      listResponse([makeExportItem({ status: "running", has_file: false })]),
    );
    renderC(<ExportCenterView />);
    expect(screen.queryByTestId("delete-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("retry-1")).not.toBeInTheDocument();
  });

  it("种类筛选切换更新 select 值", async () => {
    const user = userEvent.setup();
    renderC(<ExportCenterView />);
    await user.selectOptions(screen.getByTestId("filter-kind"), "bundle");
    expect((screen.getByTestId("filter-kind") as HTMLSelectElement).value).toBe("bundle");
  });

  it("状态筛选切换更新 select 值", async () => {
    const user = userEvent.setup();
    renderC(<ExportCenterView />);
    await user.selectOptions(screen.getByTestId("filter-status"), "failed");
    expect((screen.getByTestId("filter-status") as HTMLSelectElement).value).toBe("failed");
  });

  it("空态显示空提示", () => {
    vi.mocked(hooks.useExportCenter).mockReturnValue(listResponse([], 0));
    renderC(<ExportCenterView />);
    expect(screen.getByTestId("empty")).toBeInTheDocument();
  });
});
