import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GroupedReview } from "@/components/product-media/GroupedReview";
import { api } from "@/lib/api";
import type { FamilyMediaSummary } from "@/lib/types";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const FAMILIES = [
  { family_id: 1, code: "FAM-A", name_zh: "产品甲", status: "active" },
] as unknown as FamilyMediaSummary[];

const GROUPS = {
  kind: "image",
  group_by: "suggested_family",
  total_items: 5,
  truncated: false,
  groups: [
    {
      key: "family:1", label: "产品甲", count: 2,
      meta: { family_id: 1, family_code: "FAM-A", suggestion_type: "path" },
      targets: [{ target_type: "asset", target_id: 1 }],
      preview: [{ target_type: "asset", target_id: 1, filename: "a.png" }],
      suggested: [
        {
          family_id: 1, family_name: "产品甲", family_code: "FAM-A",
          suggestion_type: "path", matched_text: "FAM-A", matched_in: "目录名",
          origin_on_confirm: "path_or_filename_confirmed",
        },
      ],
    },
    {
      key: "none", label: "无候选", count: 3, meta: {},
      targets: [{ target_type: "asset", target_id: 2 }],
      preview: [{ target_type: "asset", target_id: 2, filename: "b.png" }],
      suggested: [],
    },
  ],
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "pmUnassignedGroups").mockResolvedValue(GROUPS as never);
});

describe("GroupedReview 无候选守卫（200 项误绑事故回归）", () => {
  it("有候选组保留整组绑定；无候选组移除绑定控件并给出替代路径", async () => {
    const user = userEvent.setup();
    wrap(<GroupedReview families={FAMILIES} />);
    await waitFor(() => expect(screen.getByTestId("grouped-review")).toBeInTheDocument());

    // 有候选组：展开后有绑定控件
    await user.click(screen.getByTestId("group-toggle-family:1"));
    expect(screen.getByTestId("group-confirm-family:1")).toBeInTheDocument();

    // 无候选组：展开后绝无绑定控件，只有守卫提示
    await user.click(screen.getByTestId("group-toggle-none"));
    expect(screen.queryByTestId("group-confirm-none")).toBeNull();
    expect(screen.queryByTestId("group-family-none")).toBeNull();
    const guard = screen.getByTestId("group-no-suggestion-none");
    expect(guard).toHaveTextContent("不提供整组绑定");
    expect(guard).toHaveTextContent("以图搜图");
  });
});
