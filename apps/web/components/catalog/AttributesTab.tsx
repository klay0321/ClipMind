"use client";

import { useEffect, useMemo, useState } from "react";

import { Button, Chip, Dialog, SelectInput, TextArea, TextInput } from "@/components/ui";
import {
  useAttributeDefinitions,
  useAttributeValues,
  useCreateAttributeDefinition,
  useDeleteAttributeValue,
  useSetAttributeValue,
} from "@/lib/hooks";
import {
  ATTRIBUTE_VALUE_TYPES,
  type AttributeDefinition,
  type AttributeTargetLevel,
  type AttributeValue,
  type AttributeValueInput,
  type AttributeValueType,
} from "@/lib/types";

import { CatalogError } from "./widgets";

// 属性值类型中文标签（受控枚举常量，非产品值）
const VALUE_TYPE_LABELS: Record<AttributeValueType, string> = {
  text: "文本",
  number: "数字",
  boolean: "是/否",
  enum: "单选枚举",
  multi_enum: "多选枚举",
  measurement: "计量（带单位）",
  date: "日期",
};

// 从 AttributeValue 按定义类型取出前端可编辑的值（只有对应列非空）
function readValue(def: AttributeDefinition, val: AttributeValue | undefined): AttributeValueInput {
  if (!val) {
    return def.value_type === "multi_enum" ? [] : def.value_type === "boolean" ? false : "";
  }
  switch (def.value_type) {
    case "text":
    case "enum":
      return val.value_text ?? "";
    case "number":
    case "measurement":
      return val.value_number ?? "";
    case "boolean":
      return val.value_boolean ?? false;
    case "multi_enum":
      return val.value_json ?? [];
    case "date":
      return val.value_date ?? "";
    default:
      return "";
  }
}

// 判断某属性是否「已填」（用于 required 缺失提示与保存判定）
function isFilled(def: AttributeDefinition, v: AttributeValueInput): boolean {
  if (def.value_type === "multi_enum") return Array.isArray(v) && v.length > 0;
  if (def.value_type === "boolean") return true; // 布尔恒有值
  return v !== "" && v != null;
}

