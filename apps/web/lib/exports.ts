// PR-06B 导出中心 / 收藏 / 动态集合的纯展示标签与文案（无副作用，便于单测）。

import type {
  ExportKind,
  ExportStatus,
  FavoriteTargetType,
  SavedSearchKind,
  ScriptExportFormat,
} from "./types";

export const EXPORT_KIND_LABELS: Record<ExportKind, string> = {
  clip: "单镜头片段",
  script: "脚本剪辑清单",
  bundle: "ZIP 打包",
};

export const EXPORT_KIND_TONE: Record<ExportKind, string> = {
  clip: "bg-blue-100 text-blue-700",
  script: "bg-violet-100 text-violet-700",
  bundle: "bg-amber-100 text-amber-800",
};

export const EXPORT_STATUS_LABELS: Record<ExportStatus, string> = {
  queued: "排队中",
  running: "生成中",
  completed: "已完成",
  failed: "失败",
};

export const EXPORT_STATUS_TONE: Record<ExportStatus, string> = {
  queued: "bg-blue-100 text-blue-700",
  running: "bg-blue-100 text-blue-700",
  completed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
};

export const SCRIPT_EXPORT_FORMAT_LABELS: Record<ScriptExportFormat, string> = {
  csv: "CSV 表格",
  xlsx: "Excel (xlsx)",
  json: "JSON",
  markdown: "Markdown",
  printable: "可打印清单",
};

export const FAVORITE_TYPE_LABELS: Record<FavoriteTargetType, string> = {
  asset: "素材",
  shot: "镜头",
  search_result: "搜索结果",
  script_match_result: "脚本匹配结果",
};

export const SAVED_SEARCH_KIND_LABELS: Record<SavedSearchKind, string> = {
  shot_search: "素材语义搜索",
  description_match: "画面描述匹配",
};

// 导出种类是否处于活动态（排队/生成中）。
export function isExportActive(status: ExportStatus): boolean {
  return status === "queued" || status === "running";
}
