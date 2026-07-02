import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AssetIdentityPanel } from "@/components/assets/AssetIdentityPanel";
import * as hooks from "@/lib/hooks";
import type { AssetIdentity, AssetLocationEntry } from "@/lib/types";

import { mutation, query } from "../search/fixtures";

vi.mock("@/lib/hooks", () => ({
  useAssetIdentity: vi.fn(),
  useAnalysisGenerations: vi.fn(),
  useRequestFingerprint: vi.fn(),
  useFingerprintJob: vi.fn(),
  useShotsByGeneration: vi.fn(),
}));

function makeLocation(o: Partial<AssetLocationEntry> = {}): AssetLocationEntry {
  return {
    id: 1,
    source_root_id: 1,
    source_root_name: "上传素材",
    relative_path: "clips/示例视频.mp4",
    location_status: "present",
    is_primary: true,
    file_size: 1024,
    first_seen_at: "2026-07-01T00:00:00Z",
    last_seen_at: "2026-07-02T00:00:00Z",
    missing_at: null,
    verified_at: null,
    ...o,
  };
}

function makeIdentity(o: Partial<AssetIdentity> = {}): AssetIdentity {
  return {
    asset_id: 10,
    fingerprint_state: "full_ready",
    quick_fingerprint_short: "aaaabbbbcccc",
    quick_fingerprint_version: "qfp1",
    full_hash_short: "deadbeef1234",
    full_hash_algorithm: "sha256",
    full_hash_available: true,
    content_size: 2048,
    fingerprinted_at: "2026-07-02T01:00:00Z",
    fingerprint_error: null,
    location_count: 2,
    present_location_count: 1,
    missing_location_count: 0,
    conflict_location_count: 0,
    primary_location: makeLocation(),
    locations: [
      makeLocation(),
      makeLocation({
        id: 2,
        relative_path: "old/旧路径.mp4",
        location_status: "historical",
        is_primary: false,
        missing_at: "2026-07-01T12:00:00Z",
      }),
    ],
    current_generation: 2,
    historical_generation_count: 1,
    ...o,
  };
}

const fpMut = mutation();

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hooks.useAssetIdentity).mockReturnValue(query({ data: makeIdentity() }));
  vi.mocked(hooks.useAnalysisGenerations).mockReturnValue(
    query({
      data: {
        asset_id: 10,
        current_generation: 2,
        items: [
          {
            generation: 2, run_id: 5, status: "completed", is_current: true,
            shot_count: 3, usage_referenced_count: 0,
            created_at: "2026-07-02T00:00:00Z", finished_at: "2026-07-02T00:05:00Z",
          },
          {
            generation: 1, run_id: 4, status: "completed", is_current: false,
            shot_count: 4, usage_referenced_count: 2,
            created_at: "2026-07-01T00:00:00Z", finished_at: "2026-07-01T00:05:00Z",
          },
        ],
      },
    }),
  );
  vi.mocked(hooks.useRequestFingerprint).mockReturnValue(fpMut);
  vi.mocked(hooks.useFingerprintJob).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useShotsByGeneration).mockReturnValue(query({ data: { items: [] } }));
});

