"use client";

import { StatGrid, type StatItem } from "@/components/ui/Stat";
import { useShotCompleteness } from "@/lib/hooks";

// 镜头拆解完整度：全部来自真实 /stats/completeness 聚合，回答「AI 拆镜头是否做完整」。
export function ShotCompletenessBar() {
  const q = useShotCompleteness();
  const d = q.data;

  if (q.isLoading) {
    return <div className="h-16 animate-pulse rounded-lg border border-gray-100 bg-gray-50" />;
  }
  if (!d) return null;

  const items: StatItem[] = [
    { label: "素材", value: d.total_assets },
    { label: "镜头总数", value: d.total_shots },
    { label: "AI 已分析", value: d.ai_analyzed_shots, tone: "brand" },
    { label: "待人工确认", value: d.pending_review_shots, tone: d.pending_review_shots > 0 ? "warning" : "neutral" },
    { label: "已确认", value: d.confirmed_shots, tone: "success" },
    { label: "可搜索", value: d.searchable_shots, tone: "info" },
    { label: "风险", value: d.risk_shots, tone: d.risk_shots > 0 ? "danger" : "neutral" },
    { label: "AI 失败", value: d.ai_failed_shots, tone: d.ai_failed_shots > 0 ? "danger" : "muted" },
  ];

  return (
    <section className="rounded-lg border border-gray-100 bg-white p-3 shadow-sm" data-testid="shot-completeness">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
        镜头拆解完整度（全库真实统计）
      </h2>
      <StatGrid items={items} className="lg:grid-cols-8" />
    </section>
  );
}
