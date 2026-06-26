// 语义搜索结果卡（网格）。展示关键帧、时间码、时长、画幅、产品、审核状态、风险、综合匹配度、
// 主要匹配理由与 degraded 标记。所有数据只读后端 item，不在前端推测或重算。
"use client";

import { formatAspect } from "@/lib/search";
import { formatDuration } from "@/lib/format";
import type { SearchResultItem } from "@/lib/types";

import { MatchScore } from "./MatchScore";
import { ResultMedia } from "./ResultMedia";
import { DegradedTag, ProductMatchTag, ReviewStatusBadge, StaleBadge } from "./SearchBadges";

export function SearchResultCard({
  item,
  selected,
  onSelect,
  onPreview,
}: {
  item: SearchResultItem;
  selected: boolean;
  onSelect: (shotId: number) => void;
  onPreview: (shotId: number) => void;
}) {
  const primaryReason = item.matched_reasons[0];
  const riskCount = item.risk_warnings.length;
  return (
    <div
      data-testid="search-result-card"
      className={`flex flex-col overflow-hidden rounded-lg border bg-white transition ${
        selected ? "border-brand ring-1 ring-brand" : "border-gray-200 hover:border-gray-300"
      }`}
    >
      <div
        role="button"
        tabIndex={0}
        aria-pressed={selected}
        onClick={() => onSelect(item.shot_id)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect(item.shot_id);
          }
        }}
        className="relative block w-full cursor-pointer text-left focus:outline-none focus:ring-2 focus:ring-brand"
        title="查看匹配详情"
      >
        <ResultMedia item={item} onPreview={onPreview} className="aspect-video w-full" />
        <div className="absolute right-1 top-1">
          <MatchScore matchPercent={item.match_percent} size="sm" />
        </div>
        <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white">
          #{item.sequence_no}
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-1.5 p-2.5">
        <div className="flex items-center justify-between text-[11px] text-gray-500">
          <span>
            {formatDuration(item.start_time)} – {formatDuration(item.end_time)}
          </span>
          <span>
            {item.duration.toFixed(1)}s · {formatAspect(item.asset.width, item.asset.height, item.asset.orientation)}
          </span>
        </div>

        {item.product ? (
          <div className="flex items-center gap-1">
            <span className="truncate text-xs font-medium text-gray-800" title={item.product.name}>
              {item.product.name}
            </span>
            <ProductMatchTag kind={item.product.match_kind} />
          </div>
        ) : null}

        <div className="truncate text-[11px] text-gray-500" title={item.asset.filename}>
          来源：{item.asset.filename}
        </div>

        {primaryReason ? (
          <div
            className="line-clamp-2 rounded bg-emerald-50 px-1.5 py-1 text-[11px] text-emerald-700"
            title={item.matched_reasons.join("；")}
          >
            ✓ {primaryReason}
          </div>
        ) : null}

        {riskCount > 0 ? (
          <div
            className="line-clamp-1 rounded bg-red-100 px-1.5 py-1 text-[11px] text-red-700"
            data-testid="card-risk"
            title={item.risk_warnings.join("；")}
          >
            ⚠ 风险：{item.risk_warnings[0]}
            {riskCount > 1 ? ` +${riskCount - 1}` : ""}
          </div>
        ) : null}

        <div className="mt-auto flex flex-wrap items-center gap-1 pt-1">
          <ReviewStatusBadge status={item.review_status} />
          <StaleBadge stale={item.review_is_stale} />
          <DegradedTag degraded={item.embedding_degraded} />
        </div>
      </div>
    </div>
  );
}
