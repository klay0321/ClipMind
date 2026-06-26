import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SearchBar } from "@/components/search/SearchBar";
import * as hooks from "@/lib/hooks";
import type { SearchMode } from "@/lib/types";

import { query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useSearchSuggestions: vi.fn(),
}));

function Harness({
  onSubmit = vi.fn(),
  onClear = vi.fn(),
  onModeChange = vi.fn(),
}: {
  onSubmit?: () => void;
  onClear?: () => void;
  onModeChange?: (m: SearchMode) => void;
}) {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  return (
    <SearchBar
      value={value}
      onChange={setValue}
      mode={mode}
      onModeChange={(m) => {
        setMode(m);
        onModeChange(m);
      }}
      onSubmit={onSubmit}
      onClear={onClear}
    />
  );
}

beforeEach(() => {
  vi.mocked(hooks.useSearchSuggestions).mockReturnValue(query({ data: { items: [] } }));
});

describe("SearchBar", () => {
  it("Enter（无 shift）触发提交", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSubmit={onSubmit} />);
    await user.type(screen.getByTestId("search-input"), "桌面充电{Enter}");
    expect(onSubmit).toHaveBeenCalled();
  });

  it("点击示例填入输入框", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const examples = screen.getAllByTestId("search-example");
    await user.click(examples[0]);
    expect((screen.getByTestId("search-input") as HTMLTextAreaElement).value.length).toBeGreaterThan(0);
  });

  it("切换搜索模式回调", async () => {
    const onModeChange = vi.fn();
    const user = userEvent.setup();
    render(<Harness onModeChange={onModeChange} />);
    await user.click(screen.getByTestId("mode-lexical"));
    expect(onModeChange).toHaveBeenCalledWith("lexical");
  });

  it("清空按钮回调", async () => {
    const onClear = vi.fn();
    const user = userEvent.setup();
    render(<Harness onClear={onClear} />);
    await user.type(screen.getByTestId("search-input"), "x");
    await user.click(screen.getByTestId("search-clear"));
    expect(onClear).toHaveBeenCalled();
  });

  it("真实建议 API 返回时展示分组建议，点击追加到查询", async () => {
    vi.mocked(hooks.useSearchSuggestions).mockReturnValue(
      query({
        data: {
          items: [
            { value: "示例扫地机 X10", type: "product" },
            { value: "桌面", type: "scene" },
          ],
        },
      }),
    );
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByTestId("search-input");
    await user.type(input, "扫地");
    // 防抖 + 聚焦后出现建议下拉
    const sug = await screen.findByTestId("suggestions", undefined, { timeout: 2000 });
    expect(sug).toHaveTextContent("产品");
    expect(sug).toHaveTextContent("场景");
    await user.click(screen.getAllByTestId("suggestion-item")[0]);
    expect((input as HTMLTextAreaElement).value).toContain("示例扫地机 X10");
  });
});
