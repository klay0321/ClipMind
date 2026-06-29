import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BundleBar } from "@/components/exports/BundleBar";
import * as hooks from "@/lib/hooks";

import { makeExportItem, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useCreateBundle: vi.fn(),
  useBundleStatus: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hooks.useCreateBundle).mockReturnValue(mutation());
  vi.mocked(hooks.useBundleStatus).mockReturnValue(query());
});

describe("BundleBar", () => {
  it("无选择且无打包时不渲染", () => {
    const { container } = render(
      <BundleBar selected={[]} totalDuration={0} onClear={vi.fn()} />,
    );
    expect(container.querySelector('[data-testid="bundle-bar"]')).toBeNull();
  });

  it("展示已选数量与总时长", () => {
    render(<BundleBar selected={[1, 2, 3]} totalDuration={12.5} onClear={vi.fn()} />);
    expect(screen.getByTestId("bundle-count")).toHaveTextContent("已选 3 个镜头");
    expect(screen.getByText(/总时长 12.5s/)).toBeInTheDocument();
  });

  it("创建 ZIP → 调 createBundle 带 shot_ids", async () => {
    const create = mutation();
    vi.mocked(hooks.useCreateBundle).mockReturnValue(create);
    const user = userEvent.setup();
    render(<BundleBar selected={[1, 2]} totalDuration={10} onClear={vi.fn()} />);
    await user.click(screen.getByTestId("bundle-create"));
    expect(create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ shot_ids: [1, 2] }),
      expect.anything(),
    );
  });

  it("超过 50 个镜头时禁用创建", () => {
    const many = Array.from({ length: 51 }, (_, i) => i + 1);
    render(<BundleBar selected={many} totalDuration={100} onClear={vi.fn()} />);
    expect(screen.getByTestId("bundle-create")).toBeDisabled();
  });

  it("总时长超 1800s 时禁用创建", () => {
    render(<BundleBar selected={[1]} totalDuration={2000} onClear={vi.fn()} />);
    expect(screen.getByTestId("bundle-create")).toBeDisabled();
  });

  it("创建成功后完成态展示下载 ZIP 直链", async () => {
    const create = mutation();
    create.mutate = vi.fn((_req: unknown, opts: { onSuccess?: (r: unknown) => void }) =>
      opts?.onSuccess?.({ export_id: 42 }),
    );
    vi.mocked(hooks.useCreateBundle).mockReturnValue(create);
    vi.mocked(hooks.useBundleStatus).mockReturnValue(
      query({ data: makeExportItem({ kind: "bundle", id: 42, status: "completed", has_file: true }) }),
    );
    const user = userEvent.setup();
    render(<BundleBar selected={[1]} totalDuration={5} onClear={vi.fn()} />);
    await user.click(screen.getByTestId("bundle-create"));
    expect(screen.getByTestId("bundle-download")).toHaveAttribute(
      "href",
      "/api/exports/bundle/42/download",
    );
    expect(screen.getByTestId("bundle-export-center")).toHaveAttribute("href", "/exports");
  });

  it("清空选择调用 onClear", async () => {
    const onClear = vi.fn();
    const user = userEvent.setup();
    render(<BundleBar selected={[1, 2]} totalDuration={6} onClear={onClear} />);
    await user.click(screen.getByText("清空选择"));
    expect(onClear).toHaveBeenCalled();
  });
});