// 单个属性行：动态渲染控件 + 独立保存/清除
function AttributeRow({
  def,
  value,
  level,
  targetId,
  readOnly = false,
}: {
  def: AttributeDefinition;
  value: AttributeValue | undefined;
  level: AttributeTargetLevel;
  targetId: number;
  readOnly?: boolean;
}) {
  const initial = useMemo(() => readValue(def, value), [def, value]);
  const [draft, setDraft] = useState<AttributeValueInput>(initial);
  const [dirty, setDirty] = useState(false);

  // 服务端值变化（保存成功/切换节点）后重置本地草稿
  useEffect(() => {
    setDraft(initial);
    setDirty(false);
  }, [initial]);

  const setValue = useSetAttributeValue(level, targetId);
  const delValue = useDeleteAttributeValue(level, targetId);

  const change = (v: AttributeValueInput) => {
    setDraft(v);
    setDirty(true);
  };

  const save = () => {
    // number/measurement 提交前转成数字；空文本按 null 提交（后端软删该值）
    let out: AttributeValueInput = draft;
    if (def.value_type === "number" || def.value_type === "measurement") {
      out = draft === "" || draft == null ? null : Number(draft);
    }
    setValue.mutate(
      { definition_id: def.id, target_level: level, target_id: targetId, value: out },
      { onSuccess: () => setDirty(false) },
    );
  };

  const clear = () => {
    if (value) {
      delValue.mutate(value.id, { onSuccess: () => setDirty(false) });
    } else {
      setDraft(readValue(def, undefined));
      setDirty(false);
    }
  };

  const filled = isFilled(def, draft);
  const missingRequired = def.required && !filled;
  const controlId = `attr-${def.id}`;

  const label = (
    <span className="flex flex-wrap items-center gap-1.5">
      <span className="text-gray-700">{def.name_zh}</span>
      {def.required ? (
        <span className="text-red-500" aria-label="必填" data-testid={`attr-required-${def.id}`}>
          *
        </span>
      ) : null}
      <Chip tone="neutral">{VALUE_TYPE_LABELS[def.value_type]}</Chip>
      {def.identity_relevant ? <Chip tone="brand">身份关键</Chip> : null}
      {def.searchable ? <Chip tone="info">可检索</Chip> : null}
    </span>
  );

  const allowed = def.allowed_values ?? [];

  return (
    <div
      className="space-y-1.5 rounded border border-gray-100 bg-white p-3"
      data-testid={`attr-row-${def.id}`}
    >
      <label htmlFor={controlId} className="block text-xs font-medium">
        {label}
      </label>
      {def.description ? (
        <p className="text-[11px] text-gray-400">{def.description}</p>
      ) : null}

      {/* 动态控件：按 value_type 渲染 */}
      {def.value_type === "text" ? (
        <input
          id={controlId}
          value={String(draft ?? "")}
          onChange={(e) => change(e.target.value)}
          data-testid={`attr-input-${def.id}`}
          maxLength={2000}
          className="w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-sm focus:border-brand focus:outline-none"
        />
      ) : null}

      {def.value_type === "number" ? (
        <input
          id={controlId}
          type="number"
          value={draft === "" || draft == null ? "" : String(draft)}
          onChange={(e) => change(e.target.value)}
          data-testid={`attr-input-${def.id}`}
          className="w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-sm focus:border-brand focus:outline-none"
        />
      ) : null}

      {def.value_type === "measurement" ? (
        <div className="flex items-center gap-2">
          <input
            id={controlId}
            type="number"
            value={draft === "" || draft == null ? "" : String(draft)}
            onChange={(e) => change(e.target.value)}
            data-testid={`attr-input-${def.id}`}
            className="w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-sm focus:border-brand focus:outline-none"
          />
          <span className="shrink-0 text-xs text-gray-500" data-testid={`attr-unit-${def.id}`}>
            {def.unit ?? ""}
          </span>
        </div>
      ) : null}

      {def.value_type === "boolean" ? (
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            id={controlId}
            type="checkbox"
            checked={Boolean(draft)}
            onChange={(e) => change(e.target.checked)}
            data-testid={`attr-input-${def.id}`}
          />
          是
        </label>
      ) : null}

      {def.value_type === "enum" ? (
        <select
          id={controlId}
          value={String(draft ?? "")}
          onChange={(e) => change(e.target.value)}
          data-testid={`attr-input-${def.id}`}
          className="w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-sm focus:border-brand focus:outline-none"
        >
          <option value="">未选择</option>
          {allowed.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      ) : null}

      {def.value_type === "multi_enum" ? (
        <div className="flex flex-wrap gap-2" data-testid={`attr-input-${def.id}`}>
          {allowed.length === 0 ? (
            <span className="text-[11px] text-gray-400">该属性未配置可选值</span>
          ) : (
            allowed.map((opt) => {
              const arr = Array.isArray(draft) ? draft : [];
              const checked = arr.includes(opt);
              return (
                <label
                  key={opt}
                  className="flex items-center gap-1 rounded border border-gray-200 px-2 py-1 text-xs text-gray-700"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? [...arr, opt]
                        : arr.filter((x) => x !== opt);
                      change(next);
                    }}
                    data-testid={`attr-opt-${def.id}-${opt}`}
                  />
                  {opt}
                </label>
              );
            })
          )}
        </div>
      ) : null}

      {def.value_type === "date" ? (
        <input
          id={controlId}
          type="date"
          value={String(draft ?? "")}
          onChange={(e) => change(e.target.value)}
          data-testid={`attr-input-${def.id}`}
          className="w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-sm focus:border-brand focus:outline-none"
        />
      ) : null}

      {missingRequired ? (
        <p className="text-[11px] text-amber-700" data-testid={`attr-missing-${def.id}`}>
          必填项尚未填写（草稿产品可暂不填写）
        </p>
      ) : null}

      <CatalogError error={setValue.error ?? delValue.error} />

      {!readOnly ? (
        <div className="flex items-center justify-end gap-2">
          {value ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={clear}
              loading={delValue.isPending}
              data-testid={`attr-clear-${def.id}`}
            >
              清除
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="primary"
            onClick={save}
            disabled={!dirty}
            loading={setValue.isPending}
            data-testid={`attr-save-${def.id}`}
          >
            保存
          </Button>
        </div>
      ) : null}
    </div>
  );
}

