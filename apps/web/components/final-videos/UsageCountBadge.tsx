"use client";

import type { ShotUsageCount } from "@/lib/types";

/** 镜头卡片上的只读使用次数徽标（仅 confirmed 计入正式使用次数）。 */
export function UsageCountBadge({ count }: { count: ShotUsageCount | undefined }) {
  if (!count) return null;
  if (count.confirmed_usage_count > 0) {
    return (
      <span
        data-testid="usage-count-badge"
        title={`已被 ${count.confirmed_usage_count} 条成片确认使用${
          count.proposed_count ? `，另有 ${count.proposed_count} 条候选待确认` : ""
        }`}
        className="rounded bg-emerald-600/90 px-1.5 py-0.5 text-[10px] font-medium text-white"
      >
        使用 {count.confirmed_usage_count} 次
      </span>
    );
  }
  if (count.proposed_count > 0) {
    return (
      <span
        data-testid="usage-count-badge"
        title={`${count.proposed_count} 条候选引用待人工确认（未计入使用次数）`}
        className="rounded bg-amber-500/90 px-1.5 py-0.5 text-[10px] font-medium text-white"
      >
        候选 {count.proposed_count}
      </span>
    );
  }
  return null;
}
