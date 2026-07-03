"use client";

import Link from "next/link";

import { useAssetLegacySummary } from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";

import { LegacyStateChip, ReviewStatusChip } from "./legacyShared";

/** 素材详情只读"历史使用证据"区。
 * 弱证据展示：legacy_used_unknown 显示为"历史上用过（次数未知）"，
 * 绝不显示成"已使用 N 次"；审核入口在 /usage-evidence 中心。
 */
export function AssetLegacyPanel({ assetId }: { assetId: number }) {
  const summary = useAssetLegacySummary(assetId);
  const data = summary.data;

  if (summary.isLoading || !data) {
    return null;
  }
  const total =
    data.accepted_count + data.pending_count + data.rejected_count + data.conflict_count;
  if (total === 0) {
    // 无任何证据时不占据抽屉空间（详情页保持整洁）
    return null;
  }

  return (
    <section data-testid="asset-legacy-panel">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
        历史使用证据
      </h3>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span data-testid="asset-legacy-state">
          <LegacyStateChip state={data.legacy_usage_state} />
        </span>
        <span className="text-xs text-gray-400">
          待审 {data.pending_count} · 已接受 {data.accepted_count} · 已驳回 {data.rejected_count}
          {data.conflict_count > 0 ? ` · 冲突 ${data.conflict_count}` : ""}
        </span>
      </div>
      <p className="mb-2 text-[11px] text-gray-400">
        证据来自历史路径标记，只说明素材可能曾被使用；次数与对应成片均未知，不计入正式使用统计。
      </p>
      <ul className="max-h-40 space-y-1 overflow-y-auto" data-testid="asset-legacy-list">
        {data.evidences.map((ev) => (
          <li
            key={ev.id}
            className="flex items-center justify-between gap-2 rounded border border-gray-100 px-2 py-1 text-xs"
          >
            <span className="min-w-0 flex-1 truncate text-gray-600" title={ev.location_relative_path ?? ev.matched_component}>
              <code className="rounded bg-gray-100 px-1">{ev.matched_component}</code>
              <span className="ml-1 text-gray-400">{formatDateTime(ev.last_observed_at)}</span>
            </span>
            <ReviewStatusChip status={ev.review_status} />
          </li>
        ))}
      </ul>
      <Link
        href="/usage-evidence"
        className="mt-2 inline-block text-xs text-brand hover:underline"
      >
        去历史使用证据中心审核 →
      </Link>
    </section>
  );
}