// 新建属性定义弹窗：name_zh / value_type /（enum 时 allowed_values）/（measurement 时 unit）
// / required / searchable / identity_relevant → POST 创建（category_id=当前节点分类）
function CreateDefinitionDialog({
  open,
  onClose,
  categoryId,
}: {
  open: boolean;
  onClose: () => void;
  categoryId: number | null;
}) {
  const create = useCreateAttributeDefinition();
  const [nameZh, setNameZh] = useState("");
  const [valueType, setValueType] = useState<AttributeValueType>("text");
  const [allowedText, setAllowedText] = useState("");
  const [unit, setUnit] = useState("");
  const [required, setRequired] = useState(false);
  const [searchable, setSearchable] = useState(false);
  const [identityRelevant, setIdentityRelevant] = useState(false);

  useEffect(() => {
    if (open) {
      setNameZh("");
      setValueType("text");
      setAllowedText("");
      setUnit("");
      setRequired(false);
      setSearchable(false);
      setIdentityRelevant(false);
    }
  }, [open]);

  const needsAllowed = valueType === "enum" || valueType === "multi_enum";
  const needsUnit = valueType === "measurement";
  const allowedValues = allowedText
    .split(/[\n,，]/)
    .map((s) => s.trim())
    .filter(Boolean);

  const canSubmit =
    nameZh.trim().length > 0 &&
    (!needsAllowed || allowedValues.length > 0) &&
    (!needsUnit || unit.trim().length > 0);

  const submit = () => {
    if (!canSubmit) return;
    create.mutate(
      {
        category_id: categoryId,
        name_zh: nameZh.trim(),
        value_type: valueType,
        allowed_values: needsAllowed ? allowedValues : undefined,
        unit: needsUnit ? unit.trim() : undefined,
        required,
        searchable,
        identity_relevant: identityRelevant,
      },
      { onSuccess: () => onClose() },
    );
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="新建属性定义"
      widthClass="max-w-md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={create.isPending}>
            取消
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={!canSubmit}
            loading={create.isPending}
            data-testid="submit-attr-def"
          >
            创建
          </Button>
        </>
      }
    >
      <div className="space-y-3" data-testid="attr-def-dialog">
        <TextInput
          label="属性名称（中文，必填）"
          value={nameZh}
          onChange={(e) => setNameZh(e.target.value)}
          maxLength={255}
          data-testid="attr-def-name"
        />
        <SelectInput
          label="值类型"
          value={valueType}
          onChange={(e) => setValueType(e.target.value as AttributeValueType)}
          data-testid="attr-def-type"
        >
          {ATTRIBUTE_VALUE_TYPES.map((t) => (
            <option key={t} value={t}>
              {VALUE_TYPE_LABELS[t]}
            </option>
          ))}
        </SelectInput>
        {needsAllowed ? (
          <TextArea
            label="可选值（每行或逗号分隔，必填）"
            value={allowedText}
            onChange={(e) => setAllowedText(e.target.value)}
            rows={3}
            hint="枚举类型必须提供至少一个可选值"
            data-testid="attr-def-allowed"
          />
        ) : null}
        {needsUnit ? (
          <TextInput
            label="计量单位（必填）"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            maxLength={32}
            hint="如 mm、g、W、V 等"
            data-testid="attr-def-unit"
          />
        ) : null}
        <div className="flex flex-wrap gap-4 text-sm text-gray-700">
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={required}
              onChange={(e) => setRequired(e.target.checked)}
              data-testid="attr-def-required"
            />
            必填
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={searchable}
              onChange={(e) => setSearchable(e.target.checked)}
              data-testid="attr-def-searchable"
            />
            可检索
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={identityRelevant}
              onChange={(e) => setIdentityRelevant(e.target.checked)}
              data-testid="attr-def-identity"
            />
            身份关键
          </label>
        </div>
        {categoryId == null ? (
          <p className="text-[11px] text-amber-700" data-testid="attr-def-global-hint">
            当前节点未归属分类，新建的属性将作为全局属性（对所有分类生效）。
          </p>
        ) : null}
        <CatalogError error={create.error} />
      </div>
    </Dialog>
  );
}

