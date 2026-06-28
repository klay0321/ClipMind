// 候选详情抽屉：分项得分（缺失=未参与）+ 规则理由 + 预览 + 进入完整镜头详情。Esc 关闭、恢复焦点。
"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import { formatDuration } from "@/lib/format";
import { scorePercent, subScoreLabel } from "@/lib/script";
import type { ScriptCandidate } from "@/lib/types";
import { MatchExplanation } from "@/components/search/MatchExplanation";

import { CandidateMedia } from "./CandidateMedia";

function ScoreRow({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="flex items-center justify-between border-b border-gray-50 py-1 text-xs last:border-b-0">
      <span className="text-gray-500">{label}</span>
      <span className={value == null ? "text-gray-400" : "font-medium text-gray-800"}>
        {subScoreLabel(value)}
      </span>
    </div>
  );
}

export function CandidateDrawer({
  candidate,
  onClose,
  onPreview,
}: {
  candidate: ScriptCandidate | null;
  onClose: () => void;
  onPreview: (shotId: number) => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (candidate == null) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      restoreRef.current?.focus?.();
    };
  }, [candidate, onClose]);

  if (candidate == null) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="候选镜头详情"
        data-testid="candidate-drawer"
        className="h-full w-full max-w-md overflow-y-auto bg-white p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-800">候选镜头 #{candidate.shot_id}</h3>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="关闭详情"
            className="rounded px-2 py-0.5 text-sm text-gray-500 hover:bg-gray-100"
          >
            关闭 ✕
          </button>
        </div>

        <CandidateMedia candidate={candidate} onPreview={onPreview} className="aspect-video w-full" />
        <div className="mt-2 text-[11px] text-gray-500">
          {candidate.start_time != null && candidate.end_time != null
            ? `${formatDuration(candidate.start_time)} – ${formatDuration(candidate.end_time)} · ${(candidate.duration ?? 0).toFixed(1)}s`
            : "时间码未知"}
          {candidate.asset_id != null ? ` · 素材 #${candidate.asset_id}` : ""}
        </div>

        <section className="mt-3">
          <h4 className="mb-1 text-xs font-semibold text-gray-700">
            综合匹配度 {scorePercent(candidate.final_score)}%
          </h4>
          <div className="rounded border border-gray-100 px-2">
            <ScoreRow label="语义" value={candidate.semantic_score} />
            <ScoreRow label="词法" value={candidate.lexical_score} />
            <ScoreRow label="标签" value={candidate.tag_score} />
            <ScoreRow label="产品" value={candidate.product_score} />
            <ScoreRow label="质量" value={candidate.quality_score} />
            <ScoreRow label="审核加权" value={candidate.review_bonus} />
            <ScoreRow label="风险惩罚" value={candidate.risk_penalty} />
          </div>
          <p className="mt-1 text-[10px] text-gray-400">分项分缺失表示该通道未参与，不是 0 分。</p>
        </section>

        <section className="mt-3">
          <MatchExplanation
            matchedReasons={candidate.matched_reasons}
            unmatched={candidate.unmatched_requirements}
            riskWarnings={candidate.risk_warnings}
          />
        </section>

        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => onPreview(candidate.shot_id)}
            disabled={candidate.preview_url == null}
            className="flex-1 rounded border border-gray-300 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            预览视频
          </button>
          <Link
            href={`/shots/${candidate.shot_id}`}
            data-testid="drawer-shot-link"
            className="flex-1 rounded border border-brand px-3 py-1.5 text-center text-xs text-brand hover:bg-brand-light"
          >
            完整镜头详情
          </Link>
        </div>
      </aside>
    </div>
  );
}
