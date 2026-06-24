"use client";

import Link from "next/link";

import { AssetStatusBadge, MediaRunStatusBadge } from "@/components/StatusBadge";
import { shotThumbnailUrl } from "@/lib/api";
import {
  formatBytes,
  formatCodec,
  formatDateTime,
  formatDuration,
  formatResolution,
} from "@/lib/format";
import type { Asset } from "@/lib/types";

function Cover({ asset, onPreview }: { asset: Asset; onPreview: (shotId: number) => void }) {
  if (asset.cover_shot_id == null) {
    return (
      <div className="flex h-12 w-20 shrink-0 items-center justify-center rounded bg-gray-100 text-[10px] text-gray-400">
        待生成封面
      </div>
    );
  }
  return (
    <button
      type="button"
      data-testid="asset-cover"
      onClick={() => onPreview(asset.cover_shot_id as number)}
      className="group relative h-12 w-20 shrink-0 overflow-hidden rounded bg-gray-900"
      title="预览"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={shotThumbnailUrl(asset.cover_shot_id)}
        alt={`${asset.filename} 封面`}
        className="h-full w-full object-cover opacity-90 group-hover:opacity-100"
        loading="lazy"
      />
      <span className="absolute inset-0 flex items-center justify-center">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-black/50 text-white">
          ▶
        </span>
      </span>
    </button>
  );
}

function AnalysisCell({ asset }: { asset: Asset }) {
  const analyzing =
    asset.status === "processing" ||
    asset.analysis_status === "queued" ||
    asset.analysis_status === "running";
  return (
    <div className="space-y-1">
      <div className="text-gray-700">
        {asset.shot_count > 0 ? `${asset.shot_count} 个镜头` : "未拆镜头"}
      </div>
      {asset.analysis_status ? (
        <MediaRunStatusBadge status={asset.analysis_status} />
      ) : null}
      {analyzing ? <div className="text-xs text-blue-600">处理中…</div> : null}
    </div>
  );
}

function AssetActions({
  asset,
  analyzing,
  rescanning,
  onAnalyze,
  onRescan,
  onPreview,
}: {
  asset: Asset;
  analyzing: boolean;
  rescanning: boolean;
  onAnalyze: (id: number, retry: boolean) => void;
  onRescan: (id: number) => void;
  onPreview: (shotId: number) => void;
}) {
  const isProcessing =
    asset.status === "processing" ||
    asset.analysis_status === "queued" ||
    asset.analysis_status === "running" ||
    analyzing;
  const hasShots = asset.shot_count > 0;
  const failed = asset.analysis_status === "failed";
  const disabledAnalyze = isProcessing || asset.status === "source_missing";

  let primaryLabel = "开始分析";
  if (isProcessing) primaryLabel = "分析中…";
  else if (failed) primaryLabel = "重试分析";
  else if (hasShots) primaryLabel = "继续分析";

  const btn =
    "rounded-md px-3 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50";

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={() => onAnalyze(asset.id, hasShots || failed)}
        disabled={disabledAnalyze}
        className={`${btn} bg-brand text-white hover:bg-brand-dark`}
      >
        ✂ {primaryLabel}
      </button>
      {asset.cover_shot_id != null ? (
        <button
          type="button"
          onClick={() => onPreview(asset.cover_shot_id as number)}
          className={`${btn} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`}
        >
          ▶ 预览
        </button>
      ) : null}
      {hasShots ? (
        <Link
          href={`/shots?asset_id=${asset.id}`}
          className={`${btn} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`}
        >
          查看镜头
        </Link>
      ) : null}
      <button
        type="button"
        onClick={() => onRescan(asset.id)}
        disabled={rescanning}
        className={`${btn} border border-gray-300 bg-white text-gray-600 hover:bg-gray-50`}
      >
        {rescanning ? "重扫中…" : "重新扫描"}
      </button>
    </div>
  );
}

export function AssetTable({
  assets,
  rescanningIds,
  analyzingIds,
  onRescan,
  onAnalyze,
  onPreview,
}: {
  assets: Asset[];
  rescanningIds: Set<number>;
  analyzingIds: Set<number>;
  onRescan: (id: number) => void;
  onAnalyze: (id: number, retry: boolean) => void;
  onPreview: (shotId: number) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-gray-100 text-xs uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-4 py-3 font-medium">封面</th>
            <th className="px-4 py-3 font-medium">文件名 / 相对路径</th>
            <th className="px-4 py-3 font-medium">产品</th>
            <th className="px-4 py-3 font-medium">大小</th>
            <th className="px-4 py-3 font-medium">时长</th>
            <th className="px-4 py-3 font-medium">分辨率</th>
            <th className="px-4 py-3 font-medium">编码</th>
            <th className="px-4 py-3 font-medium">状态</th>
            <th className="px-4 py-3 font-medium">镜头分析</th>
            <th className="px-4 py-3 font-medium">最近扫描</th>
            <th className="px-4 py-3 font-medium">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {assets.map((a) => (
            <tr key={a.id} className="align-top hover:bg-gray-50/60">
              <td className="px-4 py-3">
                <Cover asset={a} onPreview={onPreview} />
              </td>
              <td className="px-4 py-3">
                <div className="font-medium text-gray-900">{a.filename}</div>
                <div className="text-xs text-gray-400">{a.relative_path}</div>
                {a.status === "error" && a.error_message ? (
                  <div className="mt-1 text-xs text-red-600">原因：{a.error_message}</div>
                ) : null}
              </td>
              <td className="px-4 py-3 text-gray-400">未识别</td>
              <td className="px-4 py-3 text-gray-700">{formatBytes(a.file_size)}</td>
              <td className="px-4 py-3 text-gray-700">{formatDuration(a.duration)}</td>
              <td className="px-4 py-3 text-gray-700">
                {formatResolution(a.width, a.height, a.orientation)}
              </td>
              <td className="px-4 py-3 text-gray-700">
                {formatCodec(a.video_codec, a.audio_codec)}
              </td>
              <td className="px-4 py-3">
                <AssetStatusBadge status={a.status} />
              </td>
              <td className="px-4 py-3">
                <AnalysisCell asset={a} />
              </td>
              <td className="px-4 py-3 text-gray-500">{formatDateTime(a.last_seen_at)}</td>
              <td className="px-4 py-3">
                <AssetActions
                  asset={a}
                  analyzing={analyzingIds.has(a.id)}
                  rescanning={rescanningIds.has(a.id)}
                  onAnalyze={onAnalyze}
                  onRescan={onRescan}
                  onPreview={onPreview}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
