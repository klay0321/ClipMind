import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinalVideosView } from "@/components/final-videos/FinalVideosView";
import * as hooks from "@/lib/hooks";

import { makeFinalVideo, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useFinalVideos: vi.fn(),
  useCreateFinalVideo: vi.fn(),
  useAssets: vi.fn(),
  useProjects: vi.fn(),
}));

const createMut = mutation();

beforeEach(() => {
  vi.clearAllMocks();
  createMut.mutate.mockReset();
  vi.mocked(hooks.useFinalVideos).mockReturnValue(
    query({ data: { items: [makeFinalVideo()], total: 1, page: 1, page_size: 20 } }),
  );
  vi.mocked(hooks.useCreateFinalVideo).mockReturnValue(createMut);
  vi.mocked(hooks.useAssets).mockReturnValue(
    query({
      data: {
        items: [
          { id: 90, filename: "final_cut.mp4", shot_count: 0 },
          { id: 10, filename: "raw_a.mp4", shot_count: 4 },
        ],
        total: 2,
      },
    }),
  );
  vi.mocked(hooks.useProjects).mockReturnValue(
    query({ data: { items: [{ id: 5, name: "夏季广告" }], total: 1 } }),
  );
});

describe("FinalVideosView", () => {
  it("渲染成片行：标题 / 状态 / 统计列", () => {
    render(<FinalVideosView />);
    const row = screen.getByTestId("final-video-row");
    expect(row).toHaveTextContent("产品宣传片 6 月投放版");
    expect(row).toHaveTextContent("final_cut.mp4");
    expect(row).toHaveTextContent("夏季广告");
    // 来源镜头 3 / 已确认 1 / 候选 2
    expect(row).toHaveTextContent("3");
    expect(row).toHaveTextContent("1");
    expect(row).toHaveTextContent("2");
    expect(screen.getByTestId("final-video-table")).toBeInTheDocument();
  });

  it("明确提示：候选须人工确认才计入使用次数", () => {
    render(<FinalVideosView />);
    expect(
      screen.getByText(/人工确认后才计入正式使用次数/),
    ).toBeInTheDocument();
  });

  it("空态", () => {
    vi.mocked(hooks.useFinalVideos).mockReturnValue(
      query({ data: { items: [], total: 0, page: 1, page_size: 20 } }),
    );
    render(<FinalVideosView />);
    expect(screen.getByTestId("empty")).toBeInTheDocument();
  });

  it("长标题正常渲染不崩溃", () => {
    const long = "长".repeat(200);
    vi.mocked(hooks.useFinalVideos).mockReturnValue(
      query({
        data: { items: [makeFinalVideo({ title: long })], total: 1, page: 1, page_size: 20 },
      }),
    );
    render(<FinalVideosView />);
    expect(screen.getByTestId("final-video-row")).toHaveTextContent(long);
  });

  it("新建：未选素材或空标题时提交禁用；选择后提交调用创建", async () => {
    const user = userEvent.setup();
    render(<FinalVideosView />);
    await user.click(screen.getByTestId("toggle-create-final-video"));
    const submit = screen.getByTestId("create-fv-submit");
    expect(submit).toBeDisabled();
    await user.click(screen.getByTestId("create-fv-asset-90"));
    expect(submit).toBeDisabled(); // 仍缺标题
    await user.type(screen.getByTestId("create-fv-title"), "六月成片");
    expect(submit).toBeEnabled();
    await user.click(submit);
    expect(createMut.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ asset_id: 90, title: "六月成片" }),
      expect.anything(),
    );
  });

  it("创建 409 冲突时展示错误", async () => {
    const user = userEvent.setup();
    vi.mocked(hooks.useCreateFinalVideo).mockReturnValue(
      mutation({
        isError: true,
        error: Object.assign(new Error("该素材已存在未归档的成片记录（同一素材至多一个活动成片）"), {
          name: "ApiError",
          status: 409,
        }),
      }),
    );
    render(<FinalVideosView />);
    await user.click(screen.getByTestId("toggle-create-final-video"));
    expect(screen.getByTestId("create-fv-error")).toBeInTheDocument();
  });
});
