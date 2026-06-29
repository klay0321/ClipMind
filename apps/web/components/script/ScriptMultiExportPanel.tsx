// 多格式脚本导出：csv / xlsx / json / markdown / printable。
// 复用 create→轮询→下载→重试 + localStorage 刷新可恢复（按 scriptId+format 分别记录）。
// 走真实多格式 Export API（POST /scripts/{id}/exports?format=...），前端绝不自拼文件。
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { scriptExportDownloadUrl } from "@/lib/api";
import { SCRIPT_EXPORT_FORMAT_LABELS } from "@/lib/exports";
import { useCreateScriptExport, useScriptExportStatus } from "@/lib/hooks";
import { SCRIPT_EXPORT_FORMATS, type ScriptExportFormat } from "@/lib/types";

const lsKey = (scriptId: number, format: ScriptExportFormat) =>
  `clipmind-script-export-${scriptId}-${format}`;

export function ScriptMultiExportPanel({ scriptId }: { scriptId: number }) {
  const [format, setFormat] = useState<ScriptExportFormat>("csv");
  // 每种格式各自记录最近一次导出 id（刷新可恢复）
  const [exportIds, setExportIds] = useState<Partial<Record<ScriptExportFormat, number>>>({});
  const create = useCreateScriptExport(scriptId);
  const exportId = exportIds[format] ?? null;
  const statusQ = useScriptExportStatus(scriptId, exportId);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const next: Partial<Record<ScriptExportFormat, number>> = {};
    for (const f of SCRIPT_EXPORT_FORMATS) {
      const raw = window.localStorage.getItem(lsKey(scriptId, f));
      if (raw) {
        const n = Number(raw);
        if (Number.isFinite(n)) next[f] = n;
      }
    }
    setExportIds(next);
  }, [scriptId]);

  const status = statusQ.data?.status;
  const inProgress = create.isPending || status === "queued" || status === "running";

  const onExport = (f: ScriptExportFormat) => {
    setFormat(f);
    if (create.isPending) return;
    create.mutate(f, {
      onSuccess: (exp) => {
        setExportIds((prev) => ({ ...prev, [f]: exp.id }));
        if (typeof window !== "undefined")
          window.localStorage.setItem(lsKey(scriptId, f), String(exp.id));
      },
    });
  };

  return (
    <div className="space-y-2 rounded-lg border border-gray-200 bg-white p-3" data-testid="multi-export-panel">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-gray-700">多格式导出剪辑清单</span>
        <Link href="/exports" data-testid="multi-export-center-link" className="text-[11px] text-brand hover:underline">
          前往导出中心 →
        </Link>
      </div>
      <p className="text-[11px] text-gray-400">选择一种格式生成可下载文件；导出记录会同步出现在导出中心。</p>

      <div className="flex flex-wrap gap-1.5" role="group" aria-label="导出格式">
        {SCRIPT_EXPORT_FORMATS.map((f) => (
          <button
            key={f}
            type="button"
            data-testid={`export-format-${f}`}
            onClick={() => onExport(f)}
            disabled={inProgress}
            aria-pressed={format === f}
            className={`rounded-md border px-2.5 py-1 text-[11px] font-medium disabled:opacity-50 ${
              format === f
                ? "border-brand bg-brand-light text-brand-dark"
                : "border-gray-300 text-gray-600 hover:bg-gray-50"
            }`}
          >
            {SCRIPT_EXPORT_FORMAT_LABELS[f]}
          </button>
        ))}
      </div>

      {exportId != null && status ? (
        <div
          className="flex flex-wrap items-center gap-2 text-[11px]"
          data-testid="multi-export-status"
          data-status={status}
          role="status"
        >
          <span className="text-gray-500">
            {SCRIPT_EXPORT_FORMAT_LABELS[format]}：
          </span>
          {status === "queued" || status === "running" ? (
            <span className="text-blue-600">生成中…</span>
          ) : null}
          {status === "completed" ? (
            <a
              href={scriptExportDownloadUrl(scriptId, exportId)}
              data-testid="multi-export-download"
              download
              className="rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-emerald-700 hover:bg-emerald-100"
            >
              ↓ 下载{statusQ.data?.row_count != null ? `（${statusQ.data.row_count} 行）` : ""}
            </a>
          ) : null}
          {status === "failed" ? (
            <span className="text-red-600">
              导出失败{statusQ.data?.error_message ? `：${statusQ.data.error_message}` : ""}
              <button
                type="button"
                data-testid="multi-export-retry"
                onClick={() => onExport(format)}
                className="ml-1 underline"
              >
                重试
              </button>
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
