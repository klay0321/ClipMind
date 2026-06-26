import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IndexStatusIndicator } from "@/components/search/IndexStatusIndicator";
import * as hooks from "@/lib/hooks";
import type { SearchIndexStatus } from "@/lib/types";

import { query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useSearchIndexStatus: vi.fn(),
}));

function status(o: Partial<SearchIndexStatus> = {}): SearchIndexStatus {
  return {
    total_shots: 12,
    indexed_documents: 12,
    excluded_documents: 0,
    completed_embeddings: 12,
    degraded_embeddings: 0,
    failed_embeddings: 0,
    pending_embeddings: 0,
    current_embedding_version: "e5@v1",
    embedding_version_matched: 12,
    embedding_version_mismatched: 0,
    stale_documents: 0,
    last_indexed_at: null,
    provider_healthy: true,
    provider_detail: "",
    ...o,
  };
}

beforeEach(() => {
  vi.mocked(hooks.useSearchIndexStatus).mockReturnValue(query({ data: status() }));
});

describe("IndexStatusIndicator", () => {
  it("加载中显示检测中，不谎报正常", () => {
    vi.mocked(hooks.useSearchIndexStatus).mockReturnValue(query({ isLoading: true }));
    render(<IndexStatusIndicator />);
    expect(screen.getByTestId("index-status")).toHaveTextContent("检测中");
  });

  it("无数据/错误显示状态未知，不写正常", () => {
    vi.mocked(hooks.useSearchIndexStatus).mockReturnValue(query({ isError: true }));
    render(<IndexStatusIndicator />);
    expect(screen.getByTestId("index-status")).toHaveTextContent("状态未知");
    expect(screen.getByTestId("index-status")).not.toHaveTextContent("正常");
  });

  it("全就绪显示正常，展开见详细数字", async () => {
    const user = userEvent.setup();
    render(<IndexStatusIndicator />);
    expect(screen.getByTestId("index-status")).toHaveTextContent("正常");
    await user.click(screen.getByRole("button"));
    const detail = screen.getByTestId("index-status-detail");
    expect(detail).toHaveTextContent("总镜头");
    expect(detail).toHaveTextContent("e5@v1");
  });

  it("待嵌入显示建设中", () => {
    vi.mocked(hooks.useSearchIndexStatus).mockReturnValue(query({ data: status({ pending_embeddings: 4 }) }));
    render(<IndexStatusIndicator />);
    expect(screen.getByTestId("index-status")).toHaveTextContent("建设中");
  });

  it("嵌入失败显示异常", () => {
    vi.mocked(hooks.useSearchIndexStatus).mockReturnValue(query({ data: status({ failed_embeddings: 2 }) }));
    render(<IndexStatusIndicator />);
    expect(screen.getByTestId("index-status")).toHaveTextContent("异常");
  });
});
