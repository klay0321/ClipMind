"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { UnassignedWorkbench } from "@/components/product-media/UnassignedWorkbench";
import { ProductSectionTabs } from "@/components/products/ProductSectionTabs";
import {
  usePmFamilyItems,
  useDismissVisualCandidate,
  usePmMutations,
  usePmSuggestions,
  usePmSummary,
  usePmUnassigned,
} from "@/lib/hooks";
import type { FamilyMediaSummary, ProductMediaItem } from "@/lib/types";
import { cn } from "@/lib/cn";

const KIND_TABS = [
  { key: "image", label: "普通图片" },
  { key: "video", label: "视频" },
  { key: "shot", label: "Shot" },
  { key: "final_video", label: "最终成片" },
] as const;

const ORIGIN_LABELS: Record<string, string> = {
  manual: "人工",
  bulk_manual: "批量人工",
  path_or_filename_confirmed: "路径/文件名确认",
  visual_suggestion_confirmed: "视觉候选确认",
  text_suggestion_confirmed: "文本候选确认",
  migration_or_legacy: "历史迁移",
};

function RoleBadge({ role }: { role: string }) {
  return role === "primary" ? (
    <span className="rounded bg-brand/10 px-1.5 py-0.5 text-[11px] font-medium text-brand">
      主产品
    </span>
  ) : (
    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">关联</span>
  );
}

function ItemThumb({ it }: { it: ProductMediaItem }) {
  if (it.type === "shot" && it.shot_id != null) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={`/api/shots/${it.shot_id}/keyframe`} alt="" className="h-20 w-full rounded-t object-cover" />;
  }
  if (it.asset_id != null) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={`/api/assets/${it.asset_id}/poster`} alt="" className="h-20 w-full rounded-t object-cover" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />;
  }
  return <div className="h-20 w-full rounded-t bg-gray-100" />;
}

