import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CollectionDetailView } from "@/components/projects/CollectionDetailView";
import * as hooks from "@/lib/hooks";

import { makeCollection, makeProject, makeShot, mutation, query } from "./fixtures";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      projectShots: vi.fn(() => Promise.resolve({ items: [], total: 0, page: 1, page_size: 24 })),
    },
  };
});

vi.mock("@/lib/hooks", () => ({
  useCollection: vi.fn(),
  useProject: vi.fn(),
  useCollectionShots: vi.fn(),
  useAddCollectionShots: vi.fn(),
  useRemoveCollectionShot: vi.fn(),
  useReorderCollectionShots: vi.fn(),
  useDeleteCollection: vi.fn(),
  useUpdateCollection: vi.fn(),
}));

function renderC(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const delMut = mutation();
const removeMut = mutation();

function setup(projectStatus: "active" | "archived" = "active") {
  vi.mocked(hooks.useCollection).mockReturnValue(query({ data: makeCollection() }));
  vi.mocked(hooks.useProject).mockReturnValue(query({ data: makeProject({ status: projectStatus }) }));
  vi.mocked(hooks.useCollectionShots).mockReturnValue(
    query({ data: { items: [makeShot()], total: 1, page: 1, page_size: 24 } }),
  );
  vi.mocked(hooks.useAddCollectionShots).mockReturnValue(mutation());
  vi.mocked(hooks.useRemoveCollectionShot).mockReturnValue(removeMut);
  vi.mocked(hooks.useReorderCollectionShots).mockReturnValue(mutation());
  vi.mocked(hooks.useDeleteCollection).mockReturnValue(delMut);
  vi.mocked(hooks.useUpdateCollection).mockReturnValue(mutation());
}

beforeEach(() => {
  vi.clearAllMocks();
  delMut.mutate.mockReset();
  removeMut.mutate.mockReset();
  push.mockReset();
  setup();
});

describe("CollectionDetailView", () => {
  it("渲染集合名 + 镜头 + 返回项目链接", () => {
    renderC(<CollectionDetailView collectionId={1} />);
    expect(screen.getByTestId("collection-name")).toHaveTextContent("Hook 集合");
    expect(screen.getByTestId("collection-shot-101")).toBeInTheDocument();
    expect(screen.getByText("← 返回项目")).toHaveAttribute("href", "/projects/1");
  });

  it("移除镜头调用 mutate（不删镜头实体）", async () => {
    const user = userEvent.setup();
    renderC(<CollectionDetailView collectionId={1} />);
    await user.click(screen.getByTestId("remove-collection-shot-101"));
    expect(removeMut.mutate).toHaveBeenCalledWith(101);
  });

  it("删除集合：确认「不删除镜头」→ 删除并跳回项目", async () => {
    delMut.mutate.mockImplementation((_v: unknown, opts?: { onSuccess?: () => void }) =>
      opts?.onSuccess?.(),
    );
    const user = userEvent.setup();
    renderC(<CollectionDetailView collectionId={1} />);
    await user.click(screen.getByTestId("delete-collection"));
    expect(screen.getByText(/只删除集合和关联，不删除镜头/)).toBeInTheDocument();
    await user.click(screen.getByTestId("confirm-ok"));
    expect(delMut.mutate).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith("/projects/1");
  });

  it("所属项目归档 → 只读（无编辑/删除/可用添加）", () => {
    setup("archived");
    renderC(<CollectionDetailView collectionId={1} />);
    expect(screen.queryByTestId("edit-collection")).not.toBeInTheDocument();
    expect(screen.queryByTestId("delete-collection")).not.toBeInTheDocument();
    expect(screen.getByTestId("add-collection-shots")).toBeDisabled();
    expect(screen.queryByTestId("remove-collection-shot-101")).not.toBeInTheDocument();
  });
});
