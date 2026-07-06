import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EntityDetail } from "@/components/catalog/EntityDetail";
import { ApiError } from "@/lib/api";
import * as hooks from "@/lib/hooks";

import { makeFamily, makeSku, makeVariant, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useCatalogNode: vi.fn(),
  useCategories: vi.fn(),
  useCatalogAliases: vi.fn(),
  useFamilies: vi.fn(),
  useVariants: vi.fn(),
  useSkus: vi.fn(),
  useUpdateCategory: vi.fn(),
  useUpdateFamily: vi.fn(),
  useUpdateVariant: vi.fn(),
  useUpdateSku: vi.fn(),
  useSetCatalogStatus: vi.fn(),
  useArchiveCatalogNode: vi.fn(),
  useRestoreCatalogNode: vi.fn(),
  useMergeCatalogNode: vi.fn(),
  useCreateCatalogAlias: vi.fn(),
  useDeleteCatalogAlias: vi.fn(),
  // PR-A2：DetailBody 在 family/variant/sku 层调用 profile（Tab 徽标 + category_id）
  useCatalogProfile: vi.fn(),
  // PR-A2 Gate B：治理 Tab 惰性挂载所需 hooks（默认 stub，切到对应 Tab 才会被调用）
  useReadiness: vi.fn(),
  useEvaluateReadiness: vi.fn(),
  useReadinessPolicies: vi.fn(),
  useCreateReadinessPolicy: vi.fn(),
  useActivateReadinessPolicy: vi.fn(),
  useOnboarding: vi.fn(),
  useOnboardingAction: vi.fn(),
  useConfusions: vi.fn(),
  useCreateConfusionPair: vi.fn(),
  useUpdateConfusionPair: vi.fn(),
  useConfusionPairMutations: vi.fn(),
  useRevisions: vi.fn(),
}));

const updateFamily = mutation();
const setStatus = mutation();
const archive = mutation();
const restore = mutation();
const merge = mutation();
const delAlias = mutation();

