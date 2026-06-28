import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectDetailView } from "@/components/projects/ProjectDetailView";
import { ApiError } from "@/lib/api";
import * as hooks from "@/lib/hooks";

import { makeProject, makeStats, mutation, query } from "./fixtures";

// 隔离：tab 内容用桩，专注测 ProjectDetailView 头部/总览/归档
vi.mock("@/components/projects/tabs", () => ({
  ProjectAssetsTab: () => <div data-testid="stub-assets" />,
  ProjectShotsTab: () => <div data-testid="stub-shots" />,
  ProjectCollectionsTab: () => <div data-testid="stub-collections" />,
  ProjectProductsTab: () => <div data-testid="stub-products" />,
  ProjectScriptsTab: () => <div data-testid="stub-scripts" />,
}));

vi.mock("@/lib/hooks", () => ({
  useProject: vi.fn(),
  useProjectStats: vi.fn(),
  useUpdateProject: vi.fn(),
  useArchiveProject: vi.fn(),
  useUnarchiveProject: vi.fn(),
}));

const updateMut = mutation();
const archiveMut = mutation();
const unarchiveMut = mutation();

function setup(project = makeProject(), statsOver = {}) {
  vi.mocked(hooks.useProject).mockReturnValue(query({ data: project }));
  vi.mocked(hooks.useProjectStats).mockReturnValue(query({ data: makeStats(), ...statsOver }));
  vi.mocked(hooks.useUpdateProject).mockReturnValue(updateMut);
  vi.mocked(hooks.useArchiveProject).mockReturnValue(archiveMut);
  vi.mocked(hooks.useUnarchiveProject).mockReturnValue(unarchiveMut);
}

beforeEach(() => {
  vi.clearAllMocks();
  updateMut.mutate.mockReset();
  setup();
});

describe("ProjectDetailView", () => {
  it("总览展示统计 + 项目名", () => {
    render(<ProjectDetailView projectId={1} />);
    expect(screen.getByTestId("project-name")).toHaveTextContent("夏季广告");
    expect(screen.getByTestId("project-stats")).toBeInTheDocument();
    expect(screen.getByTestId("stat-visible_shot_count")).toHaveTextContent("12");
  });

  it("切换 Tab 渲染对应面板", async () => {
    const user = userEvent.setup();
    render(<ProjectDetailView projectId={1} />);
    await user.click(screen.getByTestId("tab-collections"));
    expect(screen.getByTestId("stub-collections")).toBeInTheDocument();
  });

  it("编辑携带 lock_version", async () => {
    const user = userEvent.setup();
    render(<ProjectDetailView projectId={1} />);
    await user.click(screen.getByTestId("edit-project"));
    await user.clear(screen.getByLabelText("项目名称"));
    await user.type(screen.getByLabelText("项目名称"), "新名");
    await user.click(screen.getByTestId("submit-edit-project"));
    expect(updateMut.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ lock_version: 1, name: "新名" }),
      expect.anything(),
    );
  });

  it("409 冲突显示可读提示（role=alert）", async () => {
    vi.mocked(hooks.useUpdateProject).mockReturnValue(
      mutation({ error: new ApiError(409, "项目已被更新（lock_version 不匹配），请刷新后重试") }),
    );
    const user = userEvent.setup();
    render(<ProjectDetailView projectId={1} />);
    await user.click(screen.getByTestId("edit-project"));
    expect(screen.getByRole("alert")).toHaveTextContent("lock_version 不匹配");
  });

  it("归档项目：只读（无编辑按钮）+ 归档横幅 + 恢复", () => {
    setup(makeProject({ status: "archived", lock_version: 2 }));
    render(<ProjectDetailView projectId={1} />);
    expect(screen.queryByTestId("edit-project")).not.toBeInTheDocument();
    expect(screen.getByTestId("archived-banner")).toBeInTheDocument();
    expect(screen.getByTestId("overview-unarchive")).toBeInTheDocument();
  });

  it("页面不存在「删除项目」按钮", () => {
    render(<ProjectDetailView projectId={1} />);
    expect(screen.queryByText("删除项目")).not.toBeInTheDocument();
  });

  it("归档项目总览归档按钮变为「恢复项目」并带 lock_version", async () => {
    setup(makeProject({ status: "archived", lock_version: 4 }));
    const user = userEvent.setup();
    render(<ProjectDetailView projectId={1} />);
    await user.click(screen.getByTestId("overview-unarchive"));
    expect(unarchiveMut.mutate).toHaveBeenCalledWith(4);
  });
});
