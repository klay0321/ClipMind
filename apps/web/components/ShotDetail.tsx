"use client";

import { useEffect, useState } from "react";

import { ProductLinkPanel } from "@/components/product-media/ProductLinkPanel";
import { ReviewPanel } from "@/components/ReviewPanel";
import { ShotStatusBadge } from "@/components/StatusBadge";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import {
  exportDownloadUrl,
  shotKeyframeAtUrl,
  shotKeyframeUrl,
  shotPreviewUrl,
} from "@/lib/api";
import { formatCodec, formatDateTime, formatDuration, formatResolution } from "@/lib/format";
import {
  useExportMutation,
  useExportStatus,
  useShot,
  useShotUsageSummary,
} from "@/lib/hooks";

function timecode(s: number): string {
  return formatDuration(s);
}

export function ShotDetail({ shotId }: { shotId: number | null }) {
  const [exportId, setExportId] = useState<number | null>(null);
  // 关键帧条选中帧：null = 主关键帧；数字 = 条上第 N 帧
  const [activeFrame, setActiveFrame] = useState<number | null>(null);
  const shotQ = useShot(shotId);
  const exportMut = useExportMutation();
  const exportStatusQ = useExportStatus(exportId);

  // 切换镜头时重置选中帧
  useEffect(() => {
    setActiveFrame(null);
  }, [shotId]);

  if (shotId == null) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-gray-400">
        选择左侧镜头查看详情
      </div>
    );
  }
  if (shotQ.isLoading) return <Loading />;
  if (shotQ.isError || !shotQ.data) {
    return (
      <ErrorState
        message={(shotQ.error as Error)?.message ?? "加载镜头详情失败"}
        onRetry={() => void shotQ.refetch()}
      />
    );
  }

  const s = shotQ.data;
  const exp = exportStatusQ.data;
  const exporting =
    exportMut.isPending || (exp != null && (exp.status === "queued" || exp.status === "running"));
  const exportFailed = exp?.status === "failed";

  const handleExport = () => {
    exportMut.mutate({ shotId: s.id }, { onSuccess: (d) => setExportId(d.export_id) });
  };

  return (
    <div className="space-y-3 p-4" data-testid="shot-detail">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">镜头 #{s.sequence_no}</h3>
        <div className="flex items-center gap-1.5">
          {s.retired ? (
            <span
              className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500"
              title={`来自历史分析代次（第 ${s.generation ?? "?"} 代）；默认列表与搜索只显示当前代次`}
              data-testid="shot-retired-badge"
            >
              历史代次
            </span>
          ) : null}
          <ShotStatusBadge status={s.status} />
        </div>
      </div>

      {/* 代理视频播放器（支持 Range 拖动进度条） */}
      {s.has_proxy ? (
        <video
          data-testid="shot-video"
          className="w-full rounded bg-black"
          src={shotPreviewUrl(s.id)}
          controls
          preload="metadata"
        />
      ) : (
        <div className="flex h-40 items-center justify-center rounded bg-gray-100 text-xs text-gray-400">
          代理视频不可用
        </div>
      )}

      {/* 关键帧（主帧 / 关键帧条选中帧） */}
      {s.has_keyframe ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={activeFrame == null ? shotKeyframeUrl(s.id) : shotKeyframeAtUrl(s.id, activeFrame)}
          alt={`镜头 ${s.sequence_no} 关键帧`}
          className="w-full rounded border border-gray-100"
        />
      ) : null}

      {/* 关键帧条：沿镜头均匀采样的多帧（点击放大到上方） */}
      {s.keyframe_count > 0 ? (
        <div className="space-y-1" data-testid="keyframe-strip">
          <div className="text-[11px] text-gray-400">
            关键帧条（{s.keyframe_count} 帧 · 沿镜头采样）
          </div>
          <div className="flex gap-1 overflow-x-auto pb-1">
            <button
              type="button"
              onClick={() => setActiveFrame(null)}
              className={`shrink-0 overflow-hidden rounded border ${
                activeFrame == null ? "border-brand ring-1 ring-brand" : "border-gray-200"
              }`}
              title="主关键帧"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={shotKeyframeUrl(s.id)} alt="主关键帧" className="h-12 w-20 object-cover" />
            </button>
            {Array.from({ length: s.keyframe_count }).map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setActiveFrame(i)}
                className={`shrink-0 overflow-hidden rounded border ${
                  activeFrame === i ? "border-brand ring-1 ring-brand" : "border-gray-200"
                }`}
                title={`第 ${i + 1} 帧`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={shotKeyframeAtUrl(s.id, i)}
                  alt={`关键帧 ${i + 1}`}
                  className="h-12 w-20 object-cover"
                  loading="lazy"
                />
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <dt className="text-gray-400">来源视频</dt>
        <dd className="truncate text-gray-700" title={s.asset_filename}>
          {s.asset_filename}
        </dd>
        <dt className="text-gray-400">时间码</dt>
        <dd className="text-gray-700">
          {timecode(s.start_time)} – {timecode(s.end_time)}
        </dd>
        <dt className="text-gray-400">时长</dt>
        <dd className="text-gray-700">{s.duration.toFixed(2)}s</dd>
        <dt className="text-gray-400">来源分辨率</dt>
        <dd className="text-gray-700">{formatResolution(s.asset_width, s.asset_height, null)}</dd>
        <dt className="text-gray-400">来源编码</dt>
        <dd className="text-gray-700">{formatCodec(s.asset_video_codec, s.asset_audio_codec)}</dd>
        <dt className="text-gray-400">检测器</dt>
        <dd className="text-gray-700">{s.detector_type}</dd>
      </dl>

      <div className="space-y-1">
        <button
          type="button"
          data-testid="shot-export-btn"
          onClick={handleExport}
          disabled={exporting}
          className="w-full rounded-md bg-brand px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-brand-dark"
        >
          {exporting ? "导出中…" : "导出片段"}
        </button>
        {exp?.status === "completed" && exp.has_file ? (
          <a
            data-testid="shot-download-link"
            href={exportDownloadUrl(exp.id)}
            className="block rounded-md border border-brand px-3 py-2 text-center text-sm font-medium text-brand hover:bg-brand-light"
          >
            下载片段
          </a>
        ) : null}
        {exportFailed ? (
          <p className="text-xs text-red-600">导出失败：{exp?.error_message ?? "未知错误"}</p>
        ) : null}
      </div>

      <ProductLinkPanel targetType="shot" targetId={s.id} />
      <ShotUsagePanel shotId={s.id} />

      <ReviewPanel shotId={s.id} />
    </div>
  );
}

/** PR-B：镜头正式使用情况（只读派生值；仅 confirmed 计入使用次数）。 */
function ShotUsagePanel({ shotId }: { shotId: number }) {
  const summary = useShotUsageSummary(shotId);
  const data = summary.data;
  if (summary.isLoading || !data) return null;
  return (
    <div className="rounded border border-gray-100 bg-gray-50 p-2 text-xs" data-testid="shot-usage-panel">
      <div className="flex items-center justify-between">
        <span className="font-medium text-gray-700">成片使用情况</span>
        <span
          className={
            data.confirmed_usage_count > 0 ? "font-semibold text-emerald-700" : "text-gray-500"
          }
          data-testid="shot-usage-count"
        >
          使用 {data.confirmed_usage_count} 次
        </span>
      </div>
      {data.proposed_count > 0 ? (
        <p className="mt-1 text-amber-700">
          另有 {data.proposed_count} 条候选引用待确认（候选不计入使用次数）
        </p>
      ) : null}
      {data.last_used_at ? (
        <p className="mt-1 text-gray-500">最近使用：{formatDateTime(data.last_used_at)}</p>
      ) : null}
      {data.final_videos.length > 0 ? (
        <ul className="mt-1 space-y-0.5">
          {data.final_videos.map((fv) => (
            <li key={fv.final_video_id} className="truncate">
              <a
                href={`/final-videos/${fv.final_video_id}`}
                className="text-brand hover:underline"
                data-testid={`shot-usage-fv-${fv.final_video_id}`}
              >
                用于成片：{fv.title}
              </a>
            </li>
          ))}
        </ul>
      ) : data.confirmed_usage_count === 0 && data.proposed_count === 0 ? (
        <p className="mt-1 text-gray-400">尚未被任何成片引用</p>
      ) : null}
    </div>
  );
}
