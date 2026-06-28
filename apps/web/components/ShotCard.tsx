"use client";

import { ShotStatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { MediaThumb } from "@/components/ui/MediaThumb";
import { shotThumbnailUrl } from "@/lib/api";
import { cn } from "@/lib/cn";
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
      className={cn(
        "relative flex h-full flex-col overflow-hidden rounded-lg border bg-white transition",
        selected ? "border-brand ring-1 ring-brand" : "border-gray-200 hover:border-gray-300",
      )}
    >
      <button
        type="button"
        onClick={() => onSelect(shot.id)}
        className="relative block w-full text-left"
        title="查看镜头详情"
      >
        <MediaThumb
          src={shot.has_thumbnail ? shotThumbnailUrl(shot.id) : null}
          alt={`镜头 ${shot.sequence_no}`}
          ratio="video"
          rounded="rounded-none"
          overlay={
            <>
              <span className="absolute left-1 top-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white">
                #{shot.sequence_no}
              </span>
              <span className="absolute bottom-1 right-1 rounded bg-black/60 px-1 py-0.5 text-[10px] text-white">
                {shot.duration.toFixed(1)}s
              </span>
            </>
          }
        />
      </button>
      {favorite ? <div className="absolute right-1 top-1">{favorite}</div> : null}
      <div className="flex flex-1 flex-col gap-1 p-2">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-xs text-gray-700">
            {formatDuration(shot.start_time)} – {formatDuration(shot.end_time)}
          </span>
          <ShotStatusBadge status={shot.status} />
        </div>
        {shot.asset_filename ? (
          <div className="truncate text-[11px] text-gray-400" title={shot.asset_filename}>
            来源：{shot.asset_filename}
          </div>
        ) : null}
        <div className="mt-auto flex items-center gap-2 pt-1">
          <Button size="sm" variant="secondary" className="flex-1" onClick={() => onSelect(shot.id)}>
            查看
          </Button>
          {onDownload ? (
            <Button
              size="sm"
              variant="primary"
              className="flex-1"
              onClick={() => onDownload(shot.id)}
              disabled={downloading || !shot.has_proxy}
            >
              {downloading ? "导出中…" : "↓ 下载"}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
