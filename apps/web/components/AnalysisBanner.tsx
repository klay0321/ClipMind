"use client";

import type { ShotAnalysis } from "@/lib/types";

export function AnalysisBanner({
  analysis,
  pending,
}: {
  analysis: ShotAnalysis | undefined;
  pending?: boolean;
}) {
  const status = analysis?.status;
  const active = pending || status === "queued" || status === "running";

  if (!active && status !== "failed" && status !== "completed") return null;

  if (active) {
    const pct = analysis?.progress ?? 0;
    return (
      <div
        data-testid="analysis-banner"
        className="flex items-center gap-3 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700"
      >
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-300 border-t-blue-600" />
        <span>
          镜头分析中… {pct}%
          {analysis ? `（${analysis.completed_shots}/${analysis.total_shots} 镜头）` : ""}
        </span>
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div
        data-testid="analysis-banner"
        className="rounded-lg border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        镜头分析失败：{analysis?.error_message ?? "未知错误"}
      </div>
    );
  }

  return (
    <div
      data-testid="analysis-banner"
      className="rounded-lg border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm text-emerald-700"
    >
      镜头分析完成，共 {analysis?.shot_count ?? 0} 个镜头。
    </div>
  );
}
