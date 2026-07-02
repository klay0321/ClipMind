"use client";

import { useEffect, useState } from "react";

import { Button, Chip, Dialog, TextInput } from "@/components/ui";
import {
  useActivateReadinessPolicy,
  useCreateReadinessPolicy,
  useEvaluateReadiness,
  useReadiness,
  useReadinessPolicies,
} from "@/lib/hooks";
import {
  REFERENCE_ANGLES,
  type AttributeTargetLevel,
  type ReadinessCheck,
  type ReadinessPolicy,
} from "@/lib/types";

import { ANGLE_LABELS } from "./ReferenceGallery";
import { CatalogError, CatalogStatusBadge } from "./widgets";

// check key → 中文标签（受控枚举，含阻塞项 key；非产品值）
const CHECK_LABELS: Record<string, string> = {
  name_zh: "中文名称",
  category: "归属分类",
  name_en: "英文名称",
  alias: "别名",
  required_attributes: "必填属性",
  identity_attributes: "身份关键属性",
  minimum_references: "参考图数量",
  primary_reference: "主参考图",
  required_angles: "必备拍摄角度",
  parent_active: "上级已启用",
  sku_for_variant: "型号下 SKU",
  // 阻塞项 key
  target_merged: "实体已合并",
  target_archived: "实体已归档",
  invalid_references: "无效参考图",
};

export function checkLabel(key: string): string {
  return CHECK_LABELS[key] ?? key;
}

// current/required 的通用格式化：布尔→是/否；数组→角度中文顿号连接；null→-
function fmtVal(v: unknown): string {
  if (v == null) return "-";
  if (typeof v === "boolean") return v ? "是" : "否";
  if (Array.isArray(v)) {
    if (v.length === 0) return "无";
    return v
      .map((x) => ANGLE_LABELS[x as keyof typeof ANGLE_LABELS] ?? String(x))
      .join("、");
  }
  return String(v);
}

// 新建完整度策略弹窗（category 级；创建为 draft，需显式激活后生效）
function CreatePolicyDialog({
  open,
  onClose,
  categoryId,
}: {
  open: boolean;
  onClose: () => void;
  categoryId: number;
}) {
  const create = useCreateReadinessPolicy();
  const [name, setName] = useState("");
  const [minRefs, setMinRefs] = useState("3");
  const [minIdentity, setMinIdentity] = useState("0");
  const [requirePrimary, setRequirePrimary] = useState(true);
  const [requireNameEn, setRequireNameEn] = useState(false);
  const [requireAlias, setRequireAlias] = useState(false);
  const [angles, setAngles] = useState<string[]>([]);

  useEffect(() => {
    if (open) {
      setName("");
      setMinRefs("3");
      setMinIdentity("0");
      setRequirePrimary(true);
      setRequireNameEn(false);
      setRequireAlias(false);
      setAngles([]);
    }
  }, [open]);

  const toggleAngle = (a: string) => {
    setAngles((prev) => (prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a]));
  };

  const submit = () => {
    create.mutate(
      {
        category_id: categoryId,
        name: name.trim() || undefined,
        min_reference_count: minRefs === "" ? undefined : Number(minRefs),
        min_identity_attribute_count: minIdentity === "" ? undefined : Number(minIdentity),
        require_primary_reference: requirePrimary,
        require_name_en: requireNameEn,
        require_alias: requireAlias,
        required_angles: angles.length > 0 ? angles : undefined,
      },
      { onSuccess: () => onClose() },
    );
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="新建完整度策略"
      widthClass="max-w-md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={create.isPending}>
            取消
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={create.isPending}
            data-testid="policy-create-submit"
          >
            创建（草稿）
          </Button>
        </>
      }
    >
      <div className="space-y-3" data-testid="policy-create-dialog">
        <TextInput
          label="策略名称（可选，默认按版本命名）"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={255}
          data-testid="policy-name"
        />
        <div className="grid grid-cols-2 gap-3">
          <TextInput
            label="最少参考图数量"
            type="number"
            min={0}
            max={100}
            value={minRefs}
            onChange={(e) => setMinRefs(e.target.value)}
            data-testid="policy-min-refs"
          />
          <TextInput
            label="最少身份关键属性数"
            type="number"
            min={0}
            max={50}
            value={minIdentity}
            onChange={(e) => setMinIdentity(e.target.value)}
            data-testid="policy-min-identity"
          />
        </div>
        <div className="flex flex-wrap gap-4 text-sm text-gray-700">
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={requirePrimary}
              onChange={(e) => setRequirePrimary(e.target.checked)}
              data-testid="policy-require-primary"
            />
            必须有主参考图
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={requireNameEn}
              onChange={(e) => setRequireNameEn(e.target.checked)}
              data-testid="policy-require-name-en"
            />
            必须有英文名称
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={requireAlias}
              onChange={(e) => setRequireAlias(e.target.checked)}
              data-testid="policy-require-alias"
            />
            必须有别名
          </label>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-gray-600">必备拍摄角度（可多选）</p>
          <div className="flex flex-wrap gap-2">
            {REFERENCE_ANGLES.map((a) => (
              <label
                key={a}
                className="flex items-center gap-1 rounded border border-gray-200 px-2 py-1 text-xs text-gray-700"
              >
                <input
                  type="checkbox"
                  checked={angles.includes(a)}
                  onChange={() => toggleAngle(a)}
                  data-testid={`policy-angle-${a}`}
                />
                {ANGLE_LABELS[a]}
              </label>
            ))}
          </div>
        </div>
        <p className="text-[11px] text-gray-400">
          创建后为草稿状态，需在下方策略列表中「激活」才对该分类生效；激活会归档旧版本策略。
        </p>
        <CatalogError error={create.error} />
      </div>
    </Dialog>
  );
}

