import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProcessingChain, assetPipeline } from "@/components/assets/ProcessingChain";
import type { Asset } from "@/lib/types";

function makeAsset(overrides: Partial<Asset> = {}): Asset {
  return {
    id: 1,
    source_directory_id: 1,
    relative_path: "p/demo.mp4",
    normalized_relative_path: "p/demo.mp4",
    filename: "demo.mp4",
    extension: "mp4",
    file_size: 1000,
    modified_at: null,
    quick_hash: null,
    duration: 27,
    width: 1920,
    height: 1080,
    fps: 30,
    video_codec: "h264",
    audio_codec: "aac",
    orientation: "landscape",
    has_audio: true,
    status: "indexed",
    error_message: null,
    last_seen_scan_id: 1,
    first_seen_at: "2026-06-23T00:00:00Z",
    last_seen_at: "2026-06-23T00:00:00Z",
    created_at: "2026-06-23T00:00:00Z",
    updated_at: "2026-06-23T00:00:00Z",
    shot_count: 0,
    analysis_status: null,
    cover_shot_id: null,
    has_poster: false,
    ...overrides,
  };
}

function stateOf(asset: Asset, key: string) {
  return assetPipeline(asset).find((s) => s.key === key)?.state;
}

describe("assetPipeline 诚实映射", () => {
  it("仅入库：拆镜头及之后未开始", () => {
    const a = makeAsset();
    expect(stateOf(a, "index")).toBe("done");
    expect(stateOf(a, "split")).toBe("todo");
    expect(stateOf(a, "ai")).toBe("todo");
    expect(stateOf(a, "search")).toBe("todo");
  });

  it("源缺失：入库标记失败", () => {
    expect(stateOf(makeAsset({ status: "source_missing" }), "index")).toBe("failed");
  });

  it("拆镜头进行中：split 处于处理中", () => {
    const a = makeAsset({ status: "processing", analysis_status: "running" });
    expect(stateOf(a, "split")).toBe("active");
  });

  it("拆镜头失败：split=failed", () => {
    expect(stateOf(makeAsset({ analysis_status: "failed" }), "split")).toBe("failed");
  });

  it("已拆镜头：split/deriv 完成", () => {
    const a = makeAsset({ shot_count: 6, status: "shot_split", analysis_status: "completed", cover_shot_id: 3 });
    expect(stateOf(a, "split")).toBe("done");
    expect(stateOf(a, "deriv")).toBe("done");
  });

  it("AI 完成且可搜索：ai/search=done", () => {
    const a = makeAsset({
      shot_count: 6,
      status: "searchable",
      analysis_status: "completed",
      cover_shot_id: 3,
      ai_analysis_status: "completed",
      ai_analyzed_total: 6,
    });
    expect(stateOf(a, "ai")).toBe("done");
    expect(stateOf(a, "search")).toBe("done");
  });

  it("AI 失败：ai=failed", () => {
    expect(stateOf(makeAsset({ shot_count: 6, ai_analysis_status: "failed" }), "ai")).toBe("failed");
  });
});

describe("ProcessingChain 渲染", () => {
  it("compact 渲染全部阶段标签", () => {
    render(<ProcessingChain asset={makeAsset()} />);
    expect(screen.getByText("已入库")).toBeInTheDocument();
    expect(screen.getByText("可搜索")).toBeInTheDocument();
  });

  it("full 变体含进度 aria-label", () => {
    const { container } = render(<ProcessingChain asset={makeAsset()} variant="full" />);
    expect(container.querySelector("[aria-label^='处理进度']")).toBeTruthy();
  });
});