describe("AssetIdentityPanel", () => {
  it("显示指纹状态与缩短哈希（不暴露完整哈希）", () => {
    render(<AssetIdentityPanel assetId={10} />);
    expect(screen.getByTestId("fingerprint-state")).toHaveTextContent("完整指纹就绪");
    expect(screen.getByTestId("full-hash")).toHaveTextContent("deadbeef1234…");
    expect(screen.getByTestId("quick-fp")).toHaveTextContent("aaaabbbbcccc (qfp1)");
    // 不出现 64 位完整哈希
    expect(document.body.textContent).not.toMatch(/[0-9a-f]{64}/);
  });

  it("位置历史：present/historical/primary 标记与相对路径（无绝对路径）", () => {
    render(<AssetIdentityPanel assetId={10} />);
    const rows = screen.getAllByTestId(/location-row-/);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("在此路径");
    expect(rows[0]).toHaveTextContent("primary");
    expect(rows[0]).toHaveTextContent("上传素材 / clips/示例视频.mp4");
    expect(rows[1]).toHaveTextContent("历史位置");
    expect(rows[1]).toHaveTextContent("缺失于");
    expect(document.body.textContent).not.toMatch(/[A-Z]:\\/);
  });

  it("missing/conflict 状态展示", () => {
    vi.mocked(hooks.useAssetIdentity).mockReturnValue(
      query({
        data: makeIdentity({
          fingerprint_state: "stale",
          conflict_location_count: 1,
          locations: [
            makeLocation({ location_status: "conflict" }),
            makeLocation({ id: 3, location_status: "missing", is_primary: false }),
          ],
        }),
      }),
    );
    render(<AssetIdentityPanel assetId={10} />);
    expect(screen.getByTestId("fingerprint-state")).toHaveTextContent("内容已变化");
    expect(screen.getByText("内容冲突 1")).toBeInTheDocument();
    expect(screen.getAllByTestId(/location-row-/)[0]).toHaveTextContent("内容冲突");
  });

  it("点击按钮触发指纹任务", async () => {
    const user = userEvent.setup();
    render(<AssetIdentityPanel assetId={10} />);
    await user.click(screen.getByTestId("fp-full-btn"));
    expect(fpMut.mutate).toHaveBeenCalledWith("full", expect.anything());
    await user.click(screen.getByTestId("fp-quick-btn"));
    expect(fpMut.mutate).toHaveBeenCalledWith("quick", expect.anything());
  });

  it("任务运行中展示进度并禁用按钮", () => {
    vi.mocked(hooks.useFingerprintJob).mockReturnValue(
      query({
        data: {
          id: 7, kind: "full", status: "running", total_count: 1,
          completed_count: 0, skipped_count: 0, failed_count: 0, progress: 42,
          error_message: null, results: null,
          created_at: "2026-07-02T02:00:00Z", started_at: "2026-07-02T02:00:01Z",
          finished_at: null,
        },
      }),
    );
    render(<AssetIdentityPanel assetId={10} />);
    expect(screen.getByTestId("fp-job-status")).toHaveTextContent("running（42%）");
    expect(screen.getByTestId("fp-quick-btn")).toBeDisabled();
    expect(screen.getByTestId("fp-full-btn")).toBeDisabled();
  });

  it("代次列表：current/retired 标记与血缘引用提示；quick 候选文案", () => {
    render(<AssetIdentityPanel assetId={10} />);
    const gens = screen.getByTestId("generation-list");
    expect(gens).toHaveTextContent("第 2 代");
    expect(gens).toHaveTextContent("current");
    expect(gens).toHaveTextContent("第 1 代");
    expect(gens).toHaveTextContent("retired");
    expect(gens).toHaveTextContent("被成片血缘引用 2");
    // 身份语义文案：quick 命中只是候选，不显示为已合并
    expect(
      screen.getByText(/疑似同一素材，等待完整校验/),
    ).toBeInTheDocument();
    expect(screen.getByText(/文件路径变化不会改变素材身份/)).toBeInTheDocument();
  });

  it("展开代次显示历史镜头(含历史标记)", async () => {
    const user = userEvent.setup();
    vi.mocked(hooks.useShotsByGeneration).mockReturnValue(
      query({
        data: {
          items: [
            { id: 31, sequence_no: 1, start_time: 0, end_time: 1, retired: true },
            { id: 32, sequence_no: 2, start_time: 1, end_time: 2, retired: true },
          ],
        },
      }),
    );
    render(<AssetIdentityPanel assetId={10} />);
    await user.click(screen.getByTestId("gen-toggle-1"));
    expect(screen.getByTestId("gen-shot-31")).toBeInTheDocument();
    expect(screen.getAllByTestId(/gen-shot-/)).toHaveLength(2);
  });

  it("空状态：无位置与无代次", () => {
    vi.mocked(hooks.useAssetIdentity).mockReturnValue(
      query({
        data: makeIdentity({
          locations: [], location_count: 0, primary_location: null,
          fingerprint_state: "pending", full_hash_available: false,
          full_hash_short: null, quick_fingerprint_short: null,
        }),
      }),
    );
    vi.mocked(hooks.useAnalysisGenerations).mockReturnValue(
      query({ data: { asset_id: 10, current_generation: null, items: [] } }),
    );
    render(<AssetIdentityPanel assetId={10} />);
    expect(screen.getByText("暂无位置记录")).toBeInTheDocument();
    expect(screen.getByText("尚未进行镜头分析")).toBeInTheDocument();
    expect(screen.getByTestId("full-hash")).toHaveTextContent("未计算");
  });

  it("长路径截断渲染不崩溃", () => {
    const long = "很长的目录/".repeat(40) + "文件.mp4";
    vi.mocked(hooks.useAssetIdentity).mockReturnValue(
      query({ data: makeIdentity({ locations: [makeLocation({ relative_path: long })] }) }),
    );
    render(<AssetIdentityPanel assetId={10} />);
    expect(screen.getByTestId("location-row-1")).toHaveTextContent("文件.mp4");
  });
});