// 分类策略小节：当前生效策略 / 草稿列表 + 激活入口 / 无策略时「系统默认策略」提示
function PolicySection({
  categoryId,
  readOnly,
}: {
  categoryId: number | null;
  readOnly: boolean;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const policiesQ = useReadinessPolicies(categoryId);
  const activate = useActivateReadinessPolicy(categoryId);

  if (categoryId == null) {
    return (
      <p className="text-xs text-gray-400" data-testid="policy-no-category">
        该节点未归属分类，无法配置分类级完整度策略（当前使用系统默认策略）。
      </p>
    );
  }

  const items: ReadinessPolicy[] = policiesQ.data?.items ?? [];
  const active = items.find((p) => p.status === "active");
  // 未生效版本（draft/paused）可激活
  const inactive = items.filter((p) => p.status !== "active" && p.status !== "archived");

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-medium text-gray-600">完整度策略（分类级）</h4>
        {!readOnly ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setShowCreate(true)}
            data-testid="policy-create-open"
          >
            + 新建策略
          </Button>
        ) : null}
      </div>

      {active ? (
        <div
          className="flex flex-wrap items-center gap-2 rounded border border-gray-200 bg-white px-3 py-2 text-xs"
          data-testid="policy-active"
        >
          <Chip tone="success">生效中</Chip>
          <span className="truncate font-medium text-gray-800">{active.name}</span>
          <span className="text-gray-400">v{active.version}</span>
        </div>
      ) : (
        <p
          className="rounded border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-700"
          data-testid="policy-default-notice"
        >
          该分类尚无生效策略，当前使用系统默认策略。可新建并激活分类专属策略。
        </p>
      )}

      {inactive.length > 0 ? (
        <ul className="space-y-1">
          {inactive.map((p) => (
            <li
              key={p.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded border border-gray-100 bg-gray-50 px-3 py-1.5 text-xs"
              data-testid={`policy-row-${p.id}`}
            >
              <span className="flex min-w-0 items-center gap-2">
                <CatalogStatusBadge status={p.status} />
                <span className="truncate text-gray-700">{p.name}</span>
                <span className="shrink-0 text-gray-400">v{p.version}</span>
              </span>
              {!readOnly ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => activate.mutate(p.id)}
                  loading={activate.isPending}
                  data-testid={`policy-activate-${p.id}`}
                >
                  激活
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      <CatalogError error={policiesQ.error ?? activate.error} />

      <CreatePolicyDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        categoryId={categoryId}
      />
    </div>
  );
}

// 资料完整度面板：总分 + 检查表 + 缺失项 + 阻塞项 + 重新评估 + 分类策略管理。
// 全部数据来自后端确定性计算，前端绝不重算分数、不显示任何 AI 识别状态。
export function ReadinessPanel({
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
  const readinessQ = useReadiness(level, targetId);
  const evaluate = useEvaluateReadiness(level, targetId);
  const r = readinessQ.data;

  if (readinessQ.isLoading) {
    return (
      <div className="space-y-2 p-1" data-testid="readiness-loading">
        <div className="h-16 animate-pulse rounded bg-gray-100" />
        <div className="h-24 animate-pulse rounded bg-gray-100" />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="readiness-panel">
      <CatalogError error={readinessQ.error ?? evaluate.error} />

      {r ? (
        <>
          {/* 总览：分数 / 完整徽标 / 策略版本 / 重新评估 */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-gray-200 bg-white p-3">
            <div className="flex flex-wrap items-center gap-3">
              <div>
                <span className="text-2xl font-semibold text-gray-900" data-testid="readiness-score">
                  {r.score}
                </span>
                <span className="text-sm text-gray-400"> / 100</span>
              </div>
              <span data-testid="readiness-complete">
                {r.complete ? (
                  <Chip tone="success" dot>
                    资料完整
                  </Chip>
                ) : (
                  <Chip tone="warning" dot>
                    资料不完整
                  </Chip>
                )}
              </span>
              <span className="text-xs text-gray-500" data-testid="readiness-policy-version">
                {r.policy_version === 0 ? "系统默认策略" : `策略版本 v${r.policy_version}`}
              </span>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => evaluate.mutate()}
              loading={evaluate.isPending}
              data-testid="readiness-evaluate"
            >
              重新评估
            </Button>
          </div>

          {/* 阻塞项：明确错误，醒目显示（高分也不能忽略） */}
          {r.blocking_items.length > 0 ? (
            <div
              role="alert"
              className="space-y-1 rounded border border-red-300 bg-red-50 px-3 py-2"
              data-testid="readiness-blocking"
            >
              <p className="text-xs font-semibold text-red-800">阻塞项（须处理后才能提交审核）</p>
              <ul className="space-y-0.5">
                {r.blocking_items.map((b) => (
                  <li key={b.key} className="break-words text-xs text-red-700">
                    <span className="font-medium">{checkLabel(b.key)}</span>：{b.detail}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {/* 缺失项：逐条列出（绝不只显示一个百分比） */}
          {r.missing_items.length > 0 ? (
            <div
              className="space-y-1 rounded border border-amber-200 bg-amber-50 px-3 py-2"
              data-testid="readiness-missing"
            >
              <p className="text-xs font-semibold text-amber-800">
                缺失项（{r.missing_items.length} 项）
              </p>
              <ul className="space-y-0.5">
                {r.missing_items.map((m) => (
                  <li key={m.key} className="break-words text-xs text-amber-800">
                    <span className="font-medium">{checkLabel(m.key)}</span>
                    ：当前 {fmtVal(m.current)}，要求 {fmtVal(m.required)}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {/* 检查表：每项通过与否 + 当前值/要求值 */}
          <div className="overflow-hidden rounded border border-gray-200">
            <table className="w-full text-left text-xs">
              <thead className="bg-gray-50 text-gray-500">
                <tr>
                  <th className="px-3 py-1.5 font-medium">检查项</th>
                  <th className="px-3 py-1.5 font-medium">结果</th>
                  <th className="px-3 py-1.5 font-medium">当前</th>
                  <th className="px-3 py-1.5 font-medium">要求</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {r.checks.map((c: ReadinessCheck) => (
                  <tr key={c.key} data-testid={`readiness-check-${c.key}`}>
                    <td className="px-3 py-1.5 text-gray-700">{checkLabel(c.key)}</td>
                    <td className="px-3 py-1.5">
                      {c.passed ? (
                        <span className="font-medium text-green-600" aria-label="通过">
                          ✓
                        </span>
                      ) : (
                        <span className="font-medium text-red-500" aria-label="未通过">
                          ✗
                        </span>
                      )}
                    </td>
                    <td className="max-w-[10rem] break-words px-3 py-1.5 text-gray-600">
                      {fmtVal(c.current)}
                    </td>
                    <td className="max-w-[10rem] break-words px-3 py-1.5 text-gray-500">
                      {fmtVal(c.required)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-[11px] text-gray-400">
            完整度是资料准备程度的统计，不代表 AI 已能识别该产品（自动识别尚未启用）。
            评估时间 {new Date(r.evaluated_at).toLocaleString()}
          </p>
        </>
      ) : null}

      <div className="border-t border-gray-100 pt-3">
        <PolicySection categoryId={categoryId} readOnly={readOnly} />
      </div>
    </div>
  );
}
