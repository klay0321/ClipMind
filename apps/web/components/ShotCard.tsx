"use client";

import { ShotStatusBadge } from "@/components/StatusBadge";
import { shotThumbnailUrl } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import type { Shot } from "@/lib/types";

export function ShotCard({
  shot,
  selected,
  onSelect,
  onDownload,
  downloading = false,
  favorite,
}: {
  shot: Shot;
  selected: boolean;
  onSelect: (id: number) => void;
  onDownload?: (id: number) => void;
  downloading?: boolean;
  // 可选收藏动作槽（避免复制卡片；由调用方传入 FavoriteButton）
  favorite?: React.ReactNode;
}) {
  return (
    <div
      data-testid="shot-card"
      className={`relative flex flex-col overflow-hidden rounded-lg border transition ${
        selected ? "border-brand ring-1 ring-brand" : "border-gray-200 hover:border-gray-300"
      }`}
    >
      <button
        type="button"
        onClick={() => onSelect(shot.id)}
        className="relative block aspect-video w-full bg-gray-100 text-left"
        title="查看镜头详情"
      >
        {shot.has_thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={shotThumbnailUrl(shot.id)}
            alt={`镜头 ${shot.sequence_no}`}
            className="h-full w-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-[10px] text-gray-400">
            无缩略图
          </div>
        )}
        <span className="absolute left-1 top-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white">
          #{shot.sequence_no}
        </span>
        <span className="absolute bottom-1 right-1 rounded bg-black/60 px-1 py-0.5 text-[10px] text-white">
          {shot.duration.toFixed(1)}s
        </span>
      </button>
      {favorite ? <div className="absolute right-1 top-1">{favorite}</div> : null}
      <div className="space-y-1 p-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-700">
            {formatDuration(shot.start_time)} – {formatDuration(shot.end_time)}
          </span>
          <ShotStatusBadge status={shot.status} />
        </div>
        {shot.asset_filename ? (
          <div className="truncate text-[11px] text-gray-400" title={shot.asset_filename}>
            来源：{shot.asset_filename}
          </div>
        ) : null}
        <div className="flex items-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => onSelect(shot.id)}
            className="flex-1 rounded border border-gray-300 px-2 py-1 text-[11px] text-gray-700 hover:bg-gray-50"
          >
            查看
          </button>
          {onDownload ? (
            <button
              type="button"
              onClick={() => onDownload(shot.id)}
              disabled={downloading || !shot.has_proxy}
              className="flex-1 rounded bg-brand px-2 py-1 text-[11px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-brand-dark"
            >
              {downloading ? "导出中…" : "↓ 下载"}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
