"use client";

import Link from "next/link";

import { formatDateTime } from "@/lib/format";
import type { SearchResultItem, SearchUsageInfo } from "@/lib/types";

/** 结果卡使用状态徽标。
 * 冻结文案：confirmed 才显示"正式使用 N 次"；legacy 显示
 * "历史上可能使用过（次数未知）"（绝不带数字）；proposed 只显示"待确认"。
 */
export function UsageBadge({ usage }: { usage: SearchUsageInfo | null | undefined }) {
  if (!usage) return null;
  const badges: React.ReactNode[] = [];
  if (usage.shot_confirmed_usage_count > 0) {
    badges.push(
      <Link
        key="confirmed"
        href="/usage-review"
        data-testid="usage-badge-confirmed"
        className="rounded bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700 hover:underline"
        title={
          usage.last_confirmed_used_at
            ? `最近使用于 ${formatDateTime(usage.last_confirmed_used_at)}`
            : undefined
        }
      >
        正式使用 {usage.shot_confirmed_usage_count} 次
      </Link>,
    );
  } else {
    badges.push(
      <span
        key="never"
        data-testid="usage-badge-never"
        className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-500"
      >
        未正式使用
      </span>,
    );
  }
  if (usage.accepted_legacy_evidence_count > 0) {
    badges.push(
      <Link
        key="legacy"
        href="/usage-evidence"
        data-testid="usage-badge-legacy"
        className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-800 hover:underline"
      >
        历史上可能使用过（次数未知）
      </Link>,
    );
  }
  if (usage.pending_formal_count > 0) {
    badges.push(
      <span
        key="pending"
        data-testid="usage-badge-pending"
        className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] text-blue-700"
      >
        存在待确认使用记录
      </span>,
    );
  }
  return <div className="flex flex-wrap gap-1">{badges}</div>;
}

/** 排序解释（展开块）：语义相关度 + 各调整项 + 最终分——绝不只给一个"推荐分"。 */
export function UsageExplanation({ item }: { item: SearchResultItem }) {
  if (item.base_score == null || item.final_score == null) return null;
  const reasons = item.usage_reasons ?? [];
  return (
    <div
      className="space-y-1 rounded border border-gray-100 bg-gray-50 px-2.5 py-2 text-xs text-gray-600"
      data-testid="usage-explanation"
    >
      <div className="flex justify-between">
        <span>语义相关度（base）</span>
        <span className="font-mono">{item.base_score.toFixed(4)}</span>
      </div>
      {reasons.map((r) => (
        <div key={r.code} className="flex justify-between" data-testid={`reason-${r.code}`}>
          <span>{r.message}</span>
          <span className={`font-mono ${r.adjustment >= 0 ? "text-emerald-700" : "text-red-600"}`}>
            {r.adjustment >= 0 ? "+" : ""}
            {r.adjustment.toFixed(4)}
          </span>
        </div>
      ))}
      {reasons.length === 0 ? (
        <div className="text-gray-400">无使用调整（default 模式或无使用信号）</div>
      ) : null}
      <div className="flex justify-between border-t border-gray-200 pt-1 font-medium text-gray-800">
        <span>最终分数</span>
        <span className="font-mono">{item.final_score.toFixed(4)}</span>
      </div>
    </div>
  );
}
