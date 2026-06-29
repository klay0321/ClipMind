// 候选镜头卡：综合分 + 关键帧 + 镜头信息 + 规则理由 + 选择/锁定/预览/详情。
// 所有分数与理由直读后端，缺失通道显示「未参与」（绝不当 0），推荐≠人工已确认。
"use client";

import { FavoriteButton } from "@/components/favorites/FavoriteButton";
import { formatDuration } from "@/lib/format";
import { scorePercent } from "@/lib/script";
import type { ScriptCandidate } from "@/lib/types";
import { MatchExplanation } from "@/components/search/MatchExplanation";
import { MatchScore } from "@/components/search/MatchScore";

import { CandidateMedia } from "./CandidateMedia";

export function CandidateCard({
  candidate,
  isSelected,
  isLocked,
  isRecommended,
  lockedElsewhere,
  onSelect,
  onLock,
  onPreview,
  onOpenDetail,
  selecting,
  locking,
}: {
  candidate: ScriptCandidate;
  isSelected: boolean;
  isLocked: boolean;
  isRecommended: boolean;
  lockedElsewhere: boolean;
  onSelect: () => void;
  onLock: () => void;
  onPreview: (shotId: number) => void;
  onOpenDetail: () => void;
  selecting: boolean;
  locking: boolean;
}) {
  const border = isLocked
    ? "border-brand ring-1 ring-brand"
    : isSelected
      ? "border-brand-dark"
      : "border-gray-200";
  return (
    <div
      data-testid="candidate-card"
      data-shot-id={candidate.shot_id}
      data-state={isLocked ? "locked" : isSelected ? "selected" : isRecommended ? "recommended" : "none"}
      className={`grid grid-cols-[72px_104px_1fr_auto] gap-3 rounded-lg border bg-white p-2 max-md:grid-cols-[64px_1fr] max-md:gap-2 ${border}`}
    >
      <div className="flex flex-col items-center gap-1">
        <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-white" title="候选排名">
          #{candidate.rank + 1}
        </span>
        <MatchScore matchPercent={scorePercent(candidate.final_score)} size="sm" />
      </div>

      <button
        type="button"
        onClick={onOpenDetail}
        className="block cursor-pointer focus:outline-none focus:ring-2 focus:ring-brand max-md:hidden"
        title="查看候选详情与分项得分"
      >
        <CandidateMedia candidate={candidate} onPreview={onPreview} className="aspect-video w-full" />
      </button>

      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <button type="button" onClick={onOpenDetail} className="text-xs font-semibold text-gray-900 hover:text-brand">
            镜头 #{candidate.shot_id}
          </button>
          {isLocked ? (
            <span className="rounded bg-brand px-1.5 py-0.5 text-[10px] text-white">🔒 已锁定</span>
          ) : isSelected ? (
            <span className="rounded bg-brand-light px-1.5 py-0.5 text-[10px] text-brand-dark">已选择</span>
          ) : isRecommended ? (
            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">系统推荐</span>
          ) : null}
        </div>
        <div className="text-[10px] text-gray-500">
          {candidate.start_time != null && candidate.end_time != null
            ? `${formatDuration(candidate.start_time)} – ${formatDuration(candidate.end_time)} · ${(candidate.duration ?? 0).toFixed(1)}s`
            : "时间码未知"}
          {candidate.asset_id != null ? ` · 素材 #${candidate.asset_id}` : ""}
        </div>
        <MatchExplanation
          matchedReasons={candidate.matched_reasons}
          unmatched={candidate.unmatched_requirements}
          riskWarnings={candidate.risk_warnings}
          max={5}
        />
      </div>

      <div className="flex flex-col gap-1 max-md:col-span-2 max-md:flex-row">
        <button
          type="button"
          data-testid="candidate-select"
          onClick={onSelect}
          disabled={selecting || isSelected}
          className="rounded border border-brand px-2 py-1 text-[11px] text-brand hover:bg-brand-light disabled:opacity-50"
        >
          {isSelected ? "已选择" : selecting ? "选择中…" : "选择"}
        </button>
        <button
          type="button"
          data-testid="candidate-lock"
          onClick={onLock}
          disabled={locking || isLocked}
          className="rounded border border-brand bg-brand px-2 py-1 text-[11px] text-white hover:bg-brand-dark disabled:opacity-50"
          title={lockedElsewhere ? "替换当前锁定（显式）" : "锁定后重匹配不覆盖"}
        >
          {isLocked ? "已锁定" : locking ? "锁定中…" : lockedElsewhere ? "替换锁定" : "锁定"}
        </button>
        <button
          type="button"
          onClick={() => onPreview(candidate.shot_id)}
          disabled={candidate.preview_url == null}
          className="rounded border border-gray-300 px-2 py-1 text-[11px] text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        >
          预览
        </button>
        <FavoriteButton
          targetType="script_match_result"
          shotId={candidate.shot_id}
          context={{ source: "script_candidate", final_score: candidate.final_score }}
        />
      </div>
    </div>
  );
}
