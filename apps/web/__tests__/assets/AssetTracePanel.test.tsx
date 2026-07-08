import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AssetTracePanel } from "@/components/assets/AssetTracePanel";
import { api } from "@/lib/api";
import type { AssetTrace } from "@/lib/types";

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const TRACE: AssetTrace = {
  asset_id: 7,
  media_kind: "image",
  filename: "a.jpg",
  generated_at: "2026-07-08T00:00:00Z",
  stages: [
    { stage: "scan", title: "扫描与索引", status: "ok", detail: {}, hint: "已入库索引" },
    { stage: "derive", title: "派生文件", status: "ok", detail: {}, hint: "海报已生成" },
    {
      stage: "ai", title: "AI 理解", status: "lagging", detail: {},
      hint: "图片尚无 AI 理解——自动链未触发或 ai 队列积压；可在素材详情手动发起",
    },
    { stage: "review", title: "人工审核", status: "not_applicable", detail: {}, hint: "尚无可审核的结果" },
    { stage: "document", title: "检索文档", status: "lagging", detail: {}, hint: "素材检索文档未建" },
    { stage: "embedding", title: "向量", status: "excluded", detail: {}, hint: "按规则排除" },
  ],
};

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("AssetTracePanel 链路诊断", () => {
  it("默认折叠不请求；展开后渲染六环节与状态标签", async () => {
    const spy = vi.spyOn(api, "getAssetTrace").mockResolvedValue(TRACE);
    const user = userEvent.setup();
    wrap(<AssetTracePanel assetId={7} />);
    expect(spy).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("asset-trace-toggle"));
    await waitFor(() => expect(screen.getByTestId("asset-trace-stages")).toBeInTheDocument());
    expect(spy).toHaveBeenCalledWith(7);

    // 六环节按序渲染
    for (const stage of ["scan", "derive", "ai", "review", "document", "embedding"]) {
      expect(screen.getByTestId(`trace-stage-${stage}`)).toBeInTheDocument();
    }
    // 状态语义映射：lagging=滞后 / excluded=按规则排除（不是失败）
    expect(screen.getByTestId("trace-status-ai")).toHaveTextContent("滞后");
    expect(screen.getByTestId("trace-status-embedding")).toHaveTextContent("按规则排除");
    // hint 直接可见（下一步动作）
    expect(screen.getByText(/可在素材详情手动发起/)).toBeInTheDocument();
  });
});
