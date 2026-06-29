// 剪辑清单：摘要统计 + 逐段行（含推荐镜头/理由/缺口/时长建议/标记/查看候选）。
// 系统推荐绝不标成「人工已确认」；重复/失效/风险/需确认醒目标识；缺口段保留成行。
// 导出统一放到工作台顶栏的「导出剪辑清单 ▾」，本表不再内嵌多个导出按钮。
"use client";

import { MediaThumb } from "@/components/ui/MediaThumb";
import { shotKeyframeUrl } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { useScriptEditList } from "@/lib/hooks";
import {
  durationRangeLabel,
  durationStatusLabel,
  scorePercent,
  selectionStatusLabel,
  selectionStatusTone,
} from "@/lib/script";
import type { EditListRow, EditListSummary } from "@/lib/types";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { MatchExplanation } from "@/components/search/MatchExplanation";

function SummaryBar({ s }: { s: EditListSummary }) {
  const cells: [string, string | number, string?][] = [
    ["段落总数", s.total_segments],
    ["已匹配", s.matched_segments, "text-emerald-700"],
    ["已选择", s.selected_segments],
    ["已锁定", s.locked_segments, "text-brand-dark"],
    ["系统推荐", s.recommended_segments],
    ["缺口", s.gap_segments, "text-red-700"],
    ["风险段", s.risk_segments, "text-amber-700"],
    ["重复镜头", s.duplicate_shot_count, s.duplicate_shot_count > 0 ? "text-amber-700" : undefined],
  ];
  return (
    <div className="space-y-1" data-testid="editlist-summary">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {cells.map(([label, val, tone]) => (
          <span key={label} className="text-gray-500">
            {label} <strong className={tone ?? "text-gray-800"}>{val}</strong>
          </span>
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 text-[11px] text-gray-400">
        <span>
          目标总时长 {durationRangeLabel(s.target_total_duration_min, s.target_total_duration_max)}
        </span>
        <span>建议成片总时长 ≈ {s.suggested_total_duration.toFixed(1)}s</span>
      </div>
      {s.allocation_warnings.length ? (
        <ul className="flex flex-wrap gap-1" data-testid="allocation-warnings">
          {s.allocation_warnings.map((w, i) => (
            <li key={i} className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
              {w}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Row({
  row,
  onPreview,
  onViewCandidates,
}: {
  row: EditListRow;
  onPreview: (shotId: number) => void;
  onViewCandidates?: (segmentId: number) => void;
}) {
  const hasShot = row.shot_id != null;
  return (
    <div
      data-testid="editlist-row"
      data-selection={row.selection_status}
      className={`grid grid-cols-[40px_1.4fr_140px_1.6fr] gap-3 border-b border-gray-100 px-2 py-3 last:border-b-0 max-md:grid-cols-1 max-md:gap-1.5 ${
        row.shot_invalid ? "bg-red-50" : row.risk_warnings.length ? "bg-amber-50/40" : ""
      }`}
    >
      {/* 段号 + 当前状态 */}
      <div className="flex flex-col items-start gap-1">
        <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-white">
          {row.segment_order}
        </span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${selectionStatusTone(row.selection_status)}`}>
          {selectionStatusLabel(row.selection_status)}
        </span>
      </div>

      {/* 脚本原文 + 目标时长 */}
      <div className="min-w-0">
        <p className="line-clamp-3 text-xs text-gray-700">{row.segment_text}</p>
        <p className="mt-1 text-[10px] text-gray-400">
          目标时长 {durationRangeLabel(row.target_duration_min, row.target_duration_max)}
        </p>
      </div>

      {/* 推荐镜头 / 缺口 */}
      <div>
        {hasShot ? (
          <div className="space-y-1">
            <MediaThumb
              src={shotKeyframeUrl(row.shot_id!)}
              alt={`段 ${row.segment_order} 推荐镜头 #${row.shot_id} 关键帧`}
              ratio="video"
              overlay={
                <button
                  type="button"
                  aria-label={`预览镜头 #${row.shot_id}`}
                  onClick={() => onPreview(row.shot_id!)}
                  className="absolute left-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-black/55 text-[11px] text-white hover:bg-black/75"
                >
                  ▶
                </button>
              }
            />
            <div className="flex flex-wrap items-center gap-1 text-[10px] text-gray-500">
              <span>镜头 #{row.shot_id}</span>
              {row.match_score != null ? (
                <span className="font-medium text-brand-dark">{scorePercent(row.match_score)}%</span>
              ) : null}
            </div>
            {row.source_start != null && row.source_end != null ? (
              <p className="text-[10px] text-gray-400">
                源 {formatDuration(row.source_start)}–{formatDuration(row.source_end)} ·{" "}
                建议 {formatDuration(row.suggested_in)}–{formatDuration(row.suggested_out)} ·{" "}
                {durationStatusLabel(row.duration_status)}
              </p>
            ) : null}
            <div className="flex flex-wrap gap-1">
              {row.product_name ? <span className="text-[10px] text-gray-500">{row.product_name}</span> : null}
              {row.scene ? <span className="text-[10px] text-gray-400">· {row.scene}</span> : null}
              {row.action ? <span className="text-[10px] text-gray-400">· {row.action}</span> : null}
            </div>
            <div className="flex flex-wrap gap-1">
              {row.reused ? (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700" data-testid="row-reused">
                  重复镜头
                </span>
              ) : null}
              {row.shot_invalid ? (
                <span className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] text-red-700" data-testid="row-invalid">
                  镜头失效
                </span>
              ) : null}
              {row.requires_human_confirmation ? (
                <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">需人工确认</span>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="rounded border border-dashed border-red-200 bg-red-50 p-2 text-[11px] text-red-700" data-testid="row-gap">
            缺口：本段无合适镜头
          </div>
        )}
      </div>

      {/* 理由 / 缺口 / 补拍 / 操作 */}
      <div className="min-w-0 space-y-1.5">
        <MatchExplanation
          matchedReasons={row.matched_reasons}
          unmatched={row.unmatched_requirements}
          riskWarnings={row.risk_warnings}
          max={5}
        />
        {row.gap_reasons.length ? (
          <div className="text-[11px] text-red-700">
            <span className="font-medium">缺口原因：</span>
            {row.gap_reasons.join("；")}
          </div>
        ) : null}
        {row.reshoot_recommendation.length ? (
          <div className="text-[11px] text-gray-600">
            <span className="font-medium">补拍建议：</span>
            {row.reshoot_recommendation.join("；")}
          </div>
        ) : null}
        {onViewCandidates ? (
          <button
            type="button"
            data-testid={`row-view-candidates-${row.segment_id}`}
            onClick={() => onViewCandidates(row.segment_id)}
            className="inline-flex items-center rounded border border-gray-300 bg-white px-2 py-0.5 text-[11px] text-gray-700 hover:bg-gray-50"
          >
            查看候选 / 改选 →
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function EditListTab({
  scriptId,
  active,
  onPreview,
  onViewCandidates,
}: {
  scriptId: number;
  active: boolean;
  onPreview: (shotId: number) => void;
  onViewCandidates?: (segmentId: number) => void;
}) {
  const q = useScriptEditList(scriptId, active);
  const data = q.data;
  return (
    <div className="space-y-3" data-testid="editlist-tab">
      <div>
        <h2 className="text-sm font-semibold text-gray-800">剪辑清单</h2>
        <p className="text-[11px] text-gray-500">
          每段一行，缺口段也保留；确认后可在上方「导出剪辑清单」生成多种格式给剪辑师。
        </p>
      </div>

      {data ? <SummaryBar s={data.summary} /> : null}

      {q.isLoading ? (
        <Loading rows={4} />
      ) : q.isError ? (
        <ErrorState message={(q.error as Error)?.message ?? "加载失败"} onRetry={() => void q.refetch()} />
      ) : data == null || data.rows.length === 0 ? (
        <Empty title="还没有剪辑清单" description="先拆段并进行匹配，剪辑清单会按段落生成。" />
      ) : (
        <div className="rounded-lg border border-gray-200 bg-white" aria-busy={q.isFetching}>
          {data.rows.map((r) => (
            <Row key={r.segment_id} row={r} onPreview={onPreview} onViewCandidates={onViewCandidates} />
          ))}
        </div>
      )}
    </div>
  );
}
