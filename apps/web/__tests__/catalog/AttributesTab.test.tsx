import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttributesTab } from "@/components/catalog/AttributesTab";
import { ApiError } from "@/lib/api";
import * as hooks from "@/lib/hooks";

import { makeAttrDef, makeAttrValue, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useAttributeDefinitions: vi.fn(),
  useAttributeValues: vi.fn(),
  useCreateAttributeDefinition: vi.fn(),
  useSetAttributeValue: vi.fn(),
  useDeleteAttributeValue: vi.fn(),
}));

const setValue = mutation();
const delValue = mutation();
const createDef = mutation();

function stub(defs: unknown[] = [], values: unknown[] = []) {
  vi.mocked(hooks.useAttributeDefinitions).mockReturnValue(
    query({ data: { items: defs, total: defs.length } }),
  );
  vi.mocked(hooks.useAttributeValues).mockReturnValue(query({ data: values }));
  vi.mocked(hooks.useSetAttributeValue).mockReturnValue(setValue);
  vi.mocked(hooks.useDeleteAttributeValue).mockReturnValue(delValue);
  vi.mocked(hooks.useCreateAttributeDefinition).mockReturnValue(createDef);
}

beforeEach(() => {
  vi.clearAllMocks();
  [setValue, delValue, createDef].forEach((m) => m.mutate.mockReset());
  stub();
});

function renderTab(props?: Partial<Parameters<typeof AttributesTab>[0]>) {
  render(
    <AttributesTab level="family" targetId={10} categoryId={1} {...props} />,
  );
}

