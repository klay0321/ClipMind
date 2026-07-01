import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateWizard } from "@/components/catalog/CreateWizard";
import * as hooks from "@/lib/hooks";

import { makeCategory, makeFamily, makeSku, makeVariant, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useCategories: vi.fn(),
  useCreateCategory: vi.fn(),
  useCreateFamily: vi.fn(),
  useCreateVariant: vi.fn(),
  useCreateSku: vi.fn(),
  useCreateCatalogAlias: vi.fn(),
  useSetCatalogStatus: vi.fn(),
}));

const createCategory = mutation();
const createFamily = mutation();
const createVariant = mutation();
const createSku = mutation();
const createAlias = mutation();
const setStatus = mutation();

// mutate(req, opts) → 触发 onSuccess(returnedEntity) 以驱动向导前进
function wireSuccess(m: ReturnType<typeof mutation>, entity: unknown) {
  m.mutate.mockImplementation((_req: unknown, opts?: { onSuccess?: (e: unknown) => void }) => {
    opts?.onSuccess?.(entity);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  createCategory.mutate.mockReset();
  createFamily.mutate.mockReset();
  createVariant.mutate.mockReset();
  createSku.mutate.mockReset();
  createAlias.mutate.mockReset();
  setStatus.mutate.mockReset();
  vi.mocked(hooks.useCategories).mockReturnValue(query({ data: { items: [], total: 0 } }));
  vi.mocked(hooks.useCreateCategory).mockReturnValue(createCategory);
  vi.mocked(hooks.useCreateFamily).mockReturnValue(createFamily);
  vi.mocked(hooks.useCreateVariant).mockReturnValue(createVariant);
  vi.mocked(hooks.useCreateSku).mockReturnValue(createSku);
  vi.mocked(hooks.useCreateCatalogAlias).mockReturnValue(createAlias);
  vi.mocked(hooks.useSetCatalogStatus).mockReturnValue(setStatus);
  wireSuccess(createCategory, makeCategory({ id: 7 }));
  wireSuccess(createFamily, makeFamily({ id: 10 }));
  wireSuccess(createVariant, makeVariant({ id: 20 }));
  wireSuccess(createSku, makeSku({ id: 30 }));
  wireSuccess(createAlias, {});
  wireSuccess(setStatus, makeFamily({ id: 10, status: "active" }));
});

describe("CreateWizard", () => {
  it("暂不分类 → 创建产品 → 跳过型号/SKU → 保存草稿（不启用）", async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    render(<CreateWizard open onClose={vi.fn()} onCreated={onCreated} />);

    // step1: 暂不分类默认选中，直接下一步
    await user.click(screen.getByTestId("wizard-next-category"));
    expect(createCategory.mutate).not.toHaveBeenCalled();

    // step2: 填产品名并创建
    await user.type(screen.getByTestId("wizard-family-name"), "新产品");
    await user.click(screen.getByTestId("wizard-next-family"));
    expect(createFamily.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ name_zh: "新产品", category_id: null }),
      expect.anything(),
    );

    // step3 跳过型号
    await user.click(screen.getByTestId("wizard-skip-variant"));
    // step4 跳过 SKU
    await user.click(screen.getByTestId("wizard-skip-sku"));
    // step5 保存草稿
    await user.click(screen.getByTestId("wizard-save-draft"));
    expect(setStatus.mutate).not.toHaveBeenCalled(); // 草稿不启用
    expect(onCreated).toHaveBeenCalledWith(10);
  });

  it("新建分类会先创建 category 再创建 family", async () => {
    const user = userEvent.setup();
    render(<CreateWizard open onClose={vi.fn()} />);
    await user.click(screen.getByTestId("cat-mode-new"));
    await user.type(screen.getByTestId("wizard-new-category"), "新分类");
    await user.click(screen.getByTestId("wizard-next-category"));
    expect(createCategory.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ name_zh: "新分类" }),
      expect.anything(),
    );
    // 进入 step2 后创建 family 应带上新分类 id=7
    await user.type(screen.getByTestId("wizard-family-name"), "产品A");
    await user.click(screen.getByTestId("wizard-next-family"));
    expect(createFamily.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ category_id: 7 }),
      expect.anything(),
    );
  });

  it("填型号与 SKU 时分别创建 variant/sku", async () => {
    const user = userEvent.setup();
    render(<CreateWizard open onClose={vi.fn()} />);
    await user.click(screen.getByTestId("wizard-next-category"));
    await user.type(screen.getByTestId("wizard-family-name"), "产品B");
    await user.click(screen.getByTestId("wizard-next-family"));

    await user.type(screen.getByTestId("wizard-variant-name"), "型号一");
    await user.click(screen.getByTestId("wizard-next-variant"));
    expect(createVariant.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ family_id: 10, name_zh: "型号一" }),
      expect.anything(),
    );

    await user.type(screen.getByTestId("wizard-sku-name"), "SKU一");
    await user.click(screen.getByTestId("wizard-next-sku"));
    expect(createSku.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ family_id: 10, variant_id: 20, name_zh: "SKU一" }),
      expect.anything(),
    );
  });

  it("保存并启用先激活分类再激活 family（§二 层级激活）", async () => {
    const user = userEvent.setup();
    render(<CreateWizard open onClose={vi.fn()} />);
    // 新建分类（id=7），family 归属其下，方可启用
    await user.click(screen.getByTestId("cat-mode-new"));
    await user.type(screen.getByTestId("wizard-new-category"), "分类C");
    await user.click(screen.getByTestId("wizard-next-category"));
    await user.type(screen.getByTestId("wizard-family-name"), "产品C");
    await user.click(screen.getByTestId("wizard-next-family"));
    await user.click(screen.getByTestId("wizard-skip-variant"));
    await user.click(screen.getByTestId("wizard-skip-sku"));
    await user.click(screen.getByTestId("wizard-save-active"));
    expect(setStatus.mutate).toHaveBeenCalledWith(
      { level: "category", id: 7, status: "active" },
      expect.anything(),
    );
    expect(setStatus.mutate).toHaveBeenCalledWith(
      { level: "family", id: 10, status: "active" },
      expect.anything(),
    );
  });

  it("暂不分类时「保存并启用」禁用（启用须先归属分类）", async () => {
    const user = userEvent.setup();
    render(<CreateWizard open onClose={vi.fn()} />);
    await user.click(screen.getByTestId("wizard-next-category"));
    await user.type(screen.getByTestId("wizard-family-name"), "产品D");
    await user.click(screen.getByTestId("wizard-next-family"));
    await user.click(screen.getByTestId("wizard-skip-variant"));
    await user.click(screen.getByTestId("wizard-skip-sku"));
    expect(screen.getByTestId("wizard-save-active")).toBeDisabled();
    expect(screen.getByTestId("wizard-enable-hint")).toBeInTheDocument();
  });

  it("产品名为空时创建按钮禁用", async () => {
    const user = userEvent.setup();
    render(<CreateWizard open onClose={vi.fn()} />);
    await user.click(screen.getByTestId("wizard-next-category"));
    expect(screen.getByTestId("wizard-next-family")).toBeDisabled();
  });
});
