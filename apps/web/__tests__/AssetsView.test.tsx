import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AssetsView } from "@/components/AssetsView";
import * as hooks from "@/lib/hooks";
import type { Asset, SourceDirectory } from "@/lib/types";

vi.mock("@/lib/hooks", () => ({
  useAssets: vi.fn(),
  useSourceDirectories: vi.fn(),
  useScanStatus: vi.fn(),
  useScanMutation: vi.fn(),
  useRescanMutation: vi.fn(),
  useCreateSourceDirectory: vi.fn(),
}));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function query(overrides: Record<string, any> = {}): any {
  return {
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    isFetching: false,
    refetch: vi.fn(() => Promise.resolve()),
    ...overrides,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function mutation(overrides: Record<string, any> = {}): any {
  return { mutate: vi.fn(), isPending: false, error: null, ...overrides };
}

function makeDir(overrides: Partial<SourceDirectory> = {}): SourceDirectory {
  return {
    id: 1,
    name: "PowerGo",
    mount_path: "/app/source",
    enabled: true,
    recursive: true,
    include_extensions: ["mp4"],
    exclude_patterns: [],
    read_only: true,
    scan_status: "completed",
    last_scanned_at: null,
    created_at: "2026-06-23T00:00:00Z",
    updated_at: "2026-06-23T00:00:00Z",
    ...overrides,
  };
}

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
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(hooks.useScanMutation).mockReturnValue(mutation());
  vi.mocked(hooks.useRescanMutation).mockReturnValue(mutation());
  vi.mocked(hooks.useCreateSourceDirectory).mockReturnValue(mutation());
  vi.mocked(hooks.useScanStatus).mockReturnValue(query());
  vi.mocked(hooks.useSourceDirectories).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useAssets).mockReturnValue(query());
});

describe("AssetsView", () => {
  it("加载态显示骨架", () => {
    vi.mocked(hooks.useAssets).mockReturnValue(query({ isLoading: true }));
    render(<AssetsView />);
    expect(screen.getByTestId("loading")).toBeInTheDocument();
  });

  it("无目录时空态引导创建", () => {
    vi.mocked(hooks.useSourceDirectories).mockReturnValue(query({ data: [] }));
    vi.mocked(hooks.useAssets).mockReturnValue(
      query({ data: { items: [], total: 0, page: 1, page_size: 20 } }),
    );
    render(<AssetsView />);
    expect(screen.getByTestId("empty")).toBeInTheDocument();
    expect(screen.getByText("还没有素材目录")).toBeInTheDocument();
  });

  it("错误态显示错误并可重试", () => {
    vi.mocked(hooks.useAssets).mockReturnValue(
      query({ isError: true, error: new Error("网络错误") }),
    );
    render(<AssetsView />);
    expect(screen.getByTestId("error")).toBeInTheDocument();
    expect(screen.getByText("网络错误")).toBeInTheDocument();
  });

  it("成功态显示素材表格", () => {
    vi.mocked(hooks.useAssets).mockReturnValue(
      query({ data: { items: [makeAsset()], total: 1, page: 1, page_size: 20 } }),
    );
    render(<AssetsView />);
    expect(screen.getByText("demo.mp4")).toBeInTheDocument();
    expect(screen.getByText(/共 1 个素材/)).toBeInTheDocument();
  });

  it("扫描中显示横幅且扫描按钮禁用", () => {
    vi.mocked(hooks.useSourceDirectories).mockReturnValue(query({ data: [makeDir({ scan_status: "scanning" })] }));
    vi.mocked(hooks.useScanStatus).mockReturnValue(
      query({
        data: {
          source_directory_id: 1,
          scan_status: "scanning",
          last_scanned_at: null,
          latest_run: {
            id: 1,
            source_directory_id: 1,
            status: "running",
            celery_task_id: "t1",
            queued_at: "2026-06-23T00:00:00Z",
            started_at: "2026-06-23T00:00:00Z",
            heartbeat_at: null,
            finished_at: null,
            worker_name: "w1",
            files_discovered: 5,
            files_new: 3,
            files_modified: 0,
            files_missing: 0,
            files_errored: 0,
            error_message: null,
          },
        },
      }),
    );
    vi.mocked(hooks.useAssets).mockReturnValue(
      query({ data: { items: [], total: 0, page: 1, page_size: 20 } }),
    );
    render(<AssetsView />);
    expect(screen.getByTestId("scan-banner")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "扫描中…" })).toBeDisabled();
  });
});
