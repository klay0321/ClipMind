"use client";

import type { AssetStatus } from "@/lib/types";

const STATUS_OPTIONS: { value: AssetStatus | ""; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "indexed", label: "已索引" },
  { value: "discovered", label: "已发现" },
  { value: "error", label: "分析失败" },
  { value: "source_missing", label: "源文件缺失" },
];

export function Toolbar({
  q,
  onQChange,
  status,
  onStatusChange,
  onRefresh,
  refreshing,
}: {
  q: string;
  onQChange: (v: string) => void;
  status: AssetStatus | "";
  onStatusChange: (v: AssetStatus | "") => void;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        type="search"
        value={q}
        onChange={(e) => onQChange(e.target.value)}
        placeholder="搜索文件名"
        aria-label="搜索文件名"
        className="w-48 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-brand focus:outline-none"
      />
      <select
        value={status}
        onChange={(e) => onStatusChange(e.target.value as AssetStatus | "")}
        aria-label="状态筛选"
        className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-brand focus:outline-none"
      >
        {STATUS_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={onRefresh}
        disabled={refreshing}
        className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 disabled:opacity-50 hover:bg-gray-50"
      >
        {refreshing ? "刷新中…" : "刷新"}
      </button>
    </div>
  );
}