function stub() {
  vi.mocked(hooks.useCatalogAliases).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useFamilies).mockReturnValue(query({ data: { items: [], total: 0 } }));
  vi.mocked(hooks.useVariants).mockReturnValue(query({ data: { items: [], total: 0 } }));
  vi.mocked(hooks.useSkus).mockReturnValue(query({ data: { items: [], total: 0 } }));
  vi.mocked(hooks.useUpdateCategory).mockReturnValue(mutation());
  vi.mocked(hooks.useUpdateFamily).mockReturnValue(updateFamily);
  vi.mocked(hooks.useUpdateVariant).mockReturnValue(mutation());
  vi.mocked(hooks.useUpdateSku).mockReturnValue(mutation());
  vi.mocked(hooks.useSetCatalogStatus).mockReturnValue(setStatus);
  vi.mocked(hooks.useArchiveCatalogNode).mockReturnValue(archive);
  vi.mocked(hooks.useRestoreCatalogNode).mockReturnValue(restore);
  vi.mocked(hooks.useMergeCatalogNode).mockReturnValue(merge);
  vi.mocked(hooks.useCreateCatalogAlias).mockReturnValue(mutation());
  vi.mocked(hooks.useDeleteCatalogAlias).mockReturnValue(delAlias);
  // profile 默认无数据（Tab 徽标不显示计数，category_id 走全局属性）
  vi.mocked(hooks.useCatalogProfile).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useCategories).mockReturnValue(query({ data: { items: [], total: 0 } }));
  // Gate B 治理 hooks 默认 stub（面板惰性挂载，默认 basic Tab 下不会被调用）
  vi.mocked(hooks.useReadiness).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useEvaluateReadiness).mockReturnValue(mutation());
  vi.mocked(hooks.useReadinessPolicies).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useCreateReadinessPolicy).mockReturnValue(mutation());
  vi.mocked(hooks.useActivateReadinessPolicy).mockReturnValue(mutation());
  vi.mocked(hooks.useOnboarding).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useOnboardingAction).mockReturnValue(mutation());
  vi.mocked(hooks.useConfusions).mockReturnValue(query({ data: undefined }));
  vi.mocked(hooks.useCreateConfusionPair).mockReturnValue(mutation());
  vi.mocked(hooks.useUpdateConfusionPair).mockReturnValue(mutation());
  vi.mocked(hooks.useConfusionPairMutations).mockReturnValue({
    archive: mutation(),
    restore: mutation(),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
  vi.mocked(hooks.useRevisions).mockReturnValue(query({ data: undefined }));
}

beforeEach(() => {
  vi.clearAllMocks();
  [updateFamily, setStatus, archive, restore, merge, delAlias].forEach((m) => m.mutate.mockReset());
  stub();
});

describe("EntityDetail", () => {
  it("加载态显示骨架", () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ isLoading: true }));
    render(<EntityDetail selected={{ level: "family", id: 10 }} onSelect={vi.fn()} />);
    expect(screen.getByTestId("detail-loading")).toBeInTheDocument();
  });

  it("渲染 family 详情：名称/编码/层级/状态", () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeFamily() }));
    render(<EntityDetail selected={{ level: "family", id: 10 }} onSelect={vi.fn()} />);
    expect(screen.getByTestId("detail-name")).toHaveTextContent("示例产品");
    expect(screen.getByTestId("catalog-level-family")).toBeInTheDocument();
    expect(screen.getByTestId("catalog-status-active")).toBeInTheDocument();
  });

  it("编辑并保存触发更名（更名不改编码）", async () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeFamily() }));
    const user = userEvent.setup();
    render(<EntityDetail selected={{ level: "family", id: 10 }} onSelect={vi.fn()} />);
    await user.click(screen.getByTestId("edit-node"));
    const zh = screen.getByTestId("rename-zh");
    await user.clear(zh);
    await user.type(zh, "改名后产品");
    await user.click(screen.getByTestId("save-rename"));
    expect(updateFamily.mutate).toHaveBeenCalledWith(
      { id: 10, req: expect.objectContaining({ name_zh: "改名后产品" }) },
      expect.anything(),
    );
  });

  it("family 编辑表单含归属分类下拉，保存携带 category_id（激活前置条件可在 UI 完成）", async () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeFamily({ category_id: null }) }));
    vi.mocked(hooks.useCategories).mockReturnValue(
      query({
        data: {
          items: [
            { id: 7, code: "c7", name_zh: "键盘类", name_en: null, description: null,
              status: "active", sort_order: 0, created_at: "", updated_at: "", archived_at: null },
          ],
          total: 1,
        },
      }),
    );
    const user = userEvent.setup();
    render(<EntityDetail selected={{ level: "family", id: 10 }} onSelect={vi.fn()} />);
    // 未归属时基本信息给出提示
    expect(screen.getByTestId("detail-category")).toHaveTextContent("未归属");
    await user.click(screen.getByTestId("edit-node"));
    await user.selectOptions(screen.getByTestId("rename-category"), "7");
    await user.click(screen.getByTestId("save-rename"));
    expect(updateFamily.mutate).toHaveBeenCalledWith(
      { id: 10, req: expect.objectContaining({ category_id: 7 }) },
      expect.anything(),
    );
  });

  it("draft family 显示「启用」按钮并置为 active", async () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeFamily({ status: "draft" }) }));
    const user = userEvent.setup();
    render(<EntityDetail selected={{ level: "family", id: 10 }} onSelect={vi.fn()} />);
    await user.click(screen.getByTestId("status-to-active"));
    expect(setStatus.mutate).toHaveBeenCalledWith({ level: "family", id: 10, status: "active" });
  });

  it("draft variant 也可切换状态（四层统一生命周期）", async () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeVariant({ status: "draft" }) }));
    const user = userEvent.setup();
    render(<EntityDetail selected={{ level: "variant", id: 20 }} onSelect={vi.fn()} />);
    await user.click(screen.getByTestId("status-to-active"));
    expect(setStatus.mutate).toHaveBeenCalledWith({ level: "variant", id: 20, status: "active" });
  });

  it("归档需确认后调用 archive", async () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeFamily() }));
    const user = userEvent.setup();
    render(<EntityDetail selected={{ level: "family", id: 10 }} onSelect={vi.fn()} />);
    await user.click(screen.getByTestId("archive-node"));
    // 确认对话框（确认按钮文案「确认归档」以与触发按钮「归档」区分）
    await user.click(screen.getByRole("button", { name: "确认归档" }));
    expect(archive.mutate).toHaveBeenCalledWith(
      { level: "family", id: 10 },
      expect.anything(),
    );
  });

  it("已归档节点只读并提供恢复", async () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeFamily({ status: "archived" }) }));
    const user = userEvent.setup();
    render(<EntityDetail selected={{ level: "family", id: 10 }} onSelect={vi.fn()} />);
    expect(screen.getByTestId("readonly-banner")).toBeInTheDocument();
    expect(screen.queryByTestId("edit-node")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("restore-node"));
    expect(restore.mutate).toHaveBeenCalledWith({ level: "family", id: 10 });
  });

  it("合并对话框选目标并确认调用 merge", async () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeVariant() }));
    // 合并候选：同 family 的另一个型号
    vi.mocked(hooks.useVariants).mockReturnValue(
      query({ data: { items: [makeVariant({ id: 21, name_zh: "另一型号", code: "var-21" })], total: 1 } }),
    );
    const user = userEvent.setup();
    render(<EntityDetail selected={{ level: "variant", id: 20 }} onSelect={vi.fn()} />);
    await user.click(screen.getByTestId("open-merge"));
    await user.selectOptions(screen.getByTestId("merge-target"), "21");
    await user.click(screen.getByTestId("submit-merge"));
    expect(merge.mutate).toHaveBeenCalledWith(
      { level: "variant", id: 20, req: { target_id: 21 } },
      expect.anything(),
    );
  });

  it("409 冲突显示可读中文提示", () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeFamily() }));
    vi.mocked(hooks.useUpdateFamily).mockReturnValue(
      mutation({ error: new ApiError(409, "code 已存在") }),
    );
    render(<EntityDetail selected={{ level: "family", id: 10 }} onSelect={vi.fn()} />);
    expect(screen.getByTestId("catalog-error")).toHaveTextContent("code 已存在");
  });

  it("category 无合并按钮", () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(
      query({ data: { id: 1, code: "c", name_zh: "分类", name_en: null, status: "active" } }),
    );
    render(<EntityDetail selected={{ level: "category", id: 1 }} onSelect={vi.fn()} />);
    expect(screen.queryByTestId("open-merge")).not.toBeInTheDocument();
  });

  it("子级列表渲染并可选中", async () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeFamily() }));
    vi.mocked(hooks.useVariants).mockReturnValue(
      query({ data: { items: [makeVariant({ id: 20, name_zh: "型号X" })], total: 1 } }),
    );
    vi.mocked(hooks.useSkus).mockReturnValue(
      query({ data: { items: [makeSku({ id: 30, name_zh: "SKUY", variant_id: null })], total: 1 } }),
    );
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<EntityDetail selected={{ level: "family", id: 10 }} onSelect={onSelect} />);
    const list = screen.getByTestId("child-list");
    expect(within(list).getByTestId("child-variant-20")).toHaveTextContent("型号X");
    await user.click(within(list).getByTestId("child-sku-30"));
    expect(onSelect).toHaveBeenCalledWith({ level: "sku", id: 30 });
  });

  it("别名空态提示暂无别名", () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeFamily() }));
    render(<EntityDetail selected={{ level: "family", id: 10 }} onSelect={vi.fn()} />);
    expect(screen.getByTestId("alias-empty")).toBeInTheDocument();
  });

  it("family 层显示 Gate B 治理 Tab 且惰性挂载（切到才请求）", async () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeFamily() }));
    const user = userEvent.setup();
    render(<EntityDetail selected={{ level: "family", id: 10 }} onSelect={vi.fn()} />);
    const tabs = screen.getByTestId("detail-tabs");
    expect(within(tabs).getByTestId("detail-tab-readiness")).toBeInTheDocument();
    expect(within(tabs).getByTestId("detail-tab-onboarding")).toBeInTheDocument();
    expect(within(tabs).getByTestId("detail-tab-confusions")).toBeInTheDocument();
    expect(within(tabs).getByTestId("detail-tab-history")).toBeInTheDocument();
    // 默认 basic Tab：治理面板未挂载、hooks 未被调用（惰性）
    expect(screen.queryByTestId("detail-tabpanel-readiness")).not.toBeInTheDocument();
    expect(hooks.useReadiness).not.toHaveBeenCalled();
    // 切到完整度 Tab 后面板挂载
    await user.click(screen.getByTestId("detail-tab-readiness"));
    expect(screen.getByTestId("detail-tabpanel-readiness")).toBeInTheDocument();
    expect(hooks.useReadiness).toHaveBeenCalled();
  });

  it("切到入驻审核 Tab 显示权限提示（无用户权限体系）", async () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(query({ data: makeFamily() }));
    const user = userEvent.setup();
    render(<EntityDetail selected={{ level: "family", id: 10 }} onSelect={vi.fn()} />);
    await user.click(screen.getByTestId("detail-tab-onboarding"));
    expect(screen.getByTestId("detail-tabpanel-onboarding")).toBeInTheDocument();
    expect(screen.getByTestId("onboarding-permission-notice")).toHaveTextContent(
      "当前为可信内网人工审核，尚未启用用户权限。",
    );
  });

  it("category 层不显示治理 Tab", () => {
    vi.mocked(hooks.useCatalogNode).mockReturnValue(
      query({ data: { id: 1, code: "c", name_zh: "分类", name_en: null, status: "active" } }),
    );
    render(<EntityDetail selected={{ level: "category", id: 1 }} onSelect={vi.fn()} />);
    expect(screen.queryByTestId("detail-tab-readiness")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-tab-onboarding")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-tab-confusions")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-tab-history")).not.toBeInTheDocument();
  });
});
