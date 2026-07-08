import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReferenceGallery } from "@/components/catalog/ReferenceGallery";
import * as hooks from "@/lib/hooks";

vi.mock("@/lib/hooks", () => ({
  useReferences: vi.fn(),
  useUploadReferences: vi.fn(),
  useReferenceMutations: vi.fn(),
  usePromotionSuggestions: vi.fn(),
  usePromoteReference: vi.fn(),
}));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function q(overrides: Record<string, any> = {}): any {
  return { data: undefined, isLoading: false, isError: false, error: null, ...overrides };
}

const SUGGESTION = {
  family_id: 36,
  code: "FAM-36",
  name_zh: "产品丙",
  active_refs: 0,
  candidates: [
    { asset_id: 101, filename: "a.png", role: "primary", linked_at: null, has_poster: true },
    { asset_id: 102, filename: "b.png", role: "related", linked_at: null, has_poster: false },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hooks.useReferences).mockReturnValue(q({ data: [] }));
  vi.mocked(hooks.useUploadReferences).mockReturnValue(
    q({ mutate: vi.fn(), isPending: false }),
  );
  vi.mocked(hooks.useReferenceMutations).mockReturnValue({} as never);
  vi.mocked(hooks.usePromotionSuggestions).mockReturnValue(q({ data: [SUGGESTION] }));
  vi.mocked(hooks.usePromoteReference).mockReturnValue(
    q({ mutate: vi.fn(), isPending: false }),
  );
});

describe("PromotionZone 参考图提升建议", () => {
  it("family 缺参考图时显示建议并可逐张采纳", async () => {
    const mutate = vi.fn();
    vi.mocked(hooks.usePromoteReference).mockReturnValue(
      q({ mutate, isPending: false }),
    );
    const user = userEvent.setup();
    render(<ReferenceGallery level="family" targetId={36} />);
    expect(screen.getByTestId("ref-promotion-zone")).toBeInTheDocument();
    expect(screen.getByTestId("ref-promotion-list")).toBeInTheDocument();
    await user.click(screen.getByTestId("ref-promote-101"));
    await waitFor(() => expect(mutate).toHaveBeenCalled());
    expect(mutate.mock.calls[0][0]).toEqual({ assetId: 101 });
  });

  it("建议不含本产品时不渲染；无候选时给上传指引", () => {
    vi.mocked(hooks.usePromotionSuggestions).mockReturnValue(q({ data: [] }));
    const { rerender } = render(<ReferenceGallery level="family" targetId={36} />);
    expect(screen.queryByTestId("ref-promotion-zone")).toBeNull();

    vi.mocked(hooks.usePromotionSuggestions).mockReturnValue(
      q({ data: [{ ...SUGGESTION, candidates: [] }] }),
    );
    rerender(<ReferenceGallery level="family" targetId={36} />);
    expect(screen.getByTestId("ref-promotion-empty")).toBeInTheDocument();
  });

  it("variant 级不显示提升区（参考图基准建在 family 上）", () => {
    render(<ReferenceGallery level="variant" targetId={36} />);
    expect(screen.queryByTestId("ref-promotion-zone")).toBeNull();
  });
});
