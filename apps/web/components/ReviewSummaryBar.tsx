"use client";

import { useReviewSummary } from "@/lib/hooks";

const OVERALL_LABEL: Record<string, string> = {
  not_started: "未开始",
  running: "分析中",
  completed: "已完成",
  partially_reviewed: "部分已审",
  pending_review: "待审核",
  failed: "有失败",
  mixed: "混合",
};

// 素材级 AI 审核汇总（参考图 02）：真实计数，来自 /assets/{id}/review-summary（投影口径）。
export function ReviewSummaryBar({ assetId }: { assetId: number }) {
  const { data: s } = useReviewSummary(assetId);
  if (!s) return null;

  const stat = (label: string, n: number, tone = "text-gray-700") => (
    <span className="flex items-center gap-1">
      <span className="text-gray-400">{label}</span>
      <span className={`font-medium ${tone}`}>{n}</span>
    </span>
  );

  return (
    <div
      data-testid="review-summary"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-gray-100 bg-white px-3 py-2 text-xs shadow-sm"
    >
      <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">
        AI：{OVERALL_LABEL[s.ai_overall_status] ?? s.ai_overall_status}
      </span>
      {stat("镜头", s.total_shots)}
      {stat("待审核", s.pending_review_count + s.unreviewed_count, "text-amber-700")}
      {stat("已确认", s.confirmed_count + s.modified_count, "text-emerald-700")}
      {s.rejected_count > 0 ? stat("已驳回", s.rejected_count, "text-red-600") : null}
      {s.stale_review_count > 0 ? stat("待复审", s.stale_review_count, "text-amber-700") : null}
      {s.risk_shot_count > 0 ? stat("风险", s.risk_shot_count, "text-red-600") : null}
      {s.primary_product ? (
        <span className="text-gray-500">主产品：{s.primary_product.name}</span>
      ) : null}
    </div>
  );
}
