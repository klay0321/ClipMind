import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AssetLegacyPanel } from "@/components/usage-evidence/AssetLegacyPanel";
import * as hooks from "@/lib/hooks";

import { makeEvidence, makeLegacySummary, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useAssetLegacySummary: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hooks.useAssetLegacySummary).mockReturnValue(
    query({ data: makeLegacySummary() }),
  );
});

describe("AssetLegacyPanel", () => {
  it("accepted 状态显示为历史上用过（次数未知），绝不显示已使用 N 次", () => {
    render(<AssetLegacyPanel assetId={10} />);
    expect(screen.getByTestId("asset-legacy-state")).toHaveTextContent(
      "历史上用过（次数未知）",
    );
    expect(screen.queryByText(/已使用 1 次/)).toBeNull();
    expect(screen.queryByText(/已使用 \d+ 次/)).toBeNull();
  });

  it("说明弱证据不计入正式使用统计", () => {
    render(<AssetLegacyPanel assetId={10} />);
    expect(screen.getByText(/不计入正式使用统计/)).toBeInTheDocument();
  });

  it("无任何证据时不渲染面板", () => {
    vi.mocked(hooks.useAssetLegacySummary).mockReturnValue(
      query({
        data: makeLegacySummary({
          legacy_usage_state: "no_legacy_evidence",
          accepted_count: 0,
          pending_count: 0,
          rejected_count: 0,
          conflict_count: 0,
          evidences: [],
        }),
      }),
    );
    render(<AssetLegacyPanel assetId={10} />);
    expect(screen.queryByTestId("asset-legacy-panel")).toBeNull();
  });

  it("pending 状态显示待审核", () => {
    vi.mocked(hooks.useAssetLegacySummary).mockReturnValue(
      query({
        data: makeLegacySummary({
          legacy_usage_state: "legacy_evidence_pending",
          accepted_count: 0,
          pending_count: 2,
          evidences: [makeEvidence(), makeEvidence({ id: 12 })],
        }),
      }),
    );
    render(<AssetLegacyPanel assetId={10} />);
    expect(screen.getByTestId("asset-legacy-state")).toHaveTextContent("历史证据待审核");
    expect(screen.getByTestId("asset-legacy-list").children).toHaveLength(2);
  });

  it("conflict 状态优先显示冲突", () => {
    vi.mocked(hooks.useAssetLegacySummary).mockReturnValue(
      query({
        data: makeLegacySummary({
          legacy_usage_state: "legacy_evidence_conflict",
          conflict_count: 1,
        }),
      }),
    );
    render(<AssetLegacyPanel assetId={10} />);
    expect(screen.getByTestId("asset-legacy-state")).toHaveTextContent("历史证据冲突");
  });
});
