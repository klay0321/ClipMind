// 分项得分：直接展示后端分项分，缺失通道显示「未参与」（绝不当 0），不在前端重算 final_score。

import { formatSubScore } from "@/lib/search";
import type { SearchResultItem } from "@/lib/types";

interface Row {
  key: string;
  label: string;
  value: number | null;
  signed?: boolean; // 加分/减分项
  tone: string;
}

export function ScoreBreakdown({ item }: { item: SearchResultItem }) {
  const rows: Row[] = [
    { key: "semantic", label: "语义", value: item.semantic_score, tone: "bg-brand" },
    { key: "lexical", label: "关键词", value: item.lexical_score, tone: "bg-sky-500" },
    { key: "tag", label: "标签", value: item.tag_score, tone: "bg-indigo-500" },
    { key: "product", label: "产品", value: item.product_score, tone: "bg-emerald-500" },
    { key: "quality", label: "质量", value: item.quality_score, tone: "bg-amber-500" },
    { key: "review", label: "审核加分", value: item.review_bonus, signed: true, tone: "bg-emerald-400" },
    { key: "risk", label: "风险扣分", value: item.risk_penalty, signed: true, tone: "bg-red-500" },
  ];
  return (
    <div className="space-y-1" data-testid="score-breakdown">
      <div className="text-[11px] font-medium text-gray-500">分项得分</div>
      <ul className="space-y-1">
        {rows.map((r) => {
          const absent = r.value == null;
          const pct = absent ? 0 : Math.round(Math.max(0, Math.min(1, r.value as number)) * 100);
          return (
            <li key={r.key} className="flex items-center gap-2 text-[11px]">
              <span className="w-14 shrink-0 text-gray-500">{r.label}</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100">
                {!absent ? (
                  <div className={`h-full rounded-full ${r.tone}`} style={{ width: `${pct}%` }} />
                ) : null}
              </div>
              <span className={`w-12 shrink-0 text-right ${absent ? "text-gray-300" : "text-gray-600"}`}>
                {absent ? "未参与" : `${r.signed && (r.value as number) > 0 ? "+" : ""}${formatSubScore(r.value)}`}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
