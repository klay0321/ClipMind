// 工作台顶栏：返回 + 项目名 + 解析状态 + 匹配状态汇总 + 操作（全脚本匹配 / 导出剪辑清单 / 导出中心）。
"use client";

import Link from "next/link";

import { Button } from "@/components/ui/Button";
import { matchStatusLabel } from "@/lib/script";
import type { ScriptMatchStatusResponse, ScriptProjectDetail } from "@/lib/types";

import { ParserStatusBadge } from "./ParserStatusBadge";

export function ScriptTopBar({
  project,
  status,
  onMatchAll,
  matchingAll,
  canMatch,
  onToggleExport,
  exportOpen = false,
}: {
  project: ScriptProjectDetail;
  status: ScriptMatchStatusResponse | undefined;
  onMatchAll: () => void;
  matchingAll: boolean;
  canMatch: boolean;
  onToggleExport?: () => void;
  exportOpen?: boolean;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href="/script"
          data-testid="script-back"
          className="text-sm text-gray-500 hover:text-brand"
        >
          ← 返回
        </Link>
        <h1 className="truncate text-base font-semibold text-gray-900" data-testid="script-title">
          {project.name}
        </h1>
        <ParserStatusBadge
          status={project.parse_status}
          provider={project.parser_provider}
          warnings={project.parser_warnings}
        />
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            data-testid="match-all"
            onClick={onMatchAll}
            disabled={!canMatch || matchingAll}
            loading={matchingAll}
            title={canMatch ? "复用混合检索为每段生成候选" : "请先拆段"}
          >
            {matchingAll ? "匹配中…" : "▶ 全脚本匹配"}
          </Button>
          {onToggleExport ? (
            <Button
              variant="secondary"
              size="sm"
              data-testid="toggle-export"
              aria-expanded={exportOpen}
              onClick={onToggleExport}
            >
              导出剪辑清单 ▾
            </Button>
          ) : null}
          <Link
            href="/exports"
            data-testid="open-export-center"
            className="text-xs text-gray-500 hover:text-brand"
          >
            导出中心 →
          </Link>
        </div>
      </div>

      {status ? (
        <div
          className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-500"
          data-testid="match-status-summary"
        >
          <span>段落 <strong className="text-gray-700">{status.total_segments}</strong></span>
          <span className="text-emerald-700">{matchStatusLabel("matched")} {status.matched_segments}</span>
          <span className="text-red-700">{matchStatusLabel("gap")} {status.gap_segments}</span>
          <span>已选 {status.selected_segments}</span>
          <span className="text-brand-dark">已锁定 {status.locked_segments}</span>
          <span>未匹配 {status.pending_segments}</span>
        </div>
      ) : null}
    </div>
  );
}
