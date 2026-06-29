import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ParserStatusBadge } from "@/components/script/ParserStatusBadge";
import { ScriptListView } from "@/components/script/ScriptListView";
import * as hooks from "@/lib/hooks";

import { makeProject, mutation, query } from "./fixtures";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/hooks", () => ({
  useScripts: vi.fn(),
  useCreateScript: vi.fn(),
}));

const createMut = mutation();

beforeEach(() => {
  vi.clearAllMocks();
  createMut.mutate.mockReset();
  push.mockReset();
  vi.mocked(hooks.useScripts).mockReturnValue(query({ data: { items: [makeProject()], total: 1, page: 1, page_size: 20 } }));
  vi.mocked(hooks.useCreateScript).mockReturnValue(createMut);
});

describe("ScriptListView", () => {
  it("空名/空脚本时创建按钮禁用", async () => {
    const user = userEvent.setup();
    render(<ScriptListView />);
    // 创建表单已移入「新建脚本」Modal：先打开再断言
    await user.click(screen.getByTestId("script-new-btn"));
    expect(screen.getByTestId("script-create")).toBeDisabled();
  });

  it("填名+脚本 → 创建并跳转工作台", async () => {
    createMut.mutate.mockImplementation(
      (_req: unknown, opts?: { onSuccess?: (d: unknown) => void }) => opts?.onSuccess?.(makeProject({ id: 42 })),
    );
    const user = userEvent.setup();
    render(<ScriptListView />);
    await user.click(screen.getByTestId("script-new-btn"));
    await user.type(screen.getByTestId("script-name"), "吹风机");
    await user.type(screen.getByTestId("script-raw"), "开场展示");
    await user.click(screen.getByTestId("script-create"));
    expect(createMut.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ name: "吹风机", raw_script: "开场展示" }),
      expect.anything(),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/script/42"));
  });

  it("列表项链接到工作台", () => {
    render(<ScriptListView />);
    expect(screen.getByTestId("script-list-item")).toHaveAttribute("href", "/script/1");
  });

  it("导入非 txt/md 文件被拒", async () => {
    const user = userEvent.setup();
    render(<ScriptListView />);
    await user.click(screen.getByTestId("script-new-btn"));
    const file = new File(["x"], "bad.docx", { type: "application/vnd.openxmlformats" });
    // 隐藏 input 由按钮触发；测试直接派发 change 设置文件
    fireEvent.change(screen.getByTestId("script-import"), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByText(/仅支持 .txt \/ .md/)).toBeInTheDocument());
  });
});

describe("ParserStatusBadge", () => {
  it("ok 显示 provider", () => {
    render(<ParserStatusBadge status="ok" provider="mimo" warnings={null} />);
    expect(screen.getByTestId("parser-status")).toHaveTextContent("mimo");
  });

  it("degraded 显示降级说明（不冒充 MiMo 成功）", () => {
    render(<ParserStatusBadge status="degraded" provider="rulebased" warnings={["mimo_timeout"]} />);
    expect(screen.getByTestId("parser-degraded-note")).toHaveTextContent("已使用规则拆段");
    expect(screen.getByTestId("parser-warnings")).toHaveTextContent("mimo_timeout");
  });
});
