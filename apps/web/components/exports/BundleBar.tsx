// ZIP 打包多选工具条：展示已选数量 + 总时长，创建 ZIP → 轮询状态 → 完成下载 + 导出中心入口。
// 仅在「当前页选择」上操作，绝不一次性加载所有镜头；后端限制 1..50 个、总时长 ≤ 1800s。
"use client";

import { useState } from "react";
import Link from "next/link";

import { ApiError, bundleDownloadUrl } from "@/lib/api";
import { useBundleStatus, useCreateBundle } from "@/lib/hooks";

const MAX_SHOTS = 50;
const MAX_DURATION = 1800;

export function BundleBar({
  selected,
  totalDuration,
  projectId,
  onClear,
}: {
  // 已选镜头 id（当前页选择）
  selected: number[];
  // 已选镜头总时长（秒；由调用方在当前页累加，不另发请求）
  totalDuration: number;
  projectId?: number;
  onClear: () => void;
}) {
  const create = useCreateBundle();
  const [bundleId, setBundleId] = useState<number | null>(null);
  const statusQ = useBundleStatus(bundleId);
  const status = statusQ.data?.status;

  const count = selected.length;
  if (count === 0 && bundleId == null) return null;

  const tooMany = count > MAX_SHOTS;
  const tooLong = totalDuration > MAX_DURATION;
  const inProgress = create.isPending || status === "queued" || status === "running";
  const canCreate = count >= 1 && !tooMany && !tooLong && !inProgress;

  const onCreate = () => {
    if (!canCreate) return;
    create.mutate(
      { shot_ids: selected, project_id: projectId },
      { onSuccess: (res) => setBundleId(res.export_id) },
    );
  };

  const errMsg =
    create.error instanceof ApiError
      ? create.error.message
      : create.error instanceof Error
        ? create.error.message
        : null;

  return (
    <div
      data-testid="bundle-bar"
      role="status"
      className="flex flex-wrap items-center gap-3 rounded-lg border border-brand/40 bg-brand-light/40 px-3 py-2 text-sm"
    >
      <span data-testid="bundle-count" className="font-medium text-brand-dark">
        已选 {count} 个镜头
      </span>
      <span className="text-xs text-gray-600">总时长 {totalDuration.toFixed(1)}s</span>
      {tooMany ? (
        <span className="text-xs text-red-600">最多 {MAX_SHOTS} 个</span>
      ) : null}
      {tooLong ? (
        <span className="text-xs text-red-600">总时长超过 {MAX_DURATION}s 上限</span>
      ) : null}

      <div className="ml-auto flex flex-wrap items-center gap-2">
        {count > 0 ? (
          <button
            type="button"
            onClick={onClear}
            className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50"
          >
            清空选择
          </button>
        ) : null}
        <button
          type="button"
          data-testid="bundle-create"
          onClick={onCreate}
          disabled={!canCreate}
          className="rounded bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {inProgress ? "打包中…" : "创建 ZIP"}
        </button>

        {status === "completed" && statusQ.data?.has_file ? (
          <a
            href={bundleDownloadUrl(bundleId as number)}
            download
            data-testid="bundle-download"
            className="rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-xs text-emerald-700 hover:bg-emerald-100"
          >
            ↓ 下载 ZIP
          </a>
        ) : null}
        {status === "failed" ? (
          <span className="text-xs text-red-600" data-testid="bundle-failed">
            打包失败{statusQ.data?.error_message ? `：${statusQ.data.error_message}` : ""}
          </span>
        ) : null}
        {bundleId != null ? (
          <Link href="/exports" data-testid="bundle-export-center" className="text-xs text-brand hover:underline">
            导出中心 →
          </Link>
        ) : null}
      </div>

      {errMsg ? (
        <div role="alert" className="w-full text-xs text-red-600">
          {errMsg}
        </div>
      ) : null}
    </div>
  );
}
