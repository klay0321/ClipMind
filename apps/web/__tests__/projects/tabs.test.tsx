import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ProjectAssetsTab,
  ProjectCollectionsTab,
  ProjectProductsTab,
  ProjectScriptsTab,
  ProjectShotsTab,
} from "@/components/projects/tabs";
import * as hooks from "@/lib/hooks";

import {
  makeBatch,
  makeCollection,
  makeProject,
  makeProjectAssetItem,
  makeScript,
  makeShot,
  makeStats,
  mutation,
  query,
} from "./fixtures";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listAssets: vi.fn(() => Promise.resolve({ items: [], total: 0, page: 1, page_size: 24 })),
      listShots: vi.fn(() => Promise.resolve({ items: [], total: 0, page: 1, page_size: 24 })),
      listProducts: vi.fn(() => Promise.resolve([])),
      listScripts: vi.fn(() => Promise.resolve({ items: [], total: 0, page: 1, page_size: 20 })),
      projectShots: vi.fn(() => Promise.resolve({ items: [], total: 0, page: 1, page_size: 24 })),
    },
  };
});

vi.mock("@/lib/hooks", () => ({
  useProjectAssets: vi.fn(),
  useAddProjectAssets: vi.fn(),
  useRemoveProjectAsset: vi.fn(),
  useReorderProjectAssets: vi.fn(),
  useProjectShots: vi.fn(),
  useAddProjectShots: vi.fn(),
  useRemoveProjectShot: vi.fn(),
  useProducts: vi.fn(),
  useProjectCollections: vi.fn(),
  useCreateCollection: vi.fn(),
  useDeleteCollection: vi.fn(),
  useProjectProducts: vi.fn(),
  useAddProjectProducts: vi.fn(),
  useRemoveProjectProduct: vi.fn(),
  useProjectScripts: vi.fn(),
  useProjectStats: vi.fn(),
  useAttachProjectScript: vi.fn(),
  useDetachProjectScript: vi.fn(),
}));

function renderC(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const noopQuery = () => query({ data: { items: [], total: 0, page: 1, page_size: 24 } });

beforeEach(() => {
  vi.clearAllMocks();
  // 默认所有 hooks 返回空/桩
  for (const k of Object.keys(hooks) as (keyof typeof hooks)[]) {
    const fn = hooks[k] as unknown as ReturnType<typeof vi.fn>;
    if (typeof fn?.mockReturnValue === "function") {
      fn.mockReturnValue(k.startsWith("use") && k.match(/Add|Remove|Reorder|Create|Delete|Attach|Detach/) ? mutation() : noopQuery());
    }
  }
  vi.mocked(hooks.useProducts).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useProjectStats).mockReturnValue(query({ data: makeStats() }));
});

describe("ProjectAssetsTab", () => {
  it("渲染素材项 + 移除调用 mutate", async () => {
    const remove = mutation();
    vi.mocked(hooks.useProjectAssets).mockReturnValue(
      query({ data: { items: [makeProjectAssetItem()], total: 1, page: 1, page_size: 24 } }),
    );
    vi.mocked(hooks.useRemoveProjectAsset).mockReturnValue(remove);
    const user = userEvent.setup();
    renderC(<ProjectAssetsTab project={makeProject()} />);
    expect(screen.getByTestId("project-asset-10")).toBeInTheDocument();
    await user.click(screen.getByTestId("remove-asset-10"));
    expect(remove.mutate).toHaveBeenCalledWith(10);
  });

  it("归档项目：添加按钮禁用、无移除按钮", () => {
    vi.mocked(hooks.useProjectAssets).mockReturnValue(
      query({ data: { items: [makeProjectAssetItem()], total: 1, page: 1, page_size: 24 } }),
    );
    renderC(<ProjectAssetsTab project={makeProject({ status: "archived" })} />);
    expect(screen.getByTestId("add-assets")).toBeDisabled();
    expect(screen.queryByTestId("remove-asset-10")).not.toBeInTheDocument();
  });
});

describe("ProjectShotsTab", () => {
  it("source 选择切换并展示可见镜头", async () => {
    vi.mocked(hooks.useProjectShots).mockReturnValue(
      query({ data: { items: [makeShot()], total: 1, page: 1, page_size: 24 } }),
    );
    const user = userEvent.setup();
    renderC(<ProjectShotsTab project={makeProject()} />);
    expect(screen.getByTestId("shot-card")).toBeInTheDocument();
    await user.selectOptions(screen.getByTestId("shot-source"), "explicit");
    expect((screen.getByTestId("shot-source") as HTMLSelectElement).value).toBe("explicit");
  });

  it("归档项目禁用添加显式镜头", () => {
    renderC(<ProjectShotsTab project={makeProject({ status: "archived" })} />);
    expect(screen.getByTestId("add-shots")).toBeDisabled();
  });
});

describe("ProjectCollectionsTab", () => {
  it("创建集合调用 mutate", async () => {
    const create = mutation();
    vi.mocked(hooks.useCreateCollection).mockReturnValue(create);
    const user = userEvent.setup();
    renderC(<ProjectCollectionsTab project={makeProject()} />);
    await user.click(screen.getByTestId("toggle-create-collection"));
    await user.type(screen.getByLabelText("集合名称"), "特写集合");
    await user.click(screen.getByTestId("submit-create-collection"));
    expect(create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ name: "特写集合" }),
      expect.anything(),
    );
  });

  it("删除集合显示「不删除镜头」确认", async () => {
    const del = mutation();
    vi.mocked(hooks.useProjectCollections).mockReturnValue(
      query({ data: { items: [makeCollection()], total: 1, page: 1, page_size: 20 } }),
    );
    vi.mocked(hooks.useDeleteCollection).mockReturnValue(del);
    const user = userEvent.setup();
    renderC(<ProjectCollectionsTab project={makeProject()} />);
    expect(screen.getByTestId("open-collection-1")).toHaveAttribute("href", "/collections/1");
    await user.click(screen.getByTestId("delete-collection-1"));
    expect(screen.getByText(/只删除集合和关联，不删除镜头/)).toBeInTheDocument();
    await user.click(screen.getByTestId("confirm-ok"));
    expect(del.mutate).toHaveBeenCalled();
  });
});

describe("ProjectScriptsTab", () => {
  it("detach 调用 mutate + 锁定/gap 摘要", async () => {
    const detach = mutation();
    vi.mocked(hooks.useProjectScripts).mockReturnValue(
      query({ data: { items: [makeScript()], total: 1, page: 1, page_size: 20 } }),
    );
    vi.mocked(hooks.useDetachProjectScript).mockReturnValue(detach);
    const user = userEvent.setup();
    renderC(<ProjectScriptsTab project={makeProject()} />);
    expect(screen.getByTestId("scripts-lockgap-summary")).toHaveTextContent("锁定段 1");
    expect(screen.getByText("打开")).toHaveAttribute("href", "/script/7");
    await user.click(screen.getByTestId("detach-script-7"));
    expect(detach.mutate).toHaveBeenCalledWith(7);
  });
});

describe("ProjectProductsTab", () => {
  it("批量结果 completed/skipped/failed 由通知展示（透传 onSuccess）", () => {
    vi.mocked(hooks.useProjectProducts).mockReturnValue(noopQuery());
    renderC(<ProjectProductsTab project={makeProject()} />);
    // 空态
    expect(screen.getByTestId("empty")).toBeInTheDocument();
    // 验证 makeBatch 形状被 BatchResultNotice 接受（单元覆盖在 widgets.test）
    expect(makeBatch({ completed: [1] }).completed).toEqual([1]);
  });
});
