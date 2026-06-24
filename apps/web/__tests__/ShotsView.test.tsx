import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ShotDetail } from "@/components/ShotDetail";
import { ShotsView } from "@/components/ShotsView";
import * as hooks from "@/lib/hooks";
import type { Shot, ShotAnalysis, ShotDetail as ShotDetailT } from "@/lib/types";

vi.mock("@/lib/hooks", () => ({
  useShotAnalysis: vi.fn(),
  useAnalyzeMutation: vi.fn(),
  useAssetShots: vi.fn(),
  useShots: vi.fn(),
  useShot: vi.fn(),
  useExportMutation: vi.fn(),
  useExportStatus: vi.fn(),
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

function makeShot(overrides: Partial<Shot> = {}): Shot {
  return {
    id: 1,
    asset_id: 10,
    sequence_no: 1,
    start_time: 0,
    end_time: 2,
    duration: 2,
    detector_type: "pyscenedetect",
    detector_confidence: null,
    status: "ready",
    error_message: null,
    has_keyframe: true,
    has_thumbnail: true,
    has_proxy: true,
    created_at: "2026-06-23T00:00:00Z",
    updated_at: "2026-06-23T00:00:00Z",
    ...overrides,
  };
}

function makeDetail(overrides: Partial<ShotDetailT> = {}): ShotDetailT {
  return {
    ...makeShot(),
    asset_filename: "片段 A.mp4",
    asset_duration: 27,
    asset_width: 1920,
    asset_height: 1080,
    asset_video_codec: "h264",
    asset_audio_codec: "aac",
    ...overrides,
  };
}

function makeAnalysis(overrides: Partial<ShotAnalysis> = {}): ShotAnalysis {
  return {
    asset_id: 10,
    has_run: true,
    run_id: 1,
    status: "completed",
    progress: 100,
    current_step: null,
    total_shots: 3,
    completed_shots: 3,
    error_message: null,
    celery_task_id: "mtask-1",
    generation: 1,
    queued_at: null,
    started_at: null,
    finished_at: null,
    shot_count: 3,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(hooks.useShotAnalysis).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useAnalyzeMutation).mockReturnValue(mutation());
  vi.mocked(hooks.useAssetShots).mockReturnValue(query());
  vi.mocked(hooks.useShots).mockReturnValue(query());
  vi.mocked(hooks.useShot).mockReturnValue(query({ data: makeDetail() }));
  vi.mocked(hooks.useExportMutation).mockReturnValue(mutation());
  vi.mocked(hooks.useExportStatus).mockReturnValue(query());
});

describe("ShotsView", () => {
  it("scoped 加载态显示骨架", () => {
    vi.mocked(hooks.useAssetShots).mockReturnValue(query({ isLoading: true }));
    render(<ShotsView assetId={10} />);
    expect(screen.getByTestId("loading")).toBeInTheDocument();
  });

  it("scoped 空态提示拆镜头", () => {
    vi.mocked(hooks.useAssetShots).mockReturnValue(
      query({ data: { items: [], total: 0, page: 1, page_size: 24 } }),
    );
    render(<ShotsView assetId={10} />);
    expect(screen.getByTestId("empty")).toBeInTheDocument();
    expect(screen.getByText("尚未拆镜头")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始分析" })).toBeInTheDocument();
  });

  it("渲染镜头网格并默认选中首个", () => {
    vi.mocked(hooks.useAssetShots).mockReturnValue(
      query({
        data: {
          items: [makeShot({ id: 1 }), makeShot({ id: 2, sequence_no: 2 })],
          total: 2,
          page: 1,
          page_size: 24,
        },
      }),
    );
    render(<ShotsView assetId={10} />);
    expect(screen.getAllByTestId("shot-card")).toHaveLength(2);
    expect(screen.getByTestId("shot-detail")).toBeInTheDocument();
  });

  it("分析中显示横幅且按钮禁用", () => {
    vi.mocked(hooks.useShotAnalysis).mockReturnValue(
      query({ data: makeAnalysis({ status: "running", progress: 40, completed_shots: 1 }) }),
    );
    vi.mocked(hooks.useAssetShots).mockReturnValue(
      query({ data: { items: [], total: 0, page: 1, page_size: 24 } }),
    );
    render(<ShotsView assetId={10} />);
    expect(screen.getByTestId("analysis-banner")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "分析中…" })).toBeDisabled();
  });

  it("点击开始分析触发 mutation", async () => {
    const mutate = vi.fn();
    vi.mocked(hooks.useAnalyzeMutation).mockReturnValue(mutation({ mutate }));
    vi.mocked(hooks.useAssetShots).mockReturnValue(
      query({ data: { items: [], total: 0, page: 1, page_size: 24 } }),
    );
    const user = userEvent.setup();
    render(<ShotsView assetId={10} />);
    await user.click(screen.getByRole("button", { name: "开始分析" }));
    expect(mutate).toHaveBeenCalledWith({ assetId: 10, retry: false });
  });
});

describe("ShotDetail", () => {
  it("渲染代理播放器与导出按钮", () => {
    render(<ShotDetail shotId={1} />);
    expect(screen.getByTestId("shot-video")).toBeInTheDocument();
    expect(screen.getByText("片段 A.mp4")).toBeInTheDocument();
    expect(screen.getByTestId("shot-export-btn")).toBeInTheDocument();
  });

  it("点击导出触发 mutation", async () => {
    const mutate = vi.fn();
    vi.mocked(hooks.useExportMutation).mockReturnValue(mutation({ mutate }));
    const user = userEvent.setup();
    render(<ShotDetail shotId={1} />);
    await user.click(screen.getByTestId("shot-export-btn"));
    expect(mutate).toHaveBeenCalled();
  });

  it("导出完成显示下载链接", () => {
    vi.mocked(hooks.useExportStatus).mockReturnValue(
      query({ data: { id: 5, status: "completed", has_file: true } }),
    );
    render(<ShotDetail shotId={1} />);
    expect(screen.getByTestId("shot-download-link")).toHaveAttribute(
      "href",
      "/api/exports/5/download",
    );
  });

  it("无选中镜头时提示", () => {
    render(<ShotDetail shotId={null} />);
    expect(screen.getByText("选择左侧镜头查看详情")).toBeInTheDocument();
  });
});
