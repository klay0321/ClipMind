"use client";

import { useMemo, useState } from "react";

import { Button, Chip, Dialog, SelectInput, TextArea, TextInput, type Tone } from "@/components/ui";
import {
  useConfusionPairMutations,
  useConfusions,
  useCreateConfusionPair,
  useFamilies,
  useSkus,
  useUpdateConfusionPair,
  useVariants,
} from "@/lib/hooks";
import {
  CONFUSION_SEVERITIES,
  type AttributeTargetLevel,
  type CatalogStatus,
  type ConfusionFeature,
  type ConfusionPair,
  type ConfusionSeverity,
  type ConfusionSide,
} from "@/lib/types";

import type { SelectedNode } from "./CatalogTree";
import { CatalogError } from "./widgets";

// 严重程度中文标签 + 色调（受控枚举，非产品值）
const SEVERITY_META: Record<ConfusionSeverity, { label: string; tone: Tone }> = {
  low: { label: "低", tone: "neutral" },
  medium: { label: "中", tone: "warning" },
  high: { label: "高", tone: "danger" },
};

export function severityLabel(s: ConfusionSeverity): string {
  return SEVERITY_META[s]?.label ?? s;
}

// 取混淆对中「对方」一侧（当前节点为 left 则对方为 right，反之亦然）
function otherSide(pair: ConfusionPair, selfId: number): ConfusionSide | null {
  return pair.left_target_id === selfId ? pair.right : pair.left;
}

// 同层级候选节点（供添加混淆关系选择；数据全部来自 API）
interface CandidateRow {
  id: number;
  name_zh: string;
  code: string;
  status: CatalogStatus;
}

// 添加混淆关系表单：同层级搜索候选 → 选目标 + 严重程度 + 原因 → POST
function AddPairForm({
  level,
  targetId,
  familyId,
  onClose,
}: {
  level: AttributeTargetLevel;
  targetId: number;
  familyId: number | null;
  onClose: () => void;
}) {
  const create = useCreateConfusionPair();
  const [search, setSearch] = useState("");
  const [chosen, setChosen] = useState("");
  const [severity, setSeverity] = useState<ConfusionSeverity>("medium");
  const [reason, setReason] = useState("");

  // family 层：全库按关键词搜索；variant/sku 层：同 family 下全部（客户端再按关键词过滤）
  const famQ = useFamilies({ q: search.trim() || undefined, limit: 50 }, level === "family");
  const varQ = useVariants(
    { family_id: familyId ?? undefined, limit: 500 },
    level === "variant" && familyId != null,
  );
  const skuQ = useSkus(
    { family_id: familyId ?? undefined, limit: 500 },
    level === "sku" && familyId != null,
  );

  const candidates: CandidateRow[] = useMemo(() => {
    const term = search.trim();
    let rows: CandidateRow[] =
      level === "family"
        ? (famQ.data?.items ?? [])
        : level === "variant"
          ? (varQ.data?.items ?? [])
          : (skuQ.data?.items ?? []);
    // 排除自身；variant/sku 在客户端按关键词过滤（family 已由后端 q 过滤）
    rows = rows.filter((r) => r.id !== targetId);
    if (term && level !== "family") {
      rows = rows.filter(
        (r) => r.name_zh.includes(term) || r.code.includes(term),
      );
    }
    return rows;
  }, [level, targetId, search, famQ.data, varQ.data, skuQ.data]);

  const submit = () => {
    const rightId = Number(chosen);
    if (!rightId) return;
    create.mutate(
      {
        target_level: level,
        left_target_id: targetId,
        right_target_id: rightId,
        severity,
        reason: reason.trim() || undefined,
      },
      { onSuccess: () => onClose() },
    );
  };

  return (
    <div
      className="space-y-2 rounded border border-gray-200 bg-gray-50 p-3"
      data-testid="confusion-add-form"
    >
      <TextInput
        label="搜索同层级产品"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="输入名称或编码筛选"
        data-testid="confusion-search"
      />
      <SelectInput
        label="易混淆对象（必选）"
        value={chosen}
        onChange={(e) => setChosen(e.target.value)}
        data-testid="confusion-target-select"
      >
        <option value="">请选择…</option>
        {candidates.map((c) => (
          <option key={c.id} value={String(c.id)}>
            {c.name_zh}（{c.code}）
          </option>
        ))}
      </SelectInput>
      {level !== "family" && familyId == null ? (
        <p className="text-[11px] text-amber-700">未获取到所属产品，暂无法列出同层级候选。</p>
      ) : candidates.length === 0 ? (
        <p className="text-[11px] text-gray-400">无可选的同层级候选。</p>
      ) : null}
      <SelectInput
        label="混淆严重程度"
        value={severity}
        onChange={(e) => setSeverity(e.target.value as ConfusionSeverity)}
        data-testid="confusion-severity"
      >
        {CONFUSION_SEVERITIES.map((s) => (
          <option key={s} value={s}>
            {SEVERITY_META[s].label}
          </option>
        ))}
      </SelectInput>
      <TextArea
        label="混淆原因（可选）"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        rows={2}
        data-testid="confusion-reason"
      />
      <CatalogError error={create.error} />
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onClose}>
          取消
        </Button>
        <Button
          size="sm"
          variant="primary"
          onClick={submit}
          disabled={!chosen}
          loading={create.isPending}
          data-testid="confusion-submit"
        >
          添加
        </Button>
      </div>
    </div>
  );
}

