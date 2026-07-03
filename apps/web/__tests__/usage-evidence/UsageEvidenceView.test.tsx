import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UsageEvidenceView } from "@/components/usage-evidence/UsageEvidenceView";
import * as hooks from "@/lib/hooks";

import { makeEvidence, makePreview, makeRule, makeRun, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useLegacyRules: vi.fn(),
  useCreateLegacyRule: vi.fn(),
  useUpdateLegacyRule: vi.fn(),
  useLegacyRuleAction: vi.fn(),
  useSourceDirectories: vi.fn(),
  usePreviewLegacyImport: vi.fn(),
  useCreateLegacyImport: vi.fn(),
  useLegacyImports: vi.fn(),
  useCancelLegacyImport: vi.fn(),
  useLegacyEvidence: vi.fn(),
  useLegacyEvidenceAction: vi.fn(),
  useLegacyBulkReview: vi.fn(),
  useLegacyEvidenceEvents: vi.fn(),
}));

const evidenceActionMut = mutation();
const bulkMut = mutation();
const previewMut = mutation();
const importMut = mutation();

function listData(items: ReturnType<typeof makeEvidence>[]) {
  return query({ data: { items, total: items.length, page: 1, page_size: 20 } });
}

beforeEach(() => {
  vi.clearAllMocks();
  evidenceActionMut.mutate.mockReset();
  bulkMut.mutate.mockReset();
  previewMut.mutate.mockReset();
  importMut.mutate.mockReset();
  bulkMut.data = undefined;
  vi.mocked(hooks.useLegacyRules).mockReturnValue(
    query({ data: { items: [makeRule()], total: 1 } }),
  );
  vi.mocked(hooks.useCreateLegacyRule).mockReturnValue(mutation());
  vi.mocked(hooks.useUpdateLegacyRule).mockReturnValue(mutation());
  vi.mocked(hooks.useLegacyRuleAction).mockReturnValue(mutation());
  vi.mocked(hooks.useSourceDirectories).mockReturnValue(
    query({ data: [{ id: 1, name: "素材根" }] }),
  );
  vi.mocked(hooks.usePreviewLegacyImport).mockReturnValue(previewMut);
  vi.mocked(hooks.useCreateLegacyImport).mockReturnValue(importMut);
  vi.mocked(hooks.useLegacyImports).mockReturnValue(
    query({ data: { items: [makeRun()], total: 1 } }),
  );
  vi.mocked(hooks.useCancelLegacyImport).mockReturnValue(mutation());
  vi.mocked(hooks.useLegacyEvidence).mockReturnValue(listData([makeEvidence()]));
  vi.mocked(hooks.useLegacyEvidenceAction).mockReturnValue(evidenceActionMut);
  vi.mocked(hooks.useLegacyBulkReview).mockReturnValue(bulkMut);
  vi.mocked(hooks.useLegacyEvidenceEvents).mockReturnValue(query({ data: { items: [] } }));
});

describe("UsageEvidenceView 待审核", () => {
  it("默认展示待审核 Tab + 固定接受警示文案", () => {
    render(<UsageEvidenceView />);
    expect(screen.getByTestId("evidence-table")).toBeInTheDocument();
    expect(screen.getByTestId("accept-warning")).toHaveTextContent(
      "接受历史证据不等于确认使用次数，也不等于确认对应成片或具体镜头",
    );
  });

  it("绝不把弱证据显示成已使用次数", () => {
    render(<UsageEvidenceView />);
    expect(screen.queryByText(/已使用 1 次/)).toBeNull();
  });

  it("单条接受调用 accept 动作", async () => {
    const user = userEvent.setup();
    render(<UsageEvidenceView />);
    await user.click(screen.getByTestId("accept-evidence-11"));
    expect(evidenceActionMut.mutate).toHaveBeenCalledWith({ id: 11, action: "accept" });
  });

  it("批量按钮未勾选时禁用；勾选后携带显式 id 列表", async () => {
    const user = userEvent.setup();
    render(<UsageEvidenceView />);
    const bulkAccept = screen.getByTestId("bulk-accept-button");
    expect(bulkAccept).toBeDisabled();
    await user.click(screen.getByTestId("select-evidence-11"));
    expect(bulkAccept).toBeEnabled();
    await user.click(bulkAccept);
    expect(bulkMut.mutate).toHaveBeenCalledWith(
      { action: "bulk-accept", payload: { evidence_ids: [11] } },
      expect.anything(),
    );
  });

  it("展示证据来源规则版本（快照冻结）", () => {
    vi.mocked(hooks.useLegacyEvidence).mockReturnValue(
      listData([makeEvidence({ rule_version: 3 })]),
    );
    render(<UsageEvidenceView />);
    expect(screen.getByTestId("evidence-rule-version-11")).toHaveTextContent("v3");
  });

  it("对照列展示正式使用（confirmed 独立于证据）", () => {
    vi.mocked(hooks.useLegacyEvidence).mockReturnValue(
      listData([makeEvidence({ confirmed_usage_count: 2 })]),
    );
    render(<UsageEvidenceView />);
    expect(screen.getByTestId("evidence-row-11")).toHaveTextContent("已确认 2 次");
  });
});

