"use client";

import type { ProjectStats } from "@/lib/types";

const FIELDS: { key: keyof ProjectStats; label: string }[] = [
  { key: "asset_count", label: "素材" },
  { key: "visible_shot_count", label: "可见镜头" },
  { key: "explicit_shot_count", label: "显式镜头" },
  { key: "collection_count", label: "集合" },
  { key: "collection_shot_count", label: "集合镜头" },
  { key: "product_count", label: "产品" },
  { key: "script_count", label: "脚本" },
  { key: "active_script_count", label: "活跃脚本" },
  { key: "locked_segment_count", label: "锁定段" },
  { key: "gap_segment_count", label: "缺口段" },
  { key: "completed_script_export_count", label: "已完成导出" },
  { key: "risk_shot_count", label: "风险镜头" },
  { key: "searchable_shot_count", label: "可搜索镜头" },
];

export function ProjectStatsGrid({ stats }: { stats: ProjectStats }) {
  return (
    <div
      data-testid="project-stats"
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
    >
      {FIELDS.map((f) => (
        <div
          key={f.key as string}
          data-testid={`stat-${f.key}`}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2"
        >
          <div className="text-lg font-semibold text-gray-800">{stats[f.key] as number}</div>
          <div className="text-xs text-gray-500">{f.label}</div>
        </div>
      ))}
    </div>
  );
}
