// 镜头匹配详情抽屉。叠加搜索专属解释（分项分 + 理由/不匹配/风险 + 产品），下方复用既有
// ShotDetail（代理播放/关键帧/导出下载/审核面板），不复制一套新的镜头详情数据结构。
"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";

import { FavoriteButton } from "@/components/favorites/FavoriteButton";
import { ShotDetail } from "@/components/ShotDetail";
import type { DescriptionMatchItem, SearchResultItem } from "@/lib/types";

import { MatchExplanation } from "./MatchExplanation";
import { MatchScore } from "./MatchScore";
import { ScoreBreakdown } from "./ScoreBreakdown";
import {
  DegradedTag,
  HumanConfirmTag,
  ProductMatchTag,
  RecommendationBadge,
  ReviewStatusBadge,
  StaleBadge,
} from "./SearchBadges";

function isMatchItem(i: SearchResultItem | DescriptionMatchItem): i is DescriptionMatchItem {
  return "recommendation_level" in i;
}

export function SearchResultDrawer({
  item,
  onClose,
}: {
  item: SearchResultItem | DescriptionMatchItem | null;
  onClose: () => void;
}) {
  const asideRef = useRef<HTMLElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const open = item != null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // 打开时把焦点移入抽屉；关闭时恢复到此前聚焦的元素
  useEffect(() => {
    if (!open) return;
    restoreRef.current = (document.activeElement as HTMLElement | null) ?? null;
    asideRef.current?.focus();
    return () => {
      restoreRef.current?.focus?.();
    };
  }, [open]);

  if (item == null) return null;
  const matchItem = isMatchItem(item) ? item : null;

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/40"
      data-testid="result-drawer"
      onClick={onClose}
    >
      <aside
        ref={asideRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        aria-label={`镜头 #${item.sequence_no} 匹配详情`}
        className="h-full w-full max-w-md overflow-y-auto bg-white shadow-xl focus:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-gray-100 bg-white/95 px-4 py-3 backdrop-blur">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-gray-900">镜头 #{item.sequence_no} · 匹配详情</h2>
          </div>
          <div className="flex items-center gap-2">
            <FavoriteButton
              targetType="search_result"
              shotId={item.shot_id}
              context={{ source: "search_drawer", match_percent: item.match_percent }}
            />
            <button
              type="button"
              onClick={onClose}
              aria-label="关闭详情"
              data-testid="drawer-close"
              className="rounded px-2 py-0.5 text-sm text-gray-500 hover:bg-gray-100"
            >
              关闭 ✕
            </button>
          </div>
        </div>

        <div className="space-y-4 p-4">
          {/* 搜索专属解释块 */}
          <section className="space-y-3 rounded-lg border border-gray-100 bg-gray-50/60 p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="flex flex-wrap items-center gap-1.5">
                {item.product ? (
                  <>
                    <span className="text-sm font-medium text-gray-800">{item.product.name}</span>
                    <ProductMatchTag kind={item.product.match_kind} />
                  </>
                ) : (
                  <span className="text-sm text-gray-500">未关联产品</span>
                )}
                <ReviewStatusBadge status={item.review_status} />
                <StaleBadge stale={item.review_is_stale} />
                <DegradedTag degraded={item.embedding_degraded} />
                {matchItem ? <RecommendationBadge level={matchItem.recommendation_level} /> : null}
                {matchItem ? <HumanConfirmTag requires={matchItem.requires_human_confirmation} /> : null}
              </div>
              <MatchScore matchPercent={item.match_percent} size="md" />
            </div>

            {matchItem && matchItem.target_requirements.length > 0 ? (
              <div className="space-y-1" data-testid="target-requirements">
                <div className="text-[11px] font-medium text-gray-500">目标画面要求</div>
                <ul className="flex flex-wrap gap-1">
                  {matchItem.target_requirements.map((r, i) => (
                    <li key={`${r}-${i}`} className="rounded bg-white px-1.5 py-0.5 text-[11px] text-gray-600">
                      {r}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <MatchExplanation
              matchedReasons={item.matched_reasons}
              unmatched={item.unmatched_requirements}
              riskWarnings={item.risk_warnings}
            />

            <ScoreBreakdown item={item} />
          </section>

          {/* 复用既有镜头详情：代理播放 / 关键帧 / 导出下载 / 审核（含场景/动作/镜头类型/风险） */}
          <section className="rounded-lg border border-gray-100">
            <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
              <span className="text-xs font-semibold text-gray-600">镜头详情 · 预览 · 导出 · 审核</span>
              <Link
                href={`/shots/${item.shot_id}`}
                className="text-[11px] text-brand hover:underline"
                data-testid="drawer-detail-link"
              >
                打开完整详情页 →
              </Link>
            </div>
            <ShotDetail shotId={item.shot_id} />
          </section>
        </div>
      </aside>
    </div>
  );
}