// 产品属性 Tab：仅 family/variant/sku 层。定义来自 API（该分类 + 全局），值按 definition_id 合并。
export function AttributesTab({
  level,
  targetId,
  categoryId,
  readOnly = false,
}: {
  level: AttributeTargetLevel;
  targetId: number;
  categoryId: number | null;
  readOnly?: boolean;
}) {
  const [showCreate, setShowCreate] = useState(false);

  const defsQ = useAttributeDefinitions({
    category_id: categoryId ?? undefined,
    include_global: true,
    status_filter: "active",
  });
  const valuesQ = useAttributeValues(level, targetId);

  const defs = useMemo(
    () =>
      [...(defsQ.data?.items ?? [])].sort(
        (a, b) => a.sort_order - b.sort_order || a.id - b.id,
      ),
    [defsQ.data],
  );
  // 按 definition_id 建立值索引，前端合并（一个定义至多一个活动值）
  const valueByDef = useMemo(() => {
    const map = new Map<number, AttributeValue>();
    for (const v of valuesQ.data ?? []) map.set(v.definition_id, v);
    return map;
  }, [valuesQ.data]);

  const missingCount = defs.filter(
    (d) => d.required && !isFilled(d, readValue(d, valueByDef.get(d.id))),
  ).length;

  if (defsQ.isLoading) {
    return (
      <div className="space-y-2 p-1" data-testid="attributes-loading">
        <div className="h-16 animate-pulse rounded bg-gray-100" />
        <div className="h-16 animate-pulse rounded bg-gray-100" />
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="attributes-tab">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs text-gray-500">
          {defs.length > 0 ? (
            <span data-testid="attr-summary">
              共 {defs.length} 项属性
              {missingCount > 0 ? (
                <span className="ml-1 text-amber-700">（{missingCount} 项必填未完成）</span>
              ) : null}
            </span>
          ) : null}
        </div>
        {!readOnly ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setShowCreate(true)}
            data-testid="open-create-attr-def"
          >
            + 新建属性定义
          </Button>
        ) : null}
      </div>

      <CatalogError error={defsQ.error ?? valuesQ.error} />

      {defs.length === 0 ? (
        <div
          className="rounded border border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-center"
          data-testid="attr-empty"
        >
          <p className="text-sm text-gray-600">当前分类尚未配置任何产品属性。</p>
          <p className="mt-1 text-xs text-gray-400">
            属性定义决定该类产品需要维护哪些结构化信息（如尺寸、材质、接口等），全部动态配置、无需改代码。
          </p>
          {!readOnly ? (
            <div className="mt-3 flex justify-center">
              <Button
                variant="primary"
                onClick={() => setShowCreate(true)}
                data-testid="empty-create-attr-def"
              >
                + 新建属性定义
              </Button>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="space-y-2">
          {defs.map((def) => (
            <AttributeRow
              key={def.id}
              def={def}
              value={valueByDef.get(def.id)}
              level={level}
              targetId={targetId}
              readOnly={readOnly}
            />
          ))}
        </div>
      )}

      <CreateDefinitionDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        categoryId={categoryId}
      />
    </div>
  );
}
