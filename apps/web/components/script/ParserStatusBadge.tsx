// 拆段解析状态徽章：诚实反映 parser_provider / parse_status；降级绝不显示成 MiMo 成功。
"use client";

import { parseStatusLabel } from "@/lib/script";
import type { ScriptParseStatus } from "@/lib/types";

export function ParserStatusBadge({
  status,
  provider,
  warnings,
}: {
  status: ScriptParseStatus;
  provider: string | null;
  warnings: string[] | null;
}) {
  const tone =
    status === "ok"
      ? "bg-emerald-50 text-emerald-700"
      : status === "degraded"
        ? "bg-amber-50 text-amber-700"
        : status === "failed"
          ? "bg-red-100 text-red-700"
          : "bg-gray-100 text-gray-600";
  const icon = status === "ok" ? "✓" : status === "degraded" ? "!" : status === "failed" ? "✕" : "•";
  return (
    <div className="space-y-1" data-testid="parser-status">
      <span
        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] ${tone}`}
        data-parse-status={status}
      >
        <span aria-hidden>{icon}</span>
        {parseStatusLabel(status)}
        {provider ? <span className="opacity-70">· {provider}</span> : null}
      </span>
      {status === "degraded" ? (
        <p className="text-[11px] text-amber-700" role="status" data-testid="parser-degraded-note">
          AI 脚本理解暂时不可用，已使用规则拆段。请人工检查段落和要求。
        </p>
      ) : null}
      {warnings && warnings.length ? (
        <ul className="flex flex-wrap gap-1" data-testid="parser-warnings">
          {warnings.map((w, i) => (
            <li key={`${w}-${i}`} className="rounded bg-gray-50 px-1.5 py-0.5 text-[10px] text-gray-500">
              {w}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
