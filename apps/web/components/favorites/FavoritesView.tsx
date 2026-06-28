// 收藏页：按四种 target_type 过滤的收藏网格。
// 镜头/搜索结果/脚本匹配结果 → 打开镜头详情页；素材 → 打开素材关联镜头库。
// 可移除收藏（只删收藏关系，不删镜头/素材）。所有数据只读后端。
"use client";

import { useState } from "react";
import Link from "next/link";

import { InlineError } from "@/components/projects/widgets";
import { PreviewModal } from "@/components/PreviewModal";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { TopNav } from "@/components/TopNav";
import { assetPosterUrl, shotThumbnailUrl } from "@/lib/api";
import { FAVORITE_TYPE_LABELS } from "@/lib/exports";
import { formatDateTime, formatDuration } from "@/lib/format";
import { useDeleteFavorite, useFavorites } from "@/lib/hooks";
import type { FavoriteOut, FavoriteTargetType } from "@/lib/types";

const TYPE_OPTIONS: { value: "" | FavoriteTargetType; label: string }[] = [
  { value: "", label: "全部" },
  { value: "shot", label: "镜头" },
  { value: "search_result", label: "搜索结果" },
  { value: "script_match_result", label: "脚本匹配结果" },
  { value: "asset", label: "素材" },
];

const PAGE_SIZE = 24;

export function FavoritesView() {
  const [targetType, setTargetType] = useState<"" | FavoriteTargetType>("");
  const [page, setPage] = useState(1);
  const [previewId, setPreviewId] = useState<number | null>(null);

  const query = useFavorites(targetType || undefined, page, PAGE_SIZE);
  const del = useDeleteFavorite();
  const data = query.data;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="favorites" />
      <main className="mx-auto max-w-7xl space-y-4 p-4" data-testid="favorites">
        <header>
          <h1 className="text-xl font-semibold text-gray-900">收藏</h1>
          <p className="text-sm text-gray-500">
            收藏的镜头、搜索结果、脚本匹配结果与素材。移除收藏只删除收藏关系，不删除镜头或素材。
          </p>
        </header>

        <div className="flex flex-wrap gap-1.5" role="group" aria-label="收藏类型筛选">
          {TYPE_OPTIONS.map((o) => (
            <button
              key={o.value || "all"}
              type="button"
              data-testid={`favorite-filter-${o.value || "all"}`}
              onClick={() => {
                setTargetType(o.value);
                setPage(1);
              }}
              aria-pressed={targetType === o.value}
              className={`rounded-md border px-2.5 py-1 text-sm font-medium ${
                targetType === o.value
                  ? "border-brand bg-brand-light text-brand-dark"
                  : "border-gray-300 text-gray-600 hover:bg-gray-50"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>

        <InlineError error={del.error} />

        {query.isLoading ? (
          <Loading rows={4} />
        ) : query.isError ? (
          <ErrorState message={(query.error as Error).message} onRetry={() => void query.refetch()} />
        ) : !data || data.items.length === 0 ? (
          <Empty
            title="暂无收藏"
            description="在镜头卡、搜索结果或匹配候选上点击「收藏」，即可在此查看。"
          />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {data.items.map((fav) => (
                <FavoriteItem
                  key={fav.id}
                  fav={fav}
                  onPreview={setPreviewId}
                  onRemove={() => del.mutate(fav.id)}
                  removing={del.isPending}
                />
              ))}
            </div>

            {data.total > PAGE_SIZE ? (
              <div className="flex items-center justify-between px-1 text-sm text-gray-600">
                <span>
                  共 {data.total} 项 · 第 {page} / {totalPages} 页
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    data-testid="favorites-page-prev"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="rounded-md border border-gray-300 bg-white px-3 py-1 disabled:opacity-50 hover:bg-gray-50"
                  >
                    上一页
                  </button>
                  <button
                    type="button"
                    data-testid="favorites-page-next"
                    onClick={() => setPage((p) => p + 1)}
                    disabled={page >= totalPages}
                    className="rounded-md border border-gray-300 bg-white px-3 py-1 disabled:opacity-50 hover:bg-gray-50"
                  >
                    下一页
                  </button>
                </div>
              </div>
            ) : null}
          </>
        )}
        <PreviewModal shotId={previewId} onClose={() => setPreviewId(null)} />
      </main>
    </div>
  );
}

function FavoriteItem({
  fav,
  onPreview,
  onRemove,
  removing,
}: {
  fav: FavoriteOut;
  onPreview: (shotId: number) => void;
  onRemove: () => void;
  removing: boolean;
}) {
  const isAsset = fav.target_type === "asset";
  const shotId = fav.shot_id;
  const assetId = fav.asset_id;
  const thumbUrl = isAsset
    ? assetId != null
      ? assetPosterUrl(assetId)
      : null
    : shotId != null
      ? shotThumbnailUrl(shotId)
      : null;
  const title = isAsset
    ? (fav.asset?.filename ?? (assetId != null ? `素材 #${assetId}` : "素材"))
    : (fav.shot?.asset_filename ?? (shotId != null ? `镜头 #${shotId}` : "镜头"));
  const sub = isAsset
    ? fav.asset
      ? `${formatDuration(fav.asset.duration)}`
      : ""
    : fav.shot
      ? `#${fav.shot.sequence_no} · ${fav.shot.duration.toFixed(1)}s`
      : "";

  return (
    <div
      data-testid={`favorite-item-${fav.id}`}
      className="flex flex-col overflow-hidden rounded-lg border border-gray-200 bg-white"
    >
      <div className="relative aspect-video w-full bg-gray-100">
        {thumbUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumbUrl} alt="" className="h-full w-full object-cover" loading="lazy" />
        ) : (
          <div className="flex h-full items-center justify-center text-[10px] text-gray-400">
            无缩略图
          </div>
        )}
        <span className="absolute left-1 top-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white">
          {FAVORITE_TYPE_LABELS[fav.target_type]}
        </span>
        {!isAsset && shotId != null ? (
          <button
            type="button"
            aria-label={`预览镜头 #${shotId}`}
            onClick={() => onPreview(shotId)}
            className="absolute bottom-1 right-1 flex h-6 w-6 items-center justify-center rounded-full bg-black/55 text-[11px] text-white hover:bg-black/75"
          >
            ▶
          </button>
        ) : null}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-2">
        <div className="truncate text-xs font-medium text-gray-800" title={title}>
          {title}
        </div>
        {sub ? <div className="text-[11px] text-gray-400">{sub}</div> : null}
        <div className="text-[10px] text-gray-400">收藏于 {formatDateTime(fav.created_at)}</div>
        <div className="mt-auto flex items-center gap-1 pt-1">
          {isAsset && assetId != null ? (
            <Link
              href={`/shots?asset_id=${assetId}`}
              className="flex-1 rounded border border-gray-300 px-2 py-1 text-center text-[11px] text-gray-700 hover:bg-gray-50"
            >
              打开
            </Link>
          ) : shotId != null ? (
            <Link
              href={`/shots/${shotId}`}
              className="flex-1 rounded border border-gray-300 px-2 py-1 text-center text-[11px] text-gray-700 hover:bg-gray-50"
            >
              打开
            </Link>
          ) : null}
          <button
            type="button"
            data-testid={`remove-favorite-${fav.id}`}
            onClick={onRemove}
            disabled={removing}
            className="rounded border border-gray-300 px-2 py-1 text-[11px] text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          >
            移除
          </button>
        </div>
      </div>
    </div>
  );
}