/** 未标注队列卡片（多选 + 候选建议 + 视觉候选拒绝）。 */
export function UnassignedCard({
  it,
  selected,
  onToggle,
  onPickSuggestion,
  onDismissVisual,
}: {
  it: ProductMediaItem;
  selected: boolean;
  onToggle: () => void;
  onPickSuggestion: (familyId: number, origin: string) => void;
  onDismissVisual?: (candidateId: number) => void;
}) {
  const targetId = it.type === "shot" ? it.shot_id : it.asset_id;
  const targetType = it.type === "shot" ? "shot" : "asset";
  const [showSugg, setShowSugg] = useState(false);
  const sugg = usePmSuggestions(targetType, showSugg ? (targetId ?? null) : null);
  return (
    <div
      className={cn(
        "rounded border bg-white text-xs",
        selected ? "border-brand ring-1 ring-brand" : "border-gray-200",
      )}
      data-testid={`unassigned-${it.type}-${targetId}`}
    >
      <button type="button" className="block w-full" onClick={onToggle}>
        <ItemThumb it={it} />
      </button>
      <div className="space-y-1 p-2">
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            data-testid={`select-${it.type}-${targetId}`}
          />
          <span className="truncate text-gray-700">
            {it.type === "shot" ? `镜头 #${it.shot_id}（序 ${it.sequence_no}）` : it.filename}
          </span>
        </label>
        <div className="flex items-center justify-between text-gray-400">
          <span>
            {it.type === "shot" ? `素材 #${it.asset_id}` : it.media_kind}
            {it.duration != null ? ` · ${it.duration.toFixed(1)}s` : ""}
          </span>
          <button
            type="button"
            className="text-brand hover:underline"
            onClick={() => setShowSugg((v) => !v)}
            data-testid={`toggle-sugg-${it.type}-${targetId}`}
          >
            候选建议
          </button>
        </div>
        {showSugg ? (
          <div className="space-y-1 rounded bg-gray-50 p-1.5" data-testid="suggestion-box">
            {sugg.isLoading ? <p className="text-gray-400">加载中…</p> : null}
            {(sugg.data ?? []).map((s) => (
              <div
                key={`${s.family_id}-${s.suggestion_type}`}
                className="flex items-stretch gap-1"
              >
                <button
                  type="button"
                  onClick={() => onPickSuggestion(s.family_id, s.origin_on_confirm)}
                  className="block w-full rounded border border-gray-200 bg-white px-1.5 py-1 text-left hover:border-brand"
                  data-testid={`suggestion-${s.family_id}`}
                >
                  <span className="font-medium text-gray-800">{s.family_name}</span>
                  {s.suggestion_type === "visual" ? (
                    <span
                      className="ml-1 rounded bg-purple-50 px-1 py-0.5 text-[10px] font-medium text-purple-700"
                      data-testid={`visual-badge-${s.family_id}`}
                    >
                      {s.matched_text}
                    </span>
                  ) : (
                    <span className="ml-1 text-gray-400">
                      {s.matched_in}命中「{s.matched_text}」
                    </span>
                  )}
                </button>
                {s.suggestion_type === "visual" && s.candidate_id != null ? (
                  <button
                    type="button"
                    title="不是该产品（拒绝后不再提示此组合）"
                    onClick={() => onDismissVisual?.(s.candidate_id as number)}
                    className="shrink-0 rounded border border-gray-200 bg-white px-1.5 text-gray-400 hover:border-red-300 hover:text-red-500"
                    data-testid={`dismiss-visual-${s.family_id}`}
                  >
                    ✕
                  </button>
                ) : null}
              </div>
            ))}
            {sugg.data && sugg.data.length === 0 ? (
              <p className="text-gray-400">无确定性候选（可手动选择产品）</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ProductMediaView() {
  const params = useSearchParams();
  const summary = usePmSummary();
  const { create, update, remove, bulk } = usePmMutations();
  const dismissVisual = useDismissVisualCandidate();
  const [familyId, setFamilyId] = useState<number | null>(() => {
    const f = params.get("family");
    return f ? Number(f) : null;
  });
  const [tab, setTab] = useState<string>("image");
  const [page, setPage] = useState(1);
  const [includeHistorical, setIncludeHistorical] = useState(false);
  const items = usePmFamilyItems(familyId, tab, page, includeHistorical);
  // PM-UX：任务导向主 Tab——待归类工作台（默认）| 按产品浏览。
  // URL 带 ?family= 时直达浏览 Tab（既有深链语义不变）。
  const [workTab, setWorkTab] = useState<"unassigned" | "browse">(() =>
    params.get("family") ? "browse" : "unassigned",
  );

  const fam: FamilyMediaSummary | undefined = useMemo(
    () => summary.data?.find((f) => f.family_id === familyId),
    [summary.data, familyId],
  );


  return (
    <div className="space-y-6">
      <div>
        <ProductSectionTabs current="media" />
        <h1 className="text-xl font-semibold text-gray-900">产品素材库</h1>
        <p className="mt-1 text-xs text-gray-500">
          人工确认的产品素材关系是系统正式事实；文件名、路径与 AI 结果只是辅助候选。
        </p>
      </div>

      {/* PM-UX：任务导向主 Tab */}
      <div className="flex gap-1 border-b border-gray-200" role="tablist" aria-label="工作台分区">
        {(
          [
            { key: "unassigned", label: "待归类工作台" },
            { key: "browse", label: "按产品浏览" },
          ] as const
        ).map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={workTab === t.key}
            data-testid={`pm-worktab-${t.key}`}
            onClick={() => setWorkTab(t.key)}
            className={cn(
              "rounded-t px-3 py-2 text-sm",
              workTab === t.key
                ? "border-b-2 border-brand font-medium text-brand"
                : "text-gray-500 hover:text-gray-800",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {workTab === "unassigned" ? (
        <UnassignedWorkbench families={summary.data ?? []} />
      ) : (
        <>
      {/* 产品列表 */}
      <section className="rounded-lg border border-gray-200 bg-white p-4" data-testid="pm-family-list">
        <h2 className="mb-2 text-sm font-medium text-gray-700">产品列表</h2>
        {summary.isLoading ? <p className="text-xs text-gray-400">加载中…</p> : null}
        <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
          {(summary.data ?? []).map((f) => (
            <button
              key={f.family_id}
              type="button"
              onClick={() => {
                setFamilyId(f.family_id);
                setPage(1);
              }}
              data-testid={`pm-family-${f.family_id}`}
              className={cn(
                "rounded border p-2 text-left text-xs",
                familyId === f.family_id
                  ? "border-brand ring-1 ring-brand"
                  : "border-gray-200 hover:border-gray-300",
              )}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-gray-800">{f.name_zh}</span>
                <span className="text-gray-400">{f.code}</span>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-gray-500">
                <span>型号 {f.variant_count}</span>
                <span>参考图 {f.reference_count}</span>
                <span>图片 {f.image_count}</span>
                <span>视频 {f.video_count}</span>
                <span>Shot {f.shot_link_count}</span>
                <span>使用 {f.confirmed_usage_count}</span>
                <span className="text-gray-400">
                  {f.onboarding_status ?? "未入驻"} / {f.status}
                </span>
                <span
                  className={
                    f.coverage_status === "资料较完整"
                      ? "rounded bg-emerald-50 px-1 py-0.5 text-[10px] text-emerald-700"
                      : "rounded bg-amber-50 px-1 py-0.5 text-[10px] text-amber-700"
                  }
                  data-testid={`coverage-${f.family_id}`}
                >
                  {f.coverage_status || "—"}
                </span>
              </div>
            </button>
          ))}
          {summary.data && summary.data.length === 0 ? (
            <p className="text-xs text-gray-400">
              暂无产品——先到 <Link className="text-brand" href="/products">产品库</Link> 创建
            </p>
          ) : null}
        </div>
      </section>

      {/* 产品素材详情 */}
      {familyId != null ? (
        <section className="rounded-lg border border-gray-200 bg-white p-4" data-testid="pm-family-detail">
          <div className="mb-2 flex flex-wrap items-center gap-3">
            <h2 className="text-sm font-medium text-gray-700">
              {fam ? `${fam.name_zh} 的素材` : `产品 #${familyId} 的素材`}
            </h2>
            <div className="flex gap-1">
              {KIND_TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  data-testid={`pm-tab-${t.key}`}
                  onClick={() => {
                    setTab(t.key);
                    setPage(1);
                  }}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-xs",
                    tab === t.key
                      ? "border-brand bg-brand/10 text-brand"
                      : "border-gray-300 text-gray-600",
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>
            {tab === "shot" ? (
              <label className="flex items-center gap-1 text-xs text-gray-500">
                <input
                  type="checkbox"
                  checked={includeHistorical}
                  onChange={(e) => setIncludeHistorical(e.target.checked)}
                  data-testid="pm-include-historical"
                />
                含历史镜头
              </label>
            ) : null}
            <Link href="/products" className="ml-auto text-xs text-brand hover:underline">
              参考图在产品库管理 →
            </Link>
          </div>
          {items.data ? (
            <>
              <p className="mb-2 text-xs text-gray-400" data-testid="pm-items-total">
                共 {items.data.total} 项
              </p>
              <ul className="grid gap-2 md:grid-cols-3 lg:grid-cols-4" data-testid="pm-items">
                {items.data.items.map((it) => (
                  <li
                    key={`${it.type}-${it.asset_id ?? it.shot_id ?? it.final_video_id}`}
                    className="rounded border border-gray-200 bg-white text-xs"
                    data-testid={`pm-item-${it.type}-${it.asset_id ?? it.shot_id ?? it.final_video_id}`}
                  >
                    <ItemThumb it={it} />
                    <div className="space-y-1 p-2">
                      <p className="truncate font-medium text-gray-800">
                        {it.type === "shot"
                          ? `镜头 #${it.shot_id}${it.is_historical ? "（历史）" : ""}`
                          : it.type === "final_video"
                            ? it.title
                            : it.filename}
                      </p>
                      <div className="flex flex-wrap items-center gap-1 text-gray-500">
                        {it.link ? <RoleBadge role={it.link.role} /> : null}
                        {it.link ? (
                          <span className="text-gray-400">
                            {ORIGIN_LABELS[it.link.origin] ?? it.link.origin}
                          </span>
                        ) : null}
                        {it.type === "shot" ? (
                          <span
                            className={cn(
                              "rounded px-1 py-0.5 text-[10px]",
                              it.source === "shot_override"
                                ? "bg-purple-50 text-purple-700"
                                : "bg-gray-100 text-gray-500",
                            )}
                          >
                            {it.source === "shot_override" ? "本镜头独立设置" : "继承自视频"}
                          </span>
                        ) : null}
                      </div>
                      <div className="flex gap-2 text-[11px]">
                        {it.asset_id != null && it.type !== "shot" ? (
                          <Link href={`/assets?open=${it.asset_id}`} className="text-brand">
                            打开素材
                          </Link>
                        ) : null}
                        {it.type === "shot" ? (
                          <Link href={`/shots/${it.shot_id}`} className="text-brand">
                            打开镜头
                          </Link>
                        ) : null}
                        {it.type === "final_video" ? (
                          <Link href={`/final-videos`} className="text-brand">
                            打开成片
                          </Link>
                        ) : null}
                        {it.link ? (
                          <>
                            {it.link.role !== "primary" ? (
                              <button
                                type="button"
                                className="text-gray-500 hover:text-brand"
                                onClick={() =>
                                  update.mutate({
                                    linkId: it.link!.id,
                                    body: { role: "primary" },
                                  })
                                }
                                data-testid={`set-primary-${it.link.id}`}
                              >
                                设为主产品
                              </button>
                            ) : null}
                            <button
                              type="button"
                              className="text-red-500 hover:underline"
                              onClick={() => remove.mutate(it.link!.id)}
                              data-testid={`unlink-${it.link.id}`}
                            >
                              解除关联
                            </button>
                          </>
                        ) : null}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
              {items.data.items.length === 0 ? (
                <p className="text-xs text-gray-400">该类型暂无素材</p>
              ) : null}
            </>
          ) : (
            <p className="text-xs text-gray-400">加载中…</p>
          )}
        </section>
      ) : null}

        </>
      )}
    </div>
  );
}
