import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReferenceGallery } from "@/components/catalog/ReferenceGallery";
import * as hooks from "@/lib/hooks";

import { makeReference, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  usePromotionSuggestions: vi.fn(() => ({ data: [], isLoading: false })),
  usePromoteReference: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useReferences: vi.fn(),
  useUploadReferences: vi.fn(),
  useReferenceMutations: vi.fn(),
}));

const upload = mutation();
const update = mutation();
const setPrimary = mutation();
const archive = mutation();
const restore = mutation();
const remove = mutation();
const batchAngle = mutation();
const batchArchive = mutation();

function stub(refs: unknown[] = []) {
  vi.mocked(hooks.useReferences).mockReturnValue(query({ data: refs }));
  vi.mocked(hooks.useUploadReferences).mockReturnValue(upload);
  vi.mocked(hooks.useReferenceMutations).mockReturnValue({
    update,
    setPrimary,
    archive,
    restore,
    remove,
    batchAngle,
    batchArchive,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
}

beforeEach(() => {
  vi.clearAllMocks();
  [upload, update, setPrimary, archive, restore, remove, batchAngle, batchArchive].forEach((m) =>
    m.mutate.mockReset(),
  );
  stub();
});

function renderGallery(props?: Partial<Parameters<typeof ReferenceGallery>[0]>) {
  render(<ReferenceGallery level="family" targetId={10} {...props} />);
}

describe("ReferenceGallery", () => {
  it("明确显示「自动识别未启用」，不显示虚假相似度/识别结果", () => {
    stub([makeReference({ id: 1 })]);
    renderGallery();
    expect(screen.getByTestId("ref-recognition-notice")).toHaveTextContent(
      "自动产品识别尚未启用",
    );
    // 不出现任何相似度/识别结果字样
    expect(screen.queryByText(/相似度/)).not.toBeInTheDocument();
    expect(screen.queryByText(/识别结果/)).not.toBeInTheDocument();
    expect(screen.queryByText(/匹配度/)).not.toBeInTheDocument();
  });

  it("空态提示无参考图", () => {
    stub([]);
    renderGallery();
    expect(screen.getByTestId("ref-empty")).toBeInTheDocument();
  });

  it("网格渲染参考图并用 thumbnail URL", () => {
    stub([makeReference({ id: 1 }), makeReference({ id: 2, angle: "back" })]);
    renderGallery();
    const grid = screen.getByTestId("ref-grid");
    expect(within(grid).getByTestId("ref-card-1")).toBeInTheDocument();
    expect(within(grid).getByTestId("ref-card-2")).toBeInTheDocument();
    const img = within(screen.getByTestId("ref-thumb-1")).getByRole("img");
    expect(img).toHaveAttribute("src", "/api/product-reference-assets/1/thumbnail");
  });

  it("缩略加载失败回退到原图 /file（不显示破图）", () => {
    stub([makeReference({ id: 1, has_thumbnail: true })]);
    renderGallery();
    const img = within(screen.getByTestId("ref-thumb-1")).getByRole("img");
    expect(img).toHaveAttribute("src", "/api/product-reference-assets/1/thumbnail");
    fireEvent.error(img);
    // 回退原图
    expect(
      within(screen.getByTestId("ref-thumb-1")).getByRole("img"),
    ).toHaveAttribute("src", "/api/product-reference-assets/1/file");
  });

  it("无缩略时直接用原图", () => {
    stub([makeReference({ id: 1, has_thumbnail: false })]);
    renderGallery();
    const img = within(screen.getByTestId("ref-thumb-1")).getByRole("img");
    expect(img).toHaveAttribute("src", "/api/product-reference-assets/1/file");
  });

  it("上传交互：选择文件触发 multipart 上传", async () => {
    stub([]);
    renderGallery();
    const input = screen.getByTestId("ref-file-input") as HTMLInputElement;
    const file = new File(["x"], "a.png", { type: "image/png" });
    await userEvent.upload(input, file);
    expect(upload.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ files: expect.arrayContaining([file]) }),
      expect.anything(),
    );
  });

  it("上传部分失败：显示单张失败提示但不影响成功图", () => {
    // 模拟 upload.mutate 触发 onSuccess，携带 errors
    upload.mutate.mockImplementation(
      (_input: unknown, opts?: { onSuccess?: (r: unknown) => void }) => {
        opts?.onSuccess?.({ created: [makeReference({ id: 5 })], errors: [{ filename: "dup.png", detail: "重复上传" }] });
      },
    );
    stub([makeReference({ id: 1 })]);
    renderGallery();
    const input = screen.getByTestId("ref-file-input") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "dup.png", { type: "image/png" })] } });
    expect(screen.getByTestId("ref-upload-errors")).toHaveTextContent("重复");
    // 已有成功图仍在
    expect(screen.getByTestId("ref-card-1")).toBeInTheDocument();
  });

  it("修改角度调用 update", async () => {
    stub([makeReference({ id: 1, angle: "front" })]);
    const user = userEvent.setup();
    renderGallery();
    await user.selectOptions(screen.getByTestId("ref-angle-1"), "back");
    expect(update.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1, req: { angle: "back" } }),
    );
  });

  it("人工质量标记（非 AI）调用 update", async () => {
    stub([makeReference({ id: 1, quality_status: "unchecked" })]);
    const user = userEvent.setup();
    renderGallery();
    await user.selectOptions(screen.getByTestId("ref-quality-1"), "blurred");
    expect(update.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1, req: { quality_status: "blurred" } }),
    );
  });

  it("设为主图调用 setPrimary", async () => {
    stub([makeReference({ id: 1, is_primary: false })]);
    const user = userEvent.setup();
    renderGallery();
    await user.click(screen.getByTestId("ref-set-primary-1"));
    expect(setPrimary.mutate).toHaveBeenCalledWith(1);
  });

  it("已是主图显示主图徽标且不再显示「设为主图」", () => {
    stub([makeReference({ id: 1, is_primary: true })]);
    renderGallery();
    expect(screen.getByTestId("ref-primary-badge-1")).toBeInTheDocument();
    expect(screen.queryByTestId("ref-set-primary-1")).not.toBeInTheDocument();
  });

  it("归档与恢复调用对应 mutation", async () => {
    stub([makeReference({ id: 1 })]);
    const user = userEvent.setup();
    renderGallery();
    await user.click(screen.getByTestId("ref-archive-1"));
    expect(archive.mutate).toHaveBeenCalledWith(1);
  });

  it("归档图（含归档时）显示恢复按钮", async () => {
    stub([makeReference({ id: 2, state: "archived", archived_at: "2026-06-30T00:00:00Z" })]);
    const user = userEvent.setup();
    renderGallery({ includeArchived: true });
    await user.click(screen.getByTestId("ref-restore-2"));
    expect(restore.mutate).toHaveBeenCalledWith(2);
  });

  it("默认隐藏 rejected/archived 图", () => {
    stub([
      makeReference({ id: 1, state: "active" }),
      makeReference({ id: 2, state: "archived", archived_at: "2026-06-30T00:00:00Z" }),
      makeReference({ id: 3, state: "rejected" }),
    ]);
    renderGallery();
    expect(screen.getByTestId("ref-card-1")).toBeInTheDocument();
    expect(screen.queryByTestId("ref-card-2")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ref-card-3")).not.toBeInTheDocument();
  });

  it("点击缩略打开原图预览（/file）", async () => {
    stub([makeReference({ id: 1 })]);
    const user = userEvent.setup();
    renderGallery();
    await user.click(screen.getByTestId("ref-thumb-1"));
    const preview = screen.getByTestId("ref-preview");
    expect(within(preview).getByRole("img")).toHaveAttribute(
      "src",
      "/api/product-reference-assets/1/file",
    );
  });

  it("只读（归档节点）隐藏上传与编辑控件", () => {
    stub([makeReference({ id: 1 })]);
    renderGallery({ readOnly: true });
    expect(screen.queryByTestId("ref-upload-zone")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ref-angle-1")).not.toBeInTheDocument();
    // 网格仍展示已有图
    expect(screen.getByTestId("ref-card-1")).toBeInTheDocument();
  });
});
