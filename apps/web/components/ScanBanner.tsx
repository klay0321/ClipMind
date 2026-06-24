"use client";

import type { ScanStatusResponse } from "@/lib/types";

export function ScanBanner({
  scanStatus,
  pending,
}: {
  scanStatus: ScanStatusResponse | undefined;
  pending: boolean;
}) {
  const status = scanStatus?.scan_status;
  const run = scanStatus?.latest_run;

  if (pending && !status) {
    return (
      <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-700">
        正在发起扫描…
      </div>
    );
  }

  if (status === "scanning" || status === "queued") {
    return (
      <div
        data-testid="scan-banner"
        className="flex items-center gap-3 rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-700"
      >
        <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-blue-400 border-t-transparent" />
        <span>
          扫描{status === "queued" ? "排队中" : "进行中"}…
          {run
            ? ` 已发现 ${run.files_discovered}，新增 ${run.files_new}，修改 ${run.files_modified}，失败 ${run.files_errored}`
            : ""}
        </span>
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
        上次扫描失败{run?.error_message ? `：${run.error_message}` : ""}
      </div>
    );
  }

  if (status === "completed" && run) {
    return (
      <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-700">
        上次扫描完成 · 发现 {run.files_discovered}，新增 {run.files_new}，修改{" "}
        {run.files_modified}，缺失 {run.files_missing}，失败 {run.files_errored}
      </div>
    );
  }

  return null;
}