// 区分特征编辑 Dialog：feature/left_value/right_value + 参考图可见/身份关键，可增删行
function FeaturesDialog({
  pair,
  onClose,
}: {
  pair: ConfusionPair;
  onClose: () => void;
}) {
  const update = useUpdateConfusionPair();
  const [rows, setRows] = useState<ConfusionFeature[]>(
    () => pair.distinguishing_features ?? [],
  );

  const setRow = (i: number, patch: Partial<ConfusionFeature>) => {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  };
  const addRow = () => {
    setRows((prev) => [
      ...prev,
      {
        feature: "",
        left_value: "",
        right_value: "",
        visible_in_reference: false,
        identity_relevant: false,
      },
    ]);
  };
  const removeRow = (i: number) => {
    setRows((prev) => prev.filter((_, idx) => idx !== i));
  };

  const save = () => {
    // feature 名为空的行不提交（后端要求每条必须有 feature 名称）
    const cleaned = rows.filter((r) => r.feature.trim().length > 0);
    update.mutate(
      { id: pair.id, req: { distinguishing_features: cleaned } },
      { onSuccess: () => onClose() },
    );
  };

  const leftName = pair.left?.name_zh ?? `#${pair.left_target_id}`;
  const rightName = pair.right?.name_zh ?? `#${pair.right_target_id}`;

  return (
    <Dialog
      open
      onClose={onClose}
      title="区分特征"
      widthClass="max-w-2xl"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={update.isPending}>
            取消
          </Button>
          <Button
            variant="primary"
            onClick={save}
            loading={update.isPending}
            data-testid="features-save"
          >
            保存
          </Button>
        </>
      }
    >
      <div className="space-y-3" data-testid="features-dialog">
        <p className="text-xs text-gray-500">
          记录两个产品如何区分（如按键数量、接口位置等），供人工核对与后续 AI 识别参考。
        </p>
        {rows.length === 0 ? (
          <p className="text-xs text-gray-400" data-testid="features-empty">
            暂无区分特征，点击下方按钮添加。
          </p>
        ) : (
          <div className="space-y-2">
            {rows.map((r, i) => (
              <div
                key={i}
                className="space-y-1.5 rounded border border-gray-200 bg-white p-2"
                data-testid={`feature-row-${i}`}
              >
                <div className="flex items-start gap-2">
                  <TextInput
                    label="特征名"
                    value={r.feature}
                    onChange={(e) => setRow(i, { feature: e.target.value })}
                    maxLength={100}
                    className="flex-1"
                    data-testid={`feature-name-${i}`}
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => removeRow(i)}
                    className="mt-5 shrink-0"
                    data-testid={`feature-remove-${i}`}
                  >
                    删除
                  </Button>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <TextInput
                    label={<span className="truncate">「{leftName}」的表现</span>}
                    value={r.left_value}
                    onChange={(e) => setRow(i, { left_value: e.target.value })}
                    maxLength={300}
                    data-testid={`feature-left-${i}`}
                  />
                  <TextInput
                    label={<span className="truncate">「{rightName}」的表现</span>}
                    value={r.right_value}
                    onChange={(e) => setRow(i, { right_value: e.target.value })}
                    maxLength={300}
                    data-testid={`feature-right-${i}`}
                  />
                </div>
                <div className="flex flex-wrap gap-4 text-xs text-gray-700">
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={r.visible_in_reference}
                      onChange={(e) => setRow(i, { visible_in_reference: e.target.checked })}
                      data-testid={`feature-visible-${i}`}
                    />
                    参考图可见
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={r.identity_relevant}
                      onChange={(e) => setRow(i, { identity_relevant: e.target.checked })}
                      data-testid={`feature-identity-${i}`}
                    />
                    身份关键
                  </label>
                </div>
              </div>
            ))}
          </div>
        )}
        <Button size="sm" variant="ghost" onClick={addRow} data-testid="feature-add-row">
          + 添加特征
        </Button>
        <CatalogError error={update.error} />
      </div>
    </Dialog>
  );
}

