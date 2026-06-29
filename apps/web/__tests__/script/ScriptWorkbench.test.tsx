import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScriptWorkbench } from "@/components/script/ScriptWorkbench";
import * as hooks from "@/lib/hooks";

import {
  makeCandidatesResponse,
  makeEditList,
  makeEditRow,
  makeProject,
  mutation,
  query,
} from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useScriptProject: vi.fn(),
  useScriptMatchStatus: vi.fn(),
  useProducts: vi.fn(),
  useMatchScript: vi.fn(),
  useParseScript: vi.fn(),
  useUpdateSegment: vi.fn(),
  useMatchSegment: vi.fn(),
  useReorderSegments: vi.fn(),
  useSegmentCandidates: vi.fn(),
  useSelectCandidate: vi.fn(),
  useLockCandidate: vi.fn(),
  useUnlockSegment: vi.fn(),
  useScriptEditList: vi.fn(),
  useCreateScriptCsvExport: vi.fn(),
  useScriptExportStatus: vi.fn(),
  // PR-06B：CandidateCard 内 FavoriteButton + ScriptMultiExportPanel 依赖
  useCreateFavorite: vi.fn(() => ({ mutate: vi.fn(), isPending: false, error: null })),
  useCreateScriptExport: vi.fn(() => ({ mutate: vi.fn(), isPending: false, error: null })),
}));

const matchScriptMut = mutation();

function defaults() {
  vi.mocked(hooks.useScriptProject).mockReturnValue(query({ data: makeProject() }));
  vi.mocked(hooks.useScriptMatchStatus).mockReturnValue(
    query({
      data: {
        script_id: 1,
        total_segments: 1,
        matched_segments: 1,
        gap_segments: 0,
        locked_segments: 0,
        selected_segments: 0,
        pending_segments: 0,
        segments: [],
      },
    }),
  );
  vi.mocked(hooks.useProducts).mockReturnValue(query({ data: [] }));
  vi.mocked(hooks.useMatchScript).mockReturnValue(matchScriptMut);
  vi.mocked(hooks.useParseScript).mockReturnValue(mutation());
  vi.mocked(hooks.useUpdateSegment).mockReturnValue(mutation());
  vi.mocked(hooks.useMatchSegment).mockReturnValue(mutation());
  vi.mocked(hooks.useReorderSegments).mockReturnValue(mutation());
  vi.mocked(hooks.useSegmentCandidates).mockReturnValue(query({ data: makeCandidatesResponse() }));
  vi.mocked(hooks.useSelectCandidate).mockReturnValue(mutation());
  vi.mocked(hooks.useLockCandidate).mockReturnValue(mutation());
  vi.mocked(hooks.useUnlockSegment).mockReturnValue(mutation());
  vi.mocked(hooks.useScriptEditList).mockReturnValue(query({ data: makeEditList([makeEditRow()]) }));
  vi.mocked(hooks.useCreateScriptCsvExport).mockReturnValue(mutation());
  vi.mocked(hooks.useScriptExportStatus).mockReturnValue(query());
}

beforeEach(() => {
  vi.clearAllMocks();
  matchScriptMut.mutate.mockReset();
  defaults();
});

describe("ScriptWorkbench", () => {
  it("加载中显示骨架", () => {
    vi.mocked(hooks.useScriptProject).mockReturnValue(query({ isLoading: true }));
    render(<ScriptWorkbench scriptId={1} />);
    expect(screen.getByTestId("loading")).toBeInTheDocument();
  });

  it("加载失败显示错误态", () => {
    vi.mocked(hooks.useScriptProject).mockReturnValue(query({ isError: true, error: new Error("boom") }));
    render(<ScriptWorkbench scriptId={1} />);
    expect(screen.getByTestId("error")).toBeInTheDocument();
  });

  it("scriptId 无效显示错误", () => {
    render(<ScriptWorkbench scriptId={null} />);
    expect(screen.getByText("脚本 id 无效")).toBeInTheDocument();
  });

  it("渲染顶栏标题，剪辑清单作为主视图直接可见", () => {
    render(<ScriptWorkbench scriptId={1} />);
    expect(screen.getByTestId("script-title")).toHaveTextContent("吹风机产品介绍");
    // 剪辑清单不再藏在二级 Tab，直接作为右侧主表渲染
    expect(screen.getByTestId("editlist-tab")).toBeInTheDocument();
    // 候选镜头默认收进抽屉，不抢占主视图
    expect(screen.queryByTestId("candidate-panel")).not.toBeInTheDocument();
  });

  it("全脚本匹配 → 调真实 match", async () => {
    const user = userEvent.setup();
    render(<ScriptWorkbench scriptId={1} />);
    await user.click(screen.getByTestId("match-all"));
    expect(matchScriptMut.mutate).toHaveBeenCalled();
  });

  it("点剪辑清单行「查看候选」打开候选抽屉", async () => {
    const user = userEvent.setup();
    render(<ScriptWorkbench scriptId={1} />);
    expect(screen.queryByTestId("candidate-panel")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("row-view-candidates-1"));
    expect(screen.getByTestId("candidate-panel")).toBeInTheDocument();
  });

  it("导出剪辑清单为单一入口（点开才显示格式）", async () => {
    const user = userEvent.setup();
    render(<ScriptWorkbench scriptId={1} />);
    // 默认不平铺多个导出按钮
    expect(screen.queryByTestId("multi-export-panel")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("toggle-export"));
    expect(screen.getByTestId("multi-export-panel")).toBeInTheDocument();
  });
});
