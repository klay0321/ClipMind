"use client";

import { useState } from "react";

import { cn } from "@/lib/cn";
import { useAssetTrace } from "@/lib/hooks";
import type { TraceStageStatus } from "@/lib/types";

// OBS：单素材六环节链路诊断（服务端权威判定，非前端字段推断）。
// 折叠加载：展开时才请求，避免抽屉打开即多打一个诊断查询。

const STATUS_STYLE: Record<TraceStageStatus, { dot: string; label: string; text: string }> = {
  ok: { dot: "bg-emerald-500", label: "正常", text: "text-emerald-700" },
  pending: { dot: "bg-sky-500", label: "处理中", text: "text-sky-700" },
  lagging: { dot: "bg-amber-500", label: "滞后", text: "text-amber-700" },
  failed: { dot: "bg-red-500", label: "失败", text: "text-red-700" },
  excluded: { dot: "bg-gray-400", label: "按规则排除", text: "text-gray-600" },
  not_applicable: { dot: "bg-gray-300", label: "不适用", text: "text-gray-400" },
};

export function AssetTracePanel({ assetId }: { assetId: number }) {
  const [open, setOpen] = useState(false);
  const trace = useAssetTrace(assetId, open);

  return (
    <section className="rounded border border-gray-200 bg-white p-3" data-testid="asset-trace-panel">
      <button
        type="button"
        className="flex w-full items-center justify-between text-left"
        onClick={() => setOpen((v) => !v)}
        data-testid="asset-trace-toggle"
      >
        <span className="text-sm font-medium text-gray-700">处理链路诊断</span>
        <span className="text-xs text-gray-400">{open ? "收起" : "展开（为什么搜不到？）"}</span>
      </button>

      {open ? (
        trace.isLoading ? (
          <p className="mt-2 text-xs text-gray-400">诊断中…</p>
        ) : trace.isError ? (
          <p className="mt-2 text-xs text-red-600">诊断失败，请重试</p>
        ) : trace.data ? (
          <ol className="mt-3 space-y-2" data-testid="asset-trace-stages">
            {trace.data.stages.map((s) => {
              const st = STATUS_STYLE[s.status] ?? STATUS_STYLE.not_applicable;
              return (
                <li
                  key={s.stage}
                  className="flex items-start gap-2"
                  data-testid={`trace-stage-${s.stage}`}
                >
                  <span className={cn("mt-1 h-2 w-2 shrink-0 rounded-full", st.dot)} />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="font-medium text-gray-800">{s.title}</span>
                      <span
                        className={cn("rounded bg-gray-50 px-1 py-0.5 text-[10px]", st.text)}
                        data-testid={`trace-status-${s.stage}`}
                      >
                        {st.label}
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs text-gray-500">{s.hint}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        ) : null
      ) : null}
    </section>
  );
}
