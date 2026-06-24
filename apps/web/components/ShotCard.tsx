"use client";

import { ShotStatusBadge } from "@/components/StatusBadge";
import { shotThumbnailUrl } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import type { Shot } from "@/lib/types";

export function ShotCard({
  shot,
  selected,
  onSelect,
}: {
  shot: Shot;
  selected: boolean;
  onSelect: (id: number) => void;
}) {
  return (
    <button
      type="button"
      data-testid="shot-card"
      onClick={() => onSelect(shot.id)}
      className={`flex flex-col overflow-hidden rounded-lg border text-left transition ${
        selected ? "border-brand ring-1 ring-brand" : "border-gray-200 hover:border-gray-300"
      }`}
    >
      <div className="relative aspect-video w-full bg-gray-100">
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
      </div>
      <div className="space-y-1 p-2">
        <div className="text-xs text-gray-700">
          {formatDuration(shot.start_time)} – {formatDuration(shot.end_time)}
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-gray-400">{shot.duration.toFixed(1)}s</span>
          <ShotStatusBadge status={shot.status} />
        </div>
      </div>
    </button>
  );
}
