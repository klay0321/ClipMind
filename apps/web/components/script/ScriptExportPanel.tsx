// 剪辑清单 CSV 导出：走真实 Gate B Export API（创建→轮询→下载）。前端绝不自拼 CSV。
// 刷新可恢复（localStorage 记最近 export id）；防重复点击；完成停轮询；失败可重试。
"use client";

import { useEffect, useState } from "react";

import { scriptCsvDownloadUrl } from "@/lib/api";
import { useCreateScriptCsvExport, useScriptExportStatus } from "@/lib/hooks";

const lsKey = (scriptId: number) => `clipmind-script-export-${scriptId}`;

export function ScriptExportPanel({ scriptId }: { scriptId: number }) {
  const [exportId, setExportId] = useState<number | null>(null);
  const create = useCreateScriptCsvExport(scriptId);
  const statusQ = useScriptExportStatus(scriptId, exportId);

  // 刷新后恢复最近一次导出记录
  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = window.localStorage.getItem(lsKey(scriptId));
    if (raw) {
      const n = Number(raw);
      if (Number.isFinite(n)) setExportId(n);
    }
  }, [scriptId]);

  const status = statusQ.data?.status;
  const inProgress =
    create.isPending || status === "queued" || status === "running";

  const onExport = () => {
    if (inProgress) return;
    create.mutate(undefined, {
      onSuccess: (exp) => {
        setExportId(exp.id);
        if (typeof window !== "undefined")
          window.localStorage.setItem(lsKey(scriptId), String(exp.id));
      },
    });
  };

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="export-panel">
      <button
        type="button"
        data-testid="export-csv"
        onClick={onExport}
        disabled={inProgress}
        className="rounded-md border border-brand px-3 py-1.5 text-xs font-medium text-brand hover:bg-brand-light disabled:opacity-50"
      >
        {create.isPending ? "创建导出…" : "导出剪辑清单 CSV"}
      </button>

      {exportId != null && status ? (
        <span className="text-[11px] text-gray-500" data-testid="export-status" data-status={status}>
          {status === "queued" || status === "running" ? "生成中…" : null}
          {status === "completed" ? (
            <a
              href={scriptCsvDownloadUrl(scriptId, exportId)}
              data-testid="export-download"
              download
              className="rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-emerald-700 hover:bg-emerald-100"
            >
              ↓ 下载 CSV{statusQ.data?.row_count != null ? `（${statusQ.data.row_count} 行）` : ""}
            </a>
          ) : null}
          {status === "failed" ? (
            <span className="text-red-600">
              导出失败{statusQ.data?.error_message ? `：${statusQ.data.error_message}` : ""}
              <button type="button" onClick={onExport} className="ml-1 underline">
                重试
              </button>
            </span>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}
