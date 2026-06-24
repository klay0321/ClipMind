"use client";

import { useState } from "react";

import { ShotStatusBadge } from "@/components/StatusBadge";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { exportDownloadUrl, shotKeyframeUrl, shotPreviewUrl } from "@/lib/api";
import { formatCodec, formatDuration, formatResolution } from "@/lib/format";
import { useExportMutation, useExportStatus, useShot } from "@/lib/hooks";

function timecode(s: number): string {
  return formatDuration(s);
}

export function ShotDetail({ shotId }: { shotId: number | null }) {
  const [exportId, setExportId] = useState<number | null>(null);
  const shotQ = useShot(shotId);
  const exportMut = useExportMutation();
  const exportStatusQ = useExportStatus(exportId);

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
  const exporting = exportMut.isPending || (exp != null && (exp.status === "queued" || exp.status === "running"));
  const exportFailed = exp?.status === "failed";

  const handleExport = () => {
    exportMut.mutate(
      { shotId: s.id },
      { onSuccess: (d) => setExportId(d.export_id) },
    );
  };

  return (
    <div className="space-y-3 p-4" data-testid="shot-detail">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">
          镜头 #{s.sequence_no}
        </h3>
        <ShotStatusBadge status={s.status} />
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

      {/* 主关键帧 */}
      {s.has_keyframe ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={shotKeyframeUrl(s.id)}
          alt={`镜头 ${s.sequence_no} 关键帧`}
          className="w-full rounded border border-gray-100"
        />
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
        <dd className="text-gray-700">
          {formatResolution(s.asset_width, s.asset_height, null)}
        </dd>
        <dt className="text-gray-400">来源编码</dt>
        <dd className="text-gray-700">
          {formatCodec(s.asset_video_codec, s.asset_audio_codec)}
        </dd>
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

      <p className="rounded bg-gray-50 p-2 text-xs text-gray-400">
        AI 画面描述、标签与匹配将在后续版本（PR-03 起）提供。
      </p>
    </div>
  );
}