describe("AttributesTab", () => {
  it("空态引导创建属性定义（无固定产品属性硬编码）", async () => {
    stub([]);
    const user = userEvent.setup();
    renderTab();
    expect(screen.getByTestId("attr-empty")).toBeInTheDocument();
    // 空态入口打开新建定义弹窗
    await user.click(screen.getByTestId("empty-create-attr-def"));
    expect(screen.getByTestId("attr-def-dialog")).toBeInTheDocument();
  });

  it("动态渲染各 value_type 控件", () => {
    stub([
      makeAttrDef({ id: 1, name_zh: "文本属性", value_type: "text" }),
      makeAttrDef({ id: 2, name_zh: "数字属性", value_type: "number" }),
      makeAttrDef({ id: 3, name_zh: "布尔属性", value_type: "boolean" }),
      makeAttrDef({ id: 4, name_zh: "枚举属性", value_type: "enum", allowed_values: ["A", "B"] }),
      makeAttrDef({
        id: 5,
        name_zh: "多选属性",
        value_type: "multi_enum",
        allowed_values: ["X", "Y"],
      }),
      makeAttrDef({ id: 6, name_zh: "计量属性", value_type: "measurement", unit: "mm" }),
      makeAttrDef({ id: 7, name_zh: "日期属性", value_type: "date" }),
    ]);
    renderTab();
    // text/number/date/measurement 是单一 input；enum 是 select；multi_enum 是多个复选
    expect(screen.getByTestId("attr-input-1")).toHaveProperty("type", "text");
    expect(screen.getByTestId("attr-input-2")).toHaveProperty("type", "number");
    expect(screen.getByTestId("attr-input-3")).toHaveProperty("type", "checkbox");
    expect(screen.getByTestId("attr-input-4").tagName).toBe("SELECT");
    expect(within(screen.getByTestId("attr-input-4")).getByRole("option", { name: "A" })).toBeInTheDocument();
    expect(screen.getByTestId("attr-opt-5-X")).toBeInTheDocument();
    expect(screen.getByTestId("attr-opt-5-Y")).toBeInTheDocument();
    expect(screen.getByTestId("attr-input-6")).toHaveProperty("type", "number");
    expect(screen.getByTestId("attr-unit-6")).toHaveTextContent("mm");
    expect(screen.getByTestId("attr-input-7")).toHaveProperty("type", "date");
  });

  it("required 有标识且未填时提示（草稿产品可保存不完整）", () => {
    stub([makeAttrDef({ id: 1, name_zh: "必填文本", value_type: "text", required: true })]);
    renderTab();
    expect(screen.getByTestId("attr-required-1")).toBeInTheDocument();
    // 未填必填 → 缺失提示，但控件与保存按钮仍可用（不阻塞草稿保存）
    expect(screen.getByTestId("attr-missing-1")).toBeInTheDocument();
    expect(screen.getByTestId("attr-save-1")).toBeInTheDocument();
  });

  it("编辑文本并保存走 PUT upsert", async () => {
    stub([makeAttrDef({ id: 1, name_zh: "文本属性", value_type: "text" })]);
    const user = userEvent.setup();
    renderTab();
    await user.type(screen.getByTestId("attr-input-1"), "红色");
    await user.click(screen.getByTestId("attr-save-1"));
    expect(setValue.mutate).toHaveBeenCalledWith(
      { definition_id: 1, target_level: "family", target_id: 10, value: "红色" },
      expect.anything(),
    );
  });

  it("number 保存前转为数字", async () => {
    stub([makeAttrDef({ id: 2, name_zh: "数字属性", value_type: "number" })]);
    const user = userEvent.setup();
    renderTab();
    await user.type(screen.getByTestId("attr-input-2"), "42");
    await user.click(screen.getByTestId("attr-save-2"));
    expect(setValue.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ definition_id: 2, value: 42 }),
      expect.anything(),
    );
  });

  it("已有值时可清除（软删）", async () => {
    stub(
      [makeAttrDef({ id: 1, value_type: "text" })],
      [makeAttrValue({ id: 300, definition_id: 1, value_text: "旧值" })],
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(screen.getByTestId("attr-clear-1"));
    expect(delValue.mutate).toHaveBeenCalledWith(300, expect.anything());
  });

  it("422 校验错误显示可读中文提示", () => {
    stub([makeAttrDef({ id: 1, value_type: "text" })]);
    vi.mocked(hooks.useSetAttributeValue).mockReturnValue(
      mutation({ error: new ApiError(422, "值不合法") }),
    );
    renderTab();
    expect(screen.getByTestId("catalog-error")).toHaveTextContent("值不合法");
  });

  it("新建属性定义弹窗：enum 需可选值 / measurement 需单位，提交带 category_id", async () => {
    stub([]);
    const user = userEvent.setup();
    renderTab();
    await user.click(screen.getByTestId("empty-create-attr-def"));
    await user.type(screen.getByTestId("attr-def-name"), "接口类型");
    // 选 enum → 出现可选值输入，未填时提交禁用
    await user.selectOptions(screen.getByTestId("attr-def-type"), "enum");
    expect(screen.getByTestId("attr-def-allowed")).toBeInTheDocument();
    expect(screen.getByTestId("submit-attr-def")).toBeDisabled();
    await user.type(screen.getByTestId("attr-def-allowed"), "USB-C, HDMI");
    await user.click(screen.getByTestId("submit-attr-def"));
    expect(createDef.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        category_id: 1,
        name_zh: "接口类型",
        value_type: "enum",
        allowed_values: ["USB-C", "HDMI"],
      }),
      expect.anything(),
    );
  });

  it("measurement 定义需填单位", async () => {
    stub([]);
    const user = userEvent.setup();
    renderTab();
    await user.click(screen.getByTestId("empty-create-attr-def"));
    await user.type(screen.getByTestId("attr-def-name"), "重量");
    await user.selectOptions(screen.getByTestId("attr-def-type"), "measurement");
    expect(screen.getByTestId("attr-def-unit")).toBeInTheDocument();
    expect(screen.getByTestId("submit-attr-def")).toBeDisabled();
    await user.type(screen.getByTestId("attr-def-unit"), "g");
    expect(screen.getByTestId("submit-attr-def")).not.toBeDisabled();
  });

  it("只读（归档节点）不显示保存与新建入口", () => {
    stub([makeAttrDef({ id: 1, value_type: "text" })]);
    renderTab({ readOnly: true });
    expect(screen.queryByTestId("attr-save-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("open-create-attr-def")).not.toBeInTheDocument();
  });

  it("无固定产品属性硬编码：属性全部来自 API mock", () => {
    // 传入的定义完全由 mock 提供；组件本身不含任何具体产品属性名
    stub([makeAttrDef({ id: 9, name_zh: "任意后端属性", value_type: "text" })]);
    renderTab();
    expect(screen.getByTestId("attr-row-9")).toHaveTextContent("任意后端属性");
  });
});
