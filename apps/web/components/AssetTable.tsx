"use client";

import { AssetStatusBadge } from "@/components/StatusBadge";
import {
  formatBytes,
  formatCodec,
  formatDateTime,
  formatDuration,
  formatResolution,
} from "@/lib/format";
import type { Asset } from "@/lib/types";

function CoverPlaceholder() {
  // PR-01 无关键帧，使用明确的“待生成封面”占位，不伪造视频截图
  return (
    <div className="flex h-12 w-20 shrink-0 items-center justify-center rounded bg-gray-100 text-[10px] text-gray-400">
      待生成封面
    </div>
  );
}

export function AssetTable({
  assets,
  rescanningIds,
  onRescan,
}: {
  assets: Asset[];
  rescanningIds: Set<number>;
  onRescan: (id: number) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-gray-100 text-xs uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-4 py-3 font-medium">封面</th>
            <th className="px-4 py-3 font-medium">文件名 / 相对路径</th>
            <th className="px-4 py-3 font-medium">大小</th>
            <th className="px-4 py-3 font-medium">时长</th>
            <th className="px-4 py-3 font-medium">分辨率</th>
            <th className="px-4 py-3 font-medium">帧率</th>
            <th className="px-4 py-3 font-medium">编码(视频/音频)</th>
            <th className="px-4 py-3 font-medium">状态</th>
            <th className="px-4 py-3 font-medium">最近扫描</th>
            <th className="px-4 py-3 font-medium">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {assets.map((a) => {
            const rescanning = rescanningIds.has(a.id);
            return (
              <tr key={a.id} className="align-top hover:bg-gray-50/60">
                <td className="px-4 py-3">
                  <CoverPlaceholder />
                </td>
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900">{a.filename}</div>
                  <div className="text-xs text-gray-400">{a.relative_path}</div>
                  {a.status === "error" && a.error_message ? (
                    <div className="mt-1 text-xs text-red-600">原因：{a.error_message}</div>
                  ) : null}
                </td>
                <td className="px-4 py-3 text-gray-700">{formatBytes(a.file_size)}</td>
                <td className="px-4 py-3 text-gray-700">{formatDuration(a.duration)}</td>
                <td className="px-4 py-3 text-gray-700">
                  {formatResolution(a.width, a.height, a.orientation)}
                </td>
                <td className="px-4 py-3 text-gray-700">
                  {a.fps != null ? `${Math.round(a.fps)} fps` : "—"}
                </td>
                <td className="px-4 py-3 text-gray-700">
                  {formatCodec(a.video_codec, a.audio_codec)}
                </td>
                <td className="px-4 py-3">
                  <AssetStatusBadge status={a.status} />
                </td>
                <td className="px-4 py-3 text-gray-500">{formatDateTime(a.last_seen_at)}</td>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    onClick={() => onRescan(a.id)}
                    disabled={rescanning}
                    className="rounded-md border border-gray-300 bg-white px-3 py-1 text-xs font-medium text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-50"
                  >
                    {rescanning ? "重扫中…" : "重新扫描"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
