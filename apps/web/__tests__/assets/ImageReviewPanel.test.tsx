import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImageReviewPanel } from "@/components/assets/ImageReviewPanel";
import * as hooks from "@/lib/hooks";

vi.mock("@/lib/hooks", () => ({
  useAssetImageAnalysis: vi.fn(),
  useImageReviewAction: vi.fn(),
}));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function query(overrides: Record<string, any> = {}): any {
  return { data: undefined, isLoading: false, isError: false, error: null, ...overrides };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function mutation(overrides: Record<string, any> = {}): any {
  return { mutate: vi.fn(), isPending: false, isError: false, error: null, ...overrides };
}

const VIEW = {
  asset_id: 7,
  ai_status: "completed",
  ai_result: { one_line: "AI 描述：LED 屏产品图", search_keywords: ["LED屏", "产品图"] },
  review_status: "unreviewed",
  lock_version: 0,
  effective_source: "ai",
  effective_result: { one_line: "AI 描述：LED 屏产品图", search_keywords: ["LED屏", "产品图"] },
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ImageReviewPanel 图片审核", () => {
  it("未审核：展示 AI 结果与确认/修改/驳回操作", async () => {
    const user = userEvent.setup();
    const mut = mutation();
    vi.mocked(hooks.useAssetImageAnalysis).mockReturnValue(query({ data: VIEW }));
    vi.mocked(hooks.useImageReviewAction).mockReturnValue(mut);
    render(<ImageReviewPanel assetId={7} />);
    expect(screen.getByTestId("image-review-one-line")).toHaveTextContent("AI 描述");
    expect(screen.getByTestId("image-review-status")).toHaveTextContent("未审核");
    await user.click(screen.getByTestId("image-review-confirm"));
    expect(mut.mutate).toHaveBeenCalledWith({ action: "confirm", lock_version: 0, confirmed_result: undefined });
  });

  it("修改：编辑一句话描述后携带完整结果提交", async () => {
    const user = userEvent.setup();
    const mut = mutation();
    vi.mocked(hooks.useAssetImageAnalysis).mockReturnValue(query({ data: VIEW }));
    vi.mocked(hooks.useImageReviewAction).mockReturnValue(mut);
    render(<ImageReviewPanel assetId={7} />);
    await user.click(screen.getByTestId("image-review-modify"));
    const box = screen.getByTestId("image-review-draft");
    await user.clear(box);
    await user.type(box, "人工修正描述");
    await user.click(screen.getByTestId("image-review-save"));
    const call = mut.mutate.mock.calls[0][0];
    expect(call.action).toBe("modify");
    expect(call.confirmed_result.one_line).toBe("人工修正描述");
    expect(call.confirmed_result.search_keywords).toEqual(["LED屏", "产品图"]);
  });

  it("已确认：显示人工生效与重开入口", () => {
    vi.mocked(hooks.useAssetImageAnalysis).mockReturnValue(
      query({
        data: {
          ...VIEW, review_status: "confirmed", lock_version: 1,
          effective_source: "human", reviewer_label: "审核员",
        },
      }),
    );
    vi.mocked(hooks.useImageReviewAction).mockReturnValue(mutation());
    render(<ImageReviewPanel assetId={7} />);
    expect(screen.getByTestId("image-review-status")).toHaveTextContent("已确认");
    expect(screen.getByText(/人工结果/)).toBeInTheDocument();
    expect(screen.getByTestId("image-review-reopen")).toBeInTheDocument();
  });

  it("已驳回：明确提示不进搜索，不伪造状态", () => {
    vi.mocked(hooks.useAssetImageAnalysis).mockReturnValue(
      query({
        data: {
          ...VIEW, review_status: "rejected", lock_version: 2,
          effective_source: "rejected", effective_result: null,
        },
      }),
    );
    vi.mocked(hooks.useImageReviewAction).mockReturnValue(mutation());
    render(<ImageReviewPanel assetId={7} />);
    expect(screen.getByTestId("image-review-rejected-note")).toHaveTextContent("不会进入搜索");
  });

  it("无 AI 结果：如实空态", () => {
    vi.mocked(hooks.useAssetImageAnalysis).mockReturnValue(
      query({
        data: {
          ...VIEW, ai_status: null, ai_result: null,
          effective_source: "none", effective_result: null,
        },
      }),
    );
    vi.mocked(hooks.useImageReviewAction).mockReturnValue(mutation());
    render(<ImageReviewPanel assetId={7} />);
    expect(screen.getByTestId("image-review-empty")).toBeInTheDocument();
  });
});