describe("UsageEvidenceView 规则管理", () => {
  it("规则行展示受控匹配条件；无正则输入", async () => {
    const user = userEvent.setup();
    render(<UsageEvidenceView />);
    await user.click(screen.getByTestId("tab-rules"));
    const row = screen.getByTestId("rule-row-1");
    expect(screen.getByTestId("rule-version-1")).toHaveTextContent("v1");
    expect(row).toHaveTextContent("目录名");
    expect(row).toHaveTextContent("等于");
    expect(row).toHaveTextContent("historical-marker");
    expect(screen.getByText(/不支持自由正则表达式/)).toBeInTheDocument();
  });

  it("新建规则表单只提供白名单下拉", async () => {
    const user = userEvent.setup();
    render(<UsageEvidenceView />);
    await user.click(screen.getByTestId("tab-rules"));
    await user.click(screen.getByTestId("create-rule-button"));
    const target = screen.getByTestId("rule-target-select");
    const operator = screen.getByTestId("rule-operator-select");
    expect(target.querySelectorAll("option")).toHaveLength(5);
    expect(operator.querySelectorAll("option")).toHaveLength(4);
    expect(screen.getByTestId("rule-form-submit")).toBeDisabled();
  });
});

describe("UsageEvidenceView 导入任务", () => {
  it("运行列表展示状态与计数", async () => {
    const user = userEvent.setup();
    render(<UsageEvidenceView />);
    await user.click(screen.getByTestId("tab-imports"));
    const row = screen.getByTestId("import-run-3");
    expect(row).toHaveTextContent("已完成");
    expect(row).toHaveTextContent("40");
    expect(row).toHaveTextContent("5");
  });

  it("预览后展示固定导入警示，确认才发起导入", async () => {
    const user = userEvent.setup();
    previewMut.mutate.mockImplementation(
      (_payload: unknown, opts?: { onSuccess?: (p: unknown) => void }) =>
        opts?.onSuccess?.(makePreview()),
    );
    render(<UsageEvidenceView />);
    await user.click(screen.getByTestId("tab-imports"));
    await user.click(screen.getByTestId("open-preview-button"));
    expect(screen.queryByTestId("import-warning")).toBeNull();
    await user.click(screen.getByTestId("run-preview-button"));
    expect(screen.getByTestId("preview-result")).toBeInTheDocument();
    expect(screen.getByTestId("import-warning")).toHaveTextContent(
      "本操作只创建历史使用证据，不会修改文件、不会创建正式使用次数、不会绑定最终成片",
    );
    expect(importMut.mutate).not.toHaveBeenCalled();
    await user.click(screen.getByTestId("confirm-import-button"));
    expect(importMut.mutate).toHaveBeenCalledTimes(1);
  });
});

describe("UsageEvidenceView 已审核", () => {
  it("已审核 Tab 支持筛选与重置", async () => {
    const user = userEvent.setup();
    vi.mocked(hooks.useLegacyEvidence).mockReturnValue(
      listData([makeEvidence({ review_status: "accepted" })]),
    );
    render(<UsageEvidenceView />);
    await user.click(screen.getByTestId("tab-reviewed"));
    expect(screen.getByTestId("reviewed-filter")).toBeInTheDocument();
    await user.click(screen.getByTestId("reset-evidence-11"));
    expect(evidenceActionMut.mutate).toHaveBeenCalledWith({ id: 11, action: "reset" });
  });
});
