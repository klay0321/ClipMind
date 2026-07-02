"use client";

import { useState } from "react";

import { Button, Chip } from "@/components/ui";
import { useRevisions } from "@/lib/hooks";
import type { CatalogLevel, CatalogRevision } from "@/lib/types";

import { CatalogError } from "./widgets";

// 实体类型中文标签（与后端 revision entity_type 白名单对应；受控枚举，非产品值）
const ENTITY_LABELS: Record<string, string> = {
  category: "分类",
  family: "产品",
  variant: "型号",
  sku: "SKU",
  alias: "别名",
  attribute_definition: "属性定义",
  attribute_value: "属性值",
  reference_asset: "参考图",
  readiness_policy: "完整度策略",
  onboarding_review: "入驻审核",
  confusion_pair: "混淆关系",
};

// 动作中文标签（与后端 CATALOG_REVISION_ACTIONS 一致）
const ACTION_LABELS: Record<string, string> = {
  create: "创建",
  update: "更新",
  status: "状态变更",
  archive: "归档",
  restore: "恢复",
  merge: "合并",
  delete: "删除",
  set_primary: "设为主图",
  activate: "激活",
  submit_review: "提交审核",
  approve: "批准",
  request_changes: "退回修改",
  block: "阻止使用",
};

export function entityLabel(t: string): string {
  return ENTITY_LABELS[t] ?? t;
}

export function actionLabel(a: string): string {
  return ACTION_LABELS[a] ?? a;
}

// 逐字段 diff（仅列出变化的字段；值用 JSON 序列化比较）
interface DiffRow {
  key: string;
  from: unknown;
  to: unknown;
}

export function diffFields(
  before: Record<string, unknown> | null,
  after: Record<string, unknown> | null,
): DiffRow[] {
  const keys = Array.from(
    new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})]),
  );
  return keys
    .filter((k) => JSON.stringify(before?.[k]) !== JSON.stringify(after?.[k]))
    .map((k) => ({ key: k, from: before?.[k], to: after?.[k] }));
}

// diff 值展示：undefined=（无）；null=空；布尔=是/否；对象/数组=JSON
function fmtDiffVal(v: unknown): string {
  if (v === undefined) return "（无）";
  if (v === null) return "空";
  if (typeof v === "boolean") return v ? "是" : "否";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// 单条变更行：概要 + 可展开的字段差异 + 原始 JSON 折叠
function RevisionRow({ rev }: { rev: CatalogRevision }) {
  const [expanded, setExpanded] = useState(false);
  const rows = diffFields(rev.before_data, rev.after_data);
  const isCreate = rev.before_data == null && rev.after_data != null;

  return (
    <li className="rounded border border-gray-200 bg-white" data-testid={`revision-row-${rev.id}`}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        data-testid={`revision-toggle-${rev.id}`}
        className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left hover:bg-gray-50"
      >
        <span className="shrink-0 text-[11px] text-gray-400">
          #{rev.revision_number} · {new Date(rev.created_at).toLocaleString()}
        </span>
        <Chip tone="neutral">{entityLabel(rev.entity_type)}</Chip>
        <Chip tone="info">{actionLabel(rev.action)}</Chip>
        {rev.change_summary ? (
          <span className="min-w-0 flex-1 truncate text-xs text-gray-700">
            {rev.change_summary}
          </span>
        ) : null}
        {rev.actor_label ? (
          <span className="shrink-0 text-[11px] text-gray-400">by {rev.actor_label}</span>
        ) : null}
        <span
          className="shrink-0 font-mono text-[10px] text-gray-300"
          title={rev.correlation_id}
        >
          {rev.correlation_id.slice(0, 8)}
        </span>
      </button>

      {expanded ? (
        <div
          className="space-y-2 border-t border-gray-100 px-3 py-2"
          data-testid={`revision-diff-${rev.id}`}
        >
          {rows.length === 0 ? (
            <p className="text-xs text-gray-400">无字段级变更记录。</p>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="text-gray-400">
                <tr>
                  <th className="py-0.5 pr-2 font-medium">字段</th>
                  {!isCreate ? <th className="py-0.5 pr-2 font-medium">变更前</th> : null}
                  <th className="py-0.5 font-medium">{isCreate ? "值" : "变更后"}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rows.map((r) => (
                  <tr key={r.key}>
                    <td className="max-w-[8rem] break-words py-1 pr-2 align-top font-medium text-gray-600">
                      {r.key}
                    </td>
                    {!isCreate ? (
                      <td className="max-w-[12rem] break-words py-1 pr-2 align-top text-gray-500">
                        {fmtDiffVal(r.from)}
                      </td>
                    ) : null}
                    <td className="max-w-[12rem] break-words py-1 align-top text-gray-800">
                      {fmtDiffVal(r.to)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <details className="text-xs">
            <summary className="cursor-pointer text-gray-400 hover:text-gray-600">
              查看原始 JSON
            </summary>
            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded bg-gray-50 p-2 text-[11px] text-gray-600">
              {JSON.stringify(
                { before: rev.before_data, after: rev.after_data },
                null,
                2,
              )}
            </pre>
          </details>
        </div>
      ) : null}
    </li>
  );
}

// 变更历史面板（append-only 只读）：时间线 + 字段差异 + 「加载更多」分页。
export function HistoryPanel({
  level,
  targetId,
}: {
  level: CatalogLevel;
  targetId: number;
}) {
  const [page, setPage] = useState(1);
  const revisionsQ = useRevisions(level, targetId, page);

  const items = revisionsQ.data?.items ?? [];
  const total = revisionsQ.data?.total ?? 0;
  // 后端单次查询上限 200 条；到上限后提示而不是继续加载
  const atServerCap = items.length >= 200;
  const hasMore = items.length < total && !atServerCap;

  if (revisionsQ.isLoading) {
    return (
      <div className="space-y-2 p-1" data-testid="history-loading">
        <div className="h-10 animate-pulse rounded bg-gray-100" />
        <div className="h-10 animate-pulse rounded bg-gray-100" />
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="history-panel">
      <p className="text-xs text-gray-500">
        该节点自身的变更历史（创建/更名/状态/归档/合并），只读、不可修改。
      </p>

      <CatalogError error={revisionsQ.error} />

      {items.length === 0 ? (
        <div
          className="rounded border border-dashed border-gray-300 bg-gray-50 px-4 py-6 text-center"
          data-testid="history-empty"
        >
          <p className="text-sm text-gray-600">暂无变更记录。</p>
        </div>
      ) : (
        <>
          <ul className="space-y-1.5">
            {items.map((rev) => (
              <RevisionRow key={rev.id} rev={rev} />
            ))}
          </ul>
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-gray-400">
              已显示 {items.length} / {total} 条
              {atServerCap && items.length < total ? "（仅显示最近 200 条）" : ""}
            </span>
            {hasMore ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setPage((p) => p + 1)}
                loading={revisionsQ.isFetching}
                data-testid="history-more"
              >
                加载更多
              </Button>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}