// 易混淆产品面板：列表 + 添加 + 区分特征编辑 + 归档/恢复 + 跳转对方节点。
// 全部产品名来自 API（left/right 展示信息），前端绝不硬编码任何公司产品名。
export function ConfusionsPanel({
  level,
  targetId,
  familyId,
  readOnly = false,
  onSelect,
}: {
  level: AttributeTargetLevel;
  targetId: number;
  familyId: number | null;
  readOnly?: boolean;
  onSelect: (n: SelectedNode) => void;
}) {
  const confusionsQ = useConfusions(level, targetId);
  const m = useConfusionPairMutations();
  const [showAdd, setShowAdd] = useState(false);
  const [editingPair, setEditingPair] = useState<ConfusionPair | null>(null);

  const pairs = confusionsQ.data?.items ?? [];

  if (confusionsQ.isLoading) {
    return (
      <div className="space-y-2 p-1" data-testid="confusions-loading">
        <div className="h-12 animate-pulse rounded bg-gray-100" />
        <div className="h-12 animate-pulse rounded bg-gray-100" />
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="confusions-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-gray-500">
          记录与哪些同层级产品容易混淆，供人工核对与后续识别消歧参考。
        </p>
        {!readOnly && !showAdd ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setShowAdd(true)}
            data-testid="confusion-add"
          >
            + 添加混淆关系
          </Button>
        ) : null}
      </div>

      <CatalogError error={confusionsQ.error ?? m.archive.error ?? m.restore.error} />

      {showAdd ? (
        <AddPairForm
          level={level}
          targetId={targetId}
          familyId={familyId}
          onClose={() => setShowAdd(false)}
        />
      ) : null}

      {pairs.length === 0 && !showAdd ? (
        <div
          className="rounded border border-dashed border-gray-300 bg-gray-50 px-4 py-6 text-center"
          data-testid="confusion-empty"
        >
          <p className="text-sm text-gray-600">暂无易混淆产品记录。</p>
          <p className="mt-1 text-xs text-gray-400">
            如果该产品与其他产品外观相近、容易认错，建议登记并写明区分特征。
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {pairs.map((pair) => {
            const other = otherSide(pair, targetId);
            const archived = pair.status === "archived";
            const featureCount = pair.distinguishing_features?.length ?? 0;
            return (
              <li
                key={pair.id}
                className="space-y-1.5 rounded border border-gray-200 bg-white p-3"
                data-testid={`confusion-row-${pair.id}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-gray-400">易与</span>
                  {other ? (
                    <button
                      type="button"
                      onClick={() => onSelect({ level, id: other.id })}
                      className="max-w-[14rem] truncate text-sm font-medium text-brand hover:underline"
                      data-testid={`confusion-goto-${pair.id}`}
                      title={other.name_zh}
                    >
                      {other.name_zh}
                    </button>
                  ) : (
                    <span className="text-sm text-gray-400">（对方节点不存在）</span>
                  )}
                  <span className="text-xs text-gray-400">混淆</span>
                  <Chip tone={SEVERITY_META[pair.severity].tone}>
                    {SEVERITY_META[pair.severity].label}严重度
                  </Chip>
                  <span className="text-[11px] text-gray-400">{featureCount} 条区分特征</span>
                  {archived ? <Chip tone="muted">已归档</Chip> : null}
                </div>
                {pair.reason ? (
                  <p className="break-words text-xs text-gray-600">{pair.reason}</p>
                ) : null}
                {!readOnly ? (
                  <div className="flex flex-wrap justify-end gap-1.5">
                    {!archived ? (
                      <>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setEditingPair(pair)}
                          data-testid={`confusion-features-${pair.id}`}
                        >
                          区分特征
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => m.archive.mutate(pair.id)}
                          loading={m.archive.isPending}
                          data-testid={`confusion-archive-${pair.id}`}
                        >
                          归档
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => m.restore.mutate(pair.id)}
                        loading={m.restore.isPending}
                        data-testid={`confusion-restore-${pair.id}`}
                      >
                        恢复
                      </Button>
                    )}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {editingPair ? (
        <FeaturesDialog pair={editingPair} onClose={() => setEditingPair(null)} />
      ) : null}
    </div>
  );
}
