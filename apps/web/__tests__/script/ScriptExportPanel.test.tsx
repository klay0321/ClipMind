import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScriptExportPanel } from "@/components/script/ScriptExportPanel";
import * as hooks from "@/lib/hooks";

import { makeExport, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useCreateScriptCsvExport: vi.fn(),
  useScriptExportStatus: vi.fn(),
}));

const createMut = mutation();

beforeEach(() => {
  vi.clearAllMocks();
  createMut.mutate.mockReset();
  window.localStorage.clear();
  vi.mocked(hooks.useCreateScriptCsvExport).mockReturnValue(createMut);
  vi.mocked(hooks.useScriptExportStatus).mockReturnValue(query());
});

describe("ScriptExportPanel", () => {
  it("点击导出 → 调真实 create 导出", async () => {
    const user = userEvent.setup();
    render(<ScriptExportPanel scriptId={1} />);
    await user.click(screen.getByTestId("export-csv"));
    expect(createMut.mutate).toHaveBeenCalled();
  });

  it("创建中禁用（防重复点击）", () => {
    vi.mocked(hooks.useCreateScriptCsvExport).mockReturnValue(mutation({ isPending: true }));
    render(<ScriptExportPanel scriptId={1} />);
    expect(screen.getByTestId("export-csv")).toBeDisabled();
  });

  it("从 localStorage 恢复 + completed → 显示下载链接", () => {
    window.localStorage.setItem("clipmind-script-export-1", "7");
    vi.mocked(hooks.useScriptExportStatus).mockReturnValue(
      query({ data: makeExport({ status: "completed", has_file: true, row_count: 5 }) }),
    );
    render(<ScriptExportPanel scriptId={1} />);
    const dl = screen.getByTestId("export-download");
    expect(dl).toHaveAttribute("href", "/api/scripts/1/exports/7/download");
    expect(dl).toHaveTextContent("5 行");
  });

  it("running 时显示生成中且按钮禁用", () => {
    window.localStorage.setItem("clipmind-script-export-1", "7");
    vi.mocked(hooks.useScriptExportStatus).mockReturnValue(
      query({ data: makeExport({ status: "running" }) }),
    );
    render(<ScriptExportPanel scriptId={1} />);
    expect(screen.getByTestId("export-status")).toHaveTextContent("生成中");
    expect(screen.getByTestId("export-csv")).toBeDisabled();
  });

  it("failed → 重试触发 create", async () => {
    window.localStorage.setItem("clipmind-script-export-1", "7");
    vi.mocked(hooks.useScriptExportStatus).mockReturnValue(
      query({ data: makeExport({ status: "failed", error_message: "boom" }) }),
    );
    const user = userEvent.setup();
    render(<ScriptExportPanel scriptId={1} />);
    expect(screen.getByTestId("export-status")).toHaveTextContent("boom");
    await user.click(screen.getByText("重试"));
    expect(createMut.mutate).toHaveBeenCalled();
  });
});
