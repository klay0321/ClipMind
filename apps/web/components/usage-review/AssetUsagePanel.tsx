"use client";

import Link from "next/link";

import { useAssetUsageSummary, useUsageReviewItems } from "@/lib/hooks";

/** Asset 详情统一使用摘要（§十）：
 * 正式使用次数 / 正式候选数量 / 历史证据待审核 / 历史上用过（次数未知）/ 冲突证据。
 * 「历史上用过（次数未知）」是状态陈述——绝不显示数字次数。
 */
export function AssetUsagePanel({ assetId }: { assetId: number }) {
  const summary = useAssetUsageSummary(assetId);
  const proposed = useUsageReviewItems({
    page: 1,
    page_size: 1,
    item_type: "final_video_usage",
    review_group: "needs_review",
    asset_id: assetId,
  });
  const s = summary.data;
  if (summary.isLoading || !s) return null;

  const rows: { label: string; value: string; testId: string }[] = [
    {
      label: "正式使用次数",
      value: String(s.confirmed_usage_count),
      testId: "usage-formal-confirmed",
    },
    {
      label: "正式候选数量",
      value: String(proposed.data?.total ?? 0),
      testId: "usage-formal-proposed",
    },
    {
      label: "历史证据待审核",
      value: String(s.pending_legacy_evidence_count),
      testId: "usage-legacy-pending",
    },
  ];

  return (
    <section data-testid="asset-usage-panel">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
        使用情况（正式与历史并列，口径不同不相加）
      </h3>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
        {rows.map((r) => (
          <div key={r.label} className="flex justify-between gap-2">
            <dt className="text-gray-400">{r.label}</dt>
            <dd className="text-gray-700" data-testid={r.testId}>
              {r.value}
            </dd>
          </div>
        ))}
        {s.conflict_legacy_evidence_count > 0 ? (
          <div className="flex justify-between gap-2">
            <dt className="text-gray-400">冲突证据</dt>
            <dd className="text-red-700" data-testid="usage-legacy-conflict">
              {s.conflict_legacy_evidence_count}
            </dd>
          </div>
        ) : null}
      </dl>
      {s.legacy_usage_state === "legacy_used_unknown" ? (
        <p className="mt-1.5 text-xs text-amber-800" data-testid="usage-legacy-unknown">
          历史上用过（次数未知）
        </p>
      ) : null}
      <Link
        href="/usage-review"
        className="mt-2 inline-block text-xs text-brand hover:underline"
      >
        进入使用记录中心 →
      </Link>
    </section>
  );
}
