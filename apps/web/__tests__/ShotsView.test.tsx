import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ShotDetail } from "@/components/ShotDetail";
import { ShotsView } from "@/components/ShotsView";
import * as hooks from "@/lib/hooks";
import type { Shot, ShotAnalysis, ShotDetail as ShotDetailT } from "@/lib/types";

vi.mock("@/lib/hooks", () => ({
  // PM 产品面板 stub（本文件不测产品面板；空数据只求安静渲染）
  usePmSummary: () => ({ data: [], isLoading: false }),
  usePmAssetLinks: () => ({ data: [], isLoading: false }),
  usePmShotLinks: () => ({ data: null, isLoading: true }),
  usePmSuggestions: () => ({ data: [], isLoading: false }),
  usePmMutations: () => ({
    create: { mutate: vi.fn(), isPending: false, error: null },
    update: { mutate: vi.fn(), isPending: false },
    remove: { mutate: vi.fn(), isPending: false },
    bulk: { mutate: vi.fn(), isPending: false },
  }),
  useShotAnalysis: vi.fn(),
  useAnalyzeMutation: vi.fn(),
  useAssetShots: vi.fn(),
  useShots: vi.fn(),
  useShotSearch: vi.fn(),
  useReviewSummary: vi.fn(),
  useShotCompleteness: vi.fn(),
  useShotFilterOptions: vi.fn(),
  useProducts: vi.fn(),
  useShot: vi.fn(),
  useExportMutation: vi.fn(),
  useExportStatus: vi.fn(),
  useShotAi: vi.fn(),
  useAnalyzeShotAiMutation: vi.fn(),
  useEffectiveResult: vi.fn(),
  useReviewState: vi.fn(),
  useReviewEvents: vi.fn(),
  useProductCandidates: vi.fn(),
  useReviewActionMutation: vi.fn(),
  useShotUsageCounts: vi.fn(),
  useShotUsageSummary: vi.fn(),
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
    asset_filename: null,
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
    keyframe_count: 0,
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
  vi.mocked(hooks.useShotUsageCounts).mockReturnValue(query({ data: { items: [] } }));
  vi.mocked(hooks.useShotUsageSummary).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useAnalyzeMutation).mockReturnValue(mutation());
  vi.mocked(hooks.useAssetShots).mockReturnValue(query());
  vi.mocked(hooks.useShots).mockReturnValue(query());
  vi.mocked(hooks.useShotSearch).mockReturnValue(query());
  vi.mocked(hooks.useReviewSummary).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useShotCompleteness).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useShotFilterOptions).mockReturnValue(query({ data: {} }));
  vi.mocked(hooks.useProducts).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useShot).mockReturnValue(query({ data: makeDetail() }));
  vi.mocked(hooks.useExportMutation).mockReturnValue(mutation());
  vi.mocked(hooks.useExportStatus).mockReturnValue(query());
  vi.mocked(hooks.useShotAi).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useAnalyzeShotAiMutation).mockReturnValue(mutation());
  vi.mocked(hooks.useEffectiveResult).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useReviewState).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useReviewEvents).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useProductCandidates).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useReviewActionMutation).mockReturnValue(mutation());
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

  it("选择审核状态切换为 /shot-search 投影筛选", async () => {
    vi.mocked(hooks.useShotSearch).mockReturnValue(
      query({ data: { items: [makeShot({ id: 77 })], total: 1, page: 1, page_size: 24 } }),
    );
    const user = userEvent.setup();
    render(<ShotsView assetId={null} />);
    await user.selectOptions(screen.getByTestId("filter-review-status"), "confirmed");
    expect(hooks.useShotSearch).toHaveBeenLastCalledWith(
      expect.objectContaining({ review_status: "confirmed" }),
      true,
    );
    expect(screen.getAllByTestId("shot-card")).toHaveLength(1);
  });

  it("scoped 顶部显示素材 AI 审核汇总（含风险计数）", () => {
    vi.mocked(hooks.useReviewSummary).mockReturnValue(
      query({
        data: {
          asset_id: 10, total_shots: 5, ai_unanalyzed_count: 0, ai_running_count: 0,
          ai_failed_count: 0, pending_review_count: 2, unreviewed_count: 1, confirmed_count: 1,
          modified_count: 0, rejected_count: 0, unable_count: 0, stale_review_count: 0,
          risk_shot_count: 1, primary_product: null, related_products: [],
          ai_overall_status: "pending_review",
        },
      }),
    );
    render(<ShotsView assetId={10} />);
    const bar = screen.getByTestId("review-summary");
    expect(bar).toBeInTheDocument();
    expect(bar).toHaveTextContent("风险");
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

  it("有关键帧条时渲染多帧（主帧 + N 帧）", () => {
    vi.mocked(hooks.useShot).mockReturnValue(query({ data: makeDetail({ keyframe_count: 3 }) }));
    render(<ShotDetail shotId={1} />);
    const strip = screen.getByTestId("keyframe-strip");
    expect(strip).toBeInTheDocument();
    // 主关键帧缩略 + 3 帧 = 4 个按钮
    expect(strip.querySelectorAll("button")).toHaveLength(4);
  });

  it("无关键帧条时不渲染条", () => {
    vi.mocked(hooks.useShot).mockReturnValue(query({ data: makeDetail({ keyframe_count: 0 }) }));
    render(<ShotDetail shotId={1} />);
    expect(screen.queryByTestId("keyframe-strip")).not.toBeInTheDocument();
  });

  it("审核面板显示有效结果与来源（AI 未确认）及风险", () => {
    vi.mocked(hooks.useEffectiveResult).mockReturnValue(
      query({
        data: {
          shot_id: 1, review_status: "unreviewed", source: "ai", confirmed: false,
          searchable: true, ai_status: "completed", has_newer_ai_result: false,
          review_is_stale: false, stale_reason: null,
          result: { one_line: "产品特写", risk_flags: ["competitor"] },
        },
      }),
    );
    vi.mocked(hooks.useReviewState).mockReturnValue(
      query({ data: { review_status: "unreviewed", lock_version: 0 } }),
    );
    render(<ShotDetail shotId={1} />);
    expect(screen.getByTestId("review-panel")).toBeInTheDocument();
    expect(screen.getByText("产品特写")).toBeInTheDocument();
    // 最终检索内容区明确标注来源为 AI（未经人工确认）
    expect(screen.getByText("采用 AI 结果")).toBeInTheDocument();
    expect(screen.getByText("competitor")).toBeInTheDocument();
  });

  it("点击确认按当前 lock_version 触发审核 mutation", async () => {
    const mutate = vi.fn();
    vi.mocked(hooks.useReviewActionMutation).mockReturnValue(mutation({ mutate }));
    vi.mocked(hooks.useReviewState).mockReturnValue(
      query({ data: { review_status: "unreviewed", lock_version: 3 } }),
    );
    vi.mocked(hooks.useEffectiveResult).mockReturnValue(
      query({
        data: {
          shot_id: 1, review_status: "unreviewed", source: "ai", confirmed: false,
          searchable: true, ai_status: "completed", has_newer_ai_result: false,
          review_is_stale: false, stale_reason: null, result: { one_line: "产品特写" },
        },
      }),
    );
    const user = userEvent.setup();
    render(<ShotDetail shotId={1} />);
    await user.click(screen.getByTestId("review-confirm"));
    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        shotId: 1,
        action: "confirm",
        body: expect.objectContaining({ lock_version: 3 }),
      }),
    );
  });

  it("人工确认后展示『人工确认结果』与已确认状态", () => {
    vi.mocked(hooks.useEffectiveResult).mockReturnValue(
      query({
        data: {
          shot_id: 1, review_status: "confirmed", source: "human", confirmed: true,
          searchable: true, ai_status: "completed", has_newer_ai_result: false,
          review_is_stale: false, stale_reason: null, result: { one_line: "人工确认描述" },
        },
      }),
    );
    vi.mocked(hooks.useReviewState).mockReturnValue(
      query({ data: { review_status: "confirmed", lock_version: 1 } }),
    );
    render(<ShotDetail shotId={1} />);
    // 三区分离：最终检索内容标注采用人工结果，人工审核区状态为已确认
    expect(screen.getByText("采用人工结果")).toBeInTheDocument();
    expect(screen.getByText("已确认")).toBeInTheDocument();
  });
});
