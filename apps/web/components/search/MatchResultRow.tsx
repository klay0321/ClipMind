// 画面描述匹配结果行（对照 UI 参考图 04）：匹配度 | 镜头预览 | 镜头信息+理由 | 操作。
// 下载片段经详情抽屉复用既有导出流程；预览按需打开代理视频。
"use client";

import { formatDuration } from "@/lib/format";
import type { DescriptionMatchItem } from "@/lib/types";

import { MatchExplanation } from "./MatchExplanation";
import { MatchScore } from "./MatchScore";
import { ResultMedia } from "./ResultMedia";
import {
  DegradedTag,
  HumanConfirmTag,
  ProductMatchTag,
  RecommendationBadge,
  ReviewStatusBadge,
} from "./SearchBadges";

export function MatchResultRow({
  item,
  onSelect,
  onPreview,
}: {
  item: DescriptionMatchItem;
  onSelect: (shotId: number) => void;
  onPreview: (shotId: number) => void;
}) {
  const title = item.product?.name ?? `镜头 #${item.sequence_no}`;
  return (
    <div
      data-testid="match-result-row"
      className="grid grid-cols-[88px_120px_1fr_auto] gap-3 border-b border-gray-100 px-1 py-3 last:border-b-0 max-md:grid-cols-[72px_1fr] max-md:gap-2"
    >
      {/* 匹配度 + 推荐等级 */}
      <div className="flex flex-col items-center gap-1">
        <MatchScore matchPercent={item.match_percent} size="md" />
        <RecommendationBadge level={item.recommendation_level} />
      </div>

      {/* 预览缩略图 */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => onSelect(item.shot_id)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect(item.shot_id);
          }
        }}
        className="block cursor-pointer focus:outline-none focus:ring-2 focus:ring-brand max-md:hidden"
        title="查看匹配详情"
      >
        <ResultMedia item={item} onPreview={onPreview} className="aspect-video w-full" />
      </div>

      {/* 信息 + 理由 */}
      <div className="min-w-0 space-y-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => onSelect(item.shot_id)}
            className="truncate text-sm font-semibold text-gray-900 hover:text-brand"
            title={title}
          >
            {title}
          </button>
          {item.product ? <ProductMatchTag kind={item.product.match_kind} /> : null}
          <ReviewStatusBadge status={item.review_status} />
          <HumanConfirmTag requires={item.requires_human_confirmation} />
          <DegradedTag degraded={item.embedding_degraded} />
        </div>
        <div className="text-[11px] text-gray-500">
          {formatDuration(item.start_time)} – {formatDuration(item.end_time)} · {item.duration.toFixed(1)}s ·
          来源：<span className="text-gray-600">{item.asset.filename}</span>
        </div>
        <MatchExplanation
          matchedReasons={item.matched_reasons}
          unmatched={item.unmatched_requirements}
          riskWarnings={item.risk_warnings}
          max={6}
        />
      </div>

      {/* 操作 */}
      <div className="flex flex-col gap-1.5 max-md:col-span-2 max-md:flex-row">
        <button
          type="button"
          data-testid="row-download"
          onClick={() => onSelect(item.shot_id)}
          className="rounded-md border border-brand px-3 py-1.5 text-xs font-medium text-brand hover:bg-brand-light"
          title="打开详情并导出可下载片段"
        >
          ↓ 下载片段
        </button>
        <button
          type="button"
          onClick={() => onPreview(item.shot_id)}
          disabled={item.preview_url == null}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          预览
        </button>
      </div>
    </div>
  );
}
