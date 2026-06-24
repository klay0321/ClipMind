import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AssetTable } from "@/components/AssetTable";
import { AssetStatusBadge, ScanStatusBadge } from "@/components/StatusBadge";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import type { Asset } from "@/lib/types";

function makeAsset(overrides: Partial<Asset> = {}): Asset {
  return {
    id: 1,
    source_directory_id: 1,
    relative_path: "powergo/demo.mp4",
    normalized_relative_path: "powergo/demo.mp4",
    filename: "demo.mp4",
    extension: "mp4",
    file_size: 1_048_576,
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
    ...overrides,
  };
}

const noop = () => {};

describe("AssetTable", () => {
  it("渲染文件名、相对路径与状态", () => {
    render(
      <AssetTable
        assets={[makeAsset()]}
        rescanningIds={new Set()}
        analyzingIds={new Set()}
        onRescan={noop}
        onAnalyze={noop}
      />,
    );
    expect(screen.getByText("demo.mp4")).toBeInTheDocument();
    expect(screen.getByText("powergo/demo.mp4")).toBeInTheDocument();
    expect(screen.getByText("已索引")).toBeInTheDocument();
  });

  it("error 素材显示错误原因", () => {
    render(
      <AssetTable
        assets={[makeAsset({ status: "error", error_message: "ffprobe_failed: 损坏" })]}
        rescanningIds={new Set()}
        analyzingIds={new Set()}
        onRescan={noop}
        onAnalyze={noop}
      />,
    );
    expect(screen.getByText(/ffprobe_failed/)).toBeInTheDocument();
  });

  it("开始分析按钮可点击触发回调", async () => {
    const onAnalyze = vi.fn();
    const user = userEvent.setup();
    render(
      <AssetTable
        assets={[makeAsset({ id: 7, shot_count: 0 })]}
        rescanningIds={new Set()}
        analyzingIds={new Set()}
        onRescan={noop}
        onAnalyze={onAnalyze}
      />,
    );
    await user.click(screen.getByRole("button", { name: "开始分析" }));
    expect(onAnalyze).toHaveBeenCalledWith(7, false);
  });

  it("已有镜头时显示数量与查看镜头入口", () => {
    render(
      <AssetTable
        assets={[makeAsset({ id: 9, shot_count: 6, status: "shot_split" })]}
        rescanningIds={new Set()}
        analyzingIds={new Set()}
        onRescan={noop}
        onAnalyze={noop}
      />,
    );
    expect(screen.getByText("6 个镜头")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看镜头" })).toHaveAttribute(
      "href",
      "/shots?asset_id=9",
    );
    expect(screen.getByRole("button", { name: "重新分析" })).toBeInTheDocument();
  });

  it("重扫中按钮禁用", () => {
    render(
      <AssetTable
        assets={[makeAsset({ id: 7 })]}
        rescanningIds={new Set([7])}
        analyzingIds={new Set()}
        onRescan={noop}
        onAnalyze={noop}
      />,
    );
    expect(screen.getByRole("button", { name: "重扫中…" })).toBeDisabled();
  });
});

describe("StatusBadge", () => {
  it("素材状态标签", () => {
    render(<AssetStatusBadge status="source_missing" />);
    expect(screen.getByText("源文件缺失")).toBeInTheDocument();
  });
  it("扫描状态标签", () => {
    render(<ScanStatusBadge status="scanning" />);
    expect(screen.getByText("扫描中")).toBeInTheDocument();
  });
});

describe("状态组件", () => {
  it("Loading 渲染骨架", () => {
    render(<Loading />);
    expect(screen.getByTestId("loading")).toBeInTheDocument();
  });
  it("Empty 渲染标题", () => {
    render(<Empty title="暂无素材" description="请扫描" />);
    expect(screen.getByText("暂无素材")).toBeInTheDocument();
  });
  it("ErrorState 显示信息并可重试", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<ErrorState message="网络错误" onRetry={onRetry} />);
    expect(screen.getByText("网络错误")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalled();
  });
});
