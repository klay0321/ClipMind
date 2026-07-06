import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProductLinkPanel } from "@/components/product-media/ProductLinkPanel";
import { api } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const SUMMARY = [
  {
    family_id: 1, code: "FAM-A", name_zh: "产品甲", status: "active",
    onboarding_status: "approved", variant_count: 0, reference_count: 1,
    image_count: 2, video_count: 1, shot_link_count: 1, confirmed_usage_count: 0,
  },
];

const LINK = {
  id: 11, asset_id: 5, shot_id: null, family_id: 1, family_name: "产品甲",
  family_code: "FAM-A", variant_id: null, variant_name: null, role: "primary",
  origin: "manual", actor_label: "local-reviewer", note: null,
  created_at: "2026-07-04T00:00:00Z", updated_at: "2026-07-04T00:00:00Z",
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "pmSummary").mockResolvedValue(SUMMARY as never);
  vi.spyOn(api, "pmSuggestions").mockResolvedValue([
    {
      family_id: 1, family_name: "产品甲", family_code: "FAM-A",
      suggestion_type: "filename", matched_text: "FAM-A", matched_in: "文件名",
      origin_on_confirm: "path_or_filename_confirmed",
    },
  ] as never);
});

describe("ProductLinkPanel（Asset 模式）", () => {
  it("展示主产品/来源徽标，支持解除与手动绑定", async () => {
    vi.spyOn(api, "pmAssetLinks").mockResolvedValue([LINK] as never);
    const del = vi.spyOn(api, "pmDeleteLink").mockResolvedValue(undefined as never);
    const user = userEvent.setup();
    wrap(<ProductLinkPanel targetType="asset" targetId={5} />);
    await waitFor(() => expect(screen.getByTestId("link-row-11")).toBeInTheDocument());
    expect(screen.getByTestId("link-row-11")).toHaveTextContent("主产品");
    expect(screen.getByTestId("link-row-11")).toHaveTextContent("人工");
    expect(screen.getByText(/视频级产品默认被该视频全部镜头继承/)).toBeInTheDocument();
    await user.click(screen.getByTestId("panel-unlink-11"));
    expect(del).toHaveBeenCalledWith(11);
  });

  it("确定性候选需人工点击确认才创建关系（带候选来源）", async () => {
    vi.spyOn(api, "pmAssetLinks").mockResolvedValue([] as never);
    const create = vi.spyOn(api, "pmCreateLink").mockResolvedValue(LINK as never);
    const user = userEvent.setup();
    wrap(<ProductLinkPanel targetType="asset" targetId={5} />);
    await waitFor(() =>
      expect(screen.getByTestId("panel-suggestion-1-filename")).toBeInTheDocument(),
    );
    expect(create).not.toHaveBeenCalled(); // 渲染候选绝不自动写入
    await user.click(screen.getByTestId("panel-suggestion-1-filename"));
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        family_id: 1,
        origin: "path_or_filename_confirmed",
        target_type: "asset",
      }),
    );
  });
});

describe("ProductLinkPanel（Shot 模式）", () => {
  it("区分继承自视频与本镜头独立设置；历史代次标记", async () => {
    vi.spyOn(api, "pmShotLinks").mockResolvedValue({
      shot_id: 9, generation: 2, is_historical: true,
      effective_source: "shot_override",
      own: [{ ...LINK, id: 21, shot_id: 9, asset_id: null }],
      inherited: [{ ...LINK, id: 22 }],
      effective: [{ ...LINK, id: 21, shot_id: 9, asset_id: null }],
    } as never);
    wrap(<ProductLinkPanel targetType="shot" targetId={9} />);
    await waitFor(() =>
      expect(screen.getByTestId("effective-source")).toHaveTextContent(
        "本镜头独立设置（覆盖视频级）",
      ),
    );
    expect(screen.getByText(/历史代次 g2/)).toBeInTheDocument();
    expect(screen.getByText(/查看视频级关系（被本镜头覆盖）/)).toBeInTheDocument();
  });

  it("继承态显示继承自视频", async () => {
    vi.spyOn(api, "pmShotLinks").mockResolvedValue({
      shot_id: 9, generation: 1, is_historical: false,
      effective_source: "asset_inherited",
      own: [], inherited: [LINK], effective: [LINK],
    } as never);
    wrap(<ProductLinkPanel targetType="shot" targetId={9} />);
    await waitFor(() =>
      expect(screen.getByTestId("effective-source")).toHaveTextContent("继承自视频"),
    );
    // 继承的视频级关系不给"解除"（只能在 Asset 上改）
    expect(screen.queryByTestId("panel-unlink-11")).toBeNull();
  });
});
