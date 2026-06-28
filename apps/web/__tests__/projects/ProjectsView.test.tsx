import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectsView } from "@/components/projects/ProjectsView";
import * as hooks from "@/lib/hooks";

import { makeProject, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useProjects: vi.fn(),
  useCreateProject: vi.fn(),
  useArchiveProject: vi.fn(),
  useUnarchiveProject: vi.fn(),
}));

const createMut = mutation();
const archiveMut = mutation();
const unarchiveMut = mutation();

beforeEach(() => {
  vi.clearAllMocks();
  createMut.mutate.mockReset();
  vi.mocked(hooks.useProjects).mockReturnValue(
    query({ data: { items: [makeProject()], total: 1, page: 1, page_size: 12 } }),
  );
  vi.mocked(hooks.useCreateProject).mockReturnValue(createMut);
  vi.mocked(hooks.useArchiveProject).mockReturnValue(archiveMut);
  vi.mocked(hooks.useUnarchiveProject).mockReturnValue(unarchiveMut);
});

describe("ProjectsView", () => {
  it("loading 态显示骨架", () => {
    vi.mocked(hooks.useProjects).mockReturnValue(query({ isLoading: true }));
    render(<ProjectsView />);
    expect(screen.getByTestId("loading")).toBeInTheDocument();
  });

  it("空态提示创建", () => {
    vi.mocked(hooks.useProjects).mockReturnValue(
      query({ data: { items: [], total: 0, page: 1, page_size: 12 } }),
    );
    render(<ProjectsView />);
    expect(screen.getByTestId("empty")).toBeInTheDocument();
  });

  it("渲染项目卡 + 打开详情链接", () => {
    render(<ProjectsView />);
    expect(screen.getByTestId("project-card")).toBeInTheDocument();
    expect(screen.getByTestId("open-project-1")).toHaveAttribute("href", "/projects/1");
    expect(screen.getByTestId("project-status-active")).toBeInTheDocument();
  });

  it("空名称时创建按钮禁用", async () => {
    const user = userEvent.setup();
    render(<ProjectsView />);
    await user.click(screen.getByTestId("toggle-create-project"));
    expect(screen.getByTestId("submit-create-project")).toBeDisabled();
  });

  it("填名 → 创建（重复名也允许，仅透传后端）", async () => {
    const user = userEvent.setup();
    render(<ProjectsView />);
    await user.click(screen.getByTestId("toggle-create-project"));
    await user.type(screen.getByLabelText("项目名称"), "同名项目");
    await user.click(screen.getByTestId("submit-create-project"));
    expect(createMut.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ name: "同名项目" }),
      expect.anything(),
    );
  });

  it("archived 筛选请求 status=archived", async () => {
    const user = userEvent.setup();
    render(<ProjectsView />);
    await user.click(screen.getByTestId("filter-archived"));
    await waitFor(() =>
      expect(hooks.useProjects).toHaveBeenCalledWith(1, 12, "archived"),
    );
  });

  it("归档项目卡显示恢复按钮并调用 unarchive", async () => {
    vi.mocked(hooks.useProjects).mockReturnValue(
      query({
        data: {
          items: [makeProject({ status: "archived", lock_version: 3 })],
          total: 1,
          page: 1,
          page_size: 12,
        },
      }),
    );
    const user = userEvent.setup();
    render(<ProjectsView />);
    await user.click(screen.getByTestId("unarchive-1"));
    expect(unarchiveMut.mutate).toHaveBeenCalledWith(3);
  });
});
