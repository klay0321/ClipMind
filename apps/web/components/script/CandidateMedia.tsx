// 候选镜头缩略图：图片优先、lazy 加载，绝不在卡片层自动加载视频；点播放图标按需预览。
"use client";

import { formatDuration } from "@/lib/format";
import type { ScriptCandidate } from "@/lib/types";

export function CandidateMedia({
  candidate,
  onPreview,
  className = "",
}: {
  candidate: ScriptCandidate;
  onPreview?: (shotId: number) => void;
  className?: string;
}) {
  const img = candidate.thumbnail_url ?? candidate.keyframe_url;
  const canPreview = onPreview != null && candidate.preview_url != null;
  return (
    <div className={`relative overflow-hidden rounded bg-gray-100 ${className}`}>
      {img ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={img}
          alt={`候选镜头 #${candidate.shot_id} 关键帧`}
          className="h-full w-full object-cover"
          loading="lazy"
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-[10px] text-gray-400">
          无缩略图
        </div>
      )}
      {canPreview ? (
        <button
          type="button"
          aria-label={`预览候选镜头 #${candidate.shot_id}`}
          data-testid="candidate-preview-btn"
          onClick={(e) => {
            e.stopPropagation();
            onPreview!(candidate.shot_id);
          }}
          className="absolute left-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-black/55 text-[11px] text-white hover:bg-black/75"
        >
          ▶
        </button>
      ) : null}
      {candidate.start_time != null ? (
        <span className="absolute bottom-1 right-1 rounded bg-black/60 px-1 py-0.5 text-[10px] text-white">
          {formatDuration(candidate.start_time)}
        </span>
      ) : null}
    </div>
  );
}
