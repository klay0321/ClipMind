// 左栏：脚本原文（只读展示）+ 拆段控制。拆段由后端按配置解析器（auto→mimo/规则）执行；
// 存在锁定段时重拆需 force（会丢失锁定，显式确认）。
"use client";

import { useState } from "react";

import { ApiError } from "@/lib/api";
import type { ScriptProjectDetail } from "@/lib/types";

export function ScriptInputPanel({
  project,
  hasLocked,
  onParse,
  parsing,
  parseError,
}: {
  project: ScriptProjectDetail;
  hasLocked: boolean;
  onParse: (opts: { parser?: string; force?: boolean }) => void;
  parsing: boolean;
  parseError: unknown;
}) {
  const [parser, setParser] = useState<string>("");
  const [force, setForce] = useState(false);
  const parsed = project.segments.length > 0;

  const errMsg =
    parseError instanceof ApiError
      ? parseError.message
      : (parseError as Error | undefined)?.message ?? null;

  return (
    <section className="space-y-3 rounded-lg border border-gray-200 bg-white p-3" aria-labelledby="raw-h">
      <div className="flex items-center justify-between">
        <h2 id="raw-h" className="text-sm font-semibold text-gray-800">
          脚本或分镜
        </h2>
        <span className="text-[11px] text-gray-400">{project.raw_script.length} 字</span>
      </div>
      <pre
        data-testid="script-raw-text"
        className="max-h-72 overflow-auto whitespace-pre-wrap rounded border border-gray-100 bg-gray-50 p-2 text-xs leading-relaxed text-gray-700"
      >
        {project.raw_script}
      </pre>

      <div className="space-y-2 border-t border-gray-100 pt-2">
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-gray-500">拆段解析器</span>
          <select
            data-testid="parse-parser"
            value={parser}
            onChange={(e) => setParser(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1 text-xs focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          >
            <option value="">自动（按服务端配置）</option>
            <option value="mimo">MiMo（AI 拆段）</option>
            <option value="rulebased">规则拆段</option>
            <option value="fake">Fake（测试）</option>
          </select>
        </label>

        {parsed && hasLocked ? (
          <label className="flex items-center gap-1.5 text-[11px] text-amber-700">
            <input
              type="checkbox"
              data-testid="parse-force"
              checked={force}
              onChange={(e) => setForce(e.target.checked)}
            />
            强制重新拆段（将丢失已锁定段落）
          </label>
        ) : null}

        <button
          type="button"
          data-testid="parse-btn"
          onClick={() => onParse({ parser: parser || undefined, force })}
          disabled={parsing || (parsed && hasLocked && !force)}
          className="w-full rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {parsing ? "拆段中…" : parsed ? "重新拆段" : "🧩 AI 拆段"}
        </button>
        {errMsg ? (
          <p className="text-[11px] text-red-600" role="alert">
            拆段失败：{errMsg}
          </p>
        ) : null}
      </div>
    </section>
  );
}
