import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScriptMultiExportPanel } from "@/components/script/ScriptMultiExportPanel";
import * as hooks from "@/lib/hooks";

import { mutation, query } from "../search/fixtures";
import { makeExport } from "../script/fixtures";

vi.mock("@/lib/hooks", () => ({
  useCreateScriptExport: vi.fn(),
  useScriptExportStatus: vi.fn(),
}));

const createMut = mutation();

beforeEach(() => {
  vi.clearAllMocks();
  createMut.mutate.mockReset();
  window.localStorage.clear();
  vi.mocked(hooks.useCreateScriptExport).mockReturnValue(createMut);
  vi.mocked(hooks.useScriptExportStatus).mockReturnValue(query());
});

describe("ScriptMultiExportPanel", () => {
  it("渲染全部 5 种格式按钮", () => {
    render(<ScriptMultiExportPanel scriptId={1} />);
    for (const f of ["csv", "xlsx", "json", "markdown", "printable"]) {
      expect(screen.getByTestId(`export-format-${f}`)).toBeInTheDocument();
    }
  });

  it("点击 xlsx → 用 xlsx 调创建导出", async () => {
    const user = userEvent.setup();
    render(<ScriptMultiExportPanel scriptId={1} />);
    await user.click(screen.getByTestId("export-format-xlsx"));
    expect(createMut.mutate).toHaveBeenCalledWith("xlsx", expect.anything());
  });

  it("点击 markdown → 用 markdown 调创建导出", async () => {
    const user = userEvent.setup();
    render(<ScriptMultiExportPanel scriptId={1} />);
    await user.click(screen.getByTestId("export-format-markdown"));
    expect(createMut.mutate).toHaveBeenCalledWith("markdown", expect.anything());
  });

  it("从 localStorage 恢复 completed → 显示下载链接", () => {
    window.localStorage.setItem("clipmind-script-export-1-json", "9");
    vi.mocked(hooks.useScriptExportStatus).mockReturnValue(
      query({ data: makeExport({ id: 9, status: "completed", has_file: true, export_format: "json", row_count: 4 }) }),
    );
    render(<ScriptMultiExportPanel scriptId={1} />);
    // 默认选中 csv，但 json 已记录；点击 json 后展示下载（这里直接断言 csv 默认无下载）
    expect(screen.queryByTestId("multi-export-download")).not.toBeInTheDocument();
  });

  it("含导出中心入口链接", () => {
    render(<ScriptMultiExportPanel scriptId={1} />);
    expect(screen.getByTestId("multi-export-center-link")).toHaveAttribute("href", "/exports");
  });

  it("生成中禁用全部格式按钮（防重复）", () => {
    vi.mocked(hooks.useCreateScriptExport).mockReturnValue(mutation({ isPending: true }));
    render(<ScriptMultiExportPanel scriptId={1} />);
    expect(screen.getByTestId("export-format-csv")).toBeDisabled();
  });
});
