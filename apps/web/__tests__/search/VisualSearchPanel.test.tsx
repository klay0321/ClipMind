import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VisualSearchPanel } from "@/components/search/VisualSearchPanel";
import * as hooks from "@/lib/hooks";

import { mutation } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useVisualSearch: vi.fn(),
}));

const HITS = {
  provider: "fake",
  model: "fake-visual-deterministic-v1",
  total_indexed: 42,
  hits: [
    {
      kind: "asset", score: 0.998877, asset_id: 7, filename: "a.png",
      media_kind: "image",
    },
    {
      kind: "shot", score: 0.87, shot_id: 33, asset_id: 9, filename: "v.mp4",
      sequence_no: 2, start_time: 1.5, end_time: 4.2, is_historical: false,
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  global.URL.createObjectURL = vi.fn(() => "blob:preview");
  global.URL.revokeObjectURL = vi.fn();
});

function pickFile() {
  const input = screen.getByTestId("visual-search-file") as HTMLInputElement;
  const file = new File([new Uint8Array([1, 2, 3])], "q.png", { type: "image/png" });
  fireEvent.change(input, { target: { files: [file] } });
  return file;
}

describe("VisualSearchPanel 以图搜图", () => {
  it("未选图时提交禁用；选图后提交携带 kind", async () => {
    const user = userEvent.setup();
    const mut = mutation();
    vi.mocked(hooks.useVisualSearch).mockReturnValue(mut);
    render(<VisualSearchPanel />);
    expect(screen.getByTestId("visual-search-submit")).toBeDisabled();
    const file = pickFile();
    await user.selectOptions(screen.getByTestId("visual-search-kind"), "shot");
    await user.click(screen.getByTestId("visual-search-submit"));
    expect(mut.mutate).toHaveBeenCalledWith({ file, kind: "shot" });
  });

  it("渲染命中结果：素材/镜头卡片带相似度与时间码", () => {
    vi.mocked(hooks.useVisualSearch).mockReturnValue(mutation({ data: HITS }));
    render(<VisualSearchPanel />);
    expect(screen.getByTestId("visual-search-results")).toBeInTheDocument();
    expect(screen.getByText(/42 条视觉向量比对/)).toBeInTheDocument();
    const assetCard = screen.getByTestId("visual-hit-asset-7");
    expect(assetCard).toHaveTextContent("0.999");
    const shotCard = screen.getByTestId("visual-hit-shot-33");
    expect(shotCard).toHaveTextContent("镜头 #33");
    expect(shotCard).toHaveTextContent("1.5s – 4.2s");
  });

  it("空结果显示说明而非假数据", () => {
    vi.mocked(hooks.useVisualSearch).mockReturnValue(
      mutation({ data: { ...HITS, hits: [] } }),
    );
    render(<VisualSearchPanel />);
    expect(screen.getByText(/没有相似结果/)).toBeInTheDocument();
  });

  it("接口失败显示错误（如视觉模型不可用 503）", () => {
    vi.mocked(hooks.useVisualSearch).mockReturnValue(
      mutation({ isError: true, error: new Error("视觉模型不可用: embedder 不可达") }),
    );
    render(<VisualSearchPanel />);
    expect(screen.getByTestId("visual-search-error")).toHaveTextContent("视觉模型不可用");
  });
});
