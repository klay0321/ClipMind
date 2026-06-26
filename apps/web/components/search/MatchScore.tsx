// 综合匹配度徽章：只读后端 match_percent，明确标注「综合匹配度」（不是概率），不增加虚假精度。

import { formatMatchPercent } from "@/lib/search";

function band(percent: number): { ring: string; text: string } {
  if (percent >= 75) return { ring: "border-emerald-300 bg-emerald-50", text: "text-emerald-700" };
  if (percent >= 50) return { ring: "border-brand/40 bg-brand-light", text: "text-brand-dark" };
  if (percent >= 25) return { ring: "border-amber-300 bg-amber-50", text: "text-amber-700" };
  return { ring: "border-gray-200 bg-gray-50", text: "text-gray-500" };
}

export function MatchScore({
  matchPercent,
  size = "md",
}: {
  matchPercent: number;
  size?: "sm" | "md";
}) {
  const b = band(matchPercent);
  const big = size === "md";
  return (
    <div
      data-testid="match-score"
      className={`flex flex-col items-center justify-center rounded-lg border ${b.ring} ${
        big ? "px-3 py-2" : "px-2 py-1"
      }`}
    >
      <span className="text-[10px] text-gray-500">综合匹配度</span>
      <span className={`font-semibold ${b.text} ${big ? "text-xl" : "text-base"}`}>
        {formatMatchPercent(matchPercent)}
      </span>
    </div>
  );
}
