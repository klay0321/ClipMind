import type {
  AssetStatus,
  FinalVideoStatus,
  MediaRunStatus,
  ScanStatus,
  ShotStatus,
  UsageEvidenceMethod,
  UsageStatus,
} from "@/lib/types";

const ASSET_STATUS: Record<AssetStatus, { label: string; cls: string }> = {
  discovered: { label: "已发现", cls: "bg-gray-100 text-gray-700" },
  indexed: { label: "已索引", cls: "bg-emerald-100 text-emerald-700" },
  error: { label: "分析失败", cls: "bg-red-100 text-red-700" },
  source_missing: { label: "源文件缺失", cls: "bg-amber-100 text-amber-800" },
  pending: { label: "待处理", cls: "bg-gray-100 text-gray-700" },
  processing: { label: "处理中", cls: "bg-blue-100 text-blue-700" },
  shot_split: { label: "已拆镜头", cls: "bg-blue-100 text-blue-700" },
  ai_analyzing: { label: "AI 分析中", cls: "bg-blue-100 text-blue-700" },
  pending_review: { label: "待人工审核", cls: "bg-amber-100 text-amber-800" },
  searchable: { label: "可检索", cls: "bg-emerald-100 text-emerald-700" },
  paused: { label: "已暂停", cls: "bg-gray-100 text-gray-700" },
  archived: { label: "已归档", cls: "bg-gray-100 text-gray-500" },
};

const SCAN_STATUS: Record<ScanStatus, { label: string; cls: string }> = {
  never_scanned: { label: "未扫描", cls: "bg-gray-100 text-gray-600" },
  queued: { label: "排队中", cls: "bg-blue-100 text-blue-700" },
  scanning: { label: "扫描中", cls: "bg-blue-100 text-blue-700" },
  completed: { label: "已完成", cls: "bg-emerald-100 text-emerald-700" },
  failed: { label: "失败", cls: "bg-red-100 text-red-700" },
  cancelled: { label: "已取消", cls: "bg-gray-100 text-gray-600" },
};

const SHOT_STATUS: Record<ShotStatus, { label: string; cls: string }> = {
  pending: { label: "待处理", cls: "bg-gray-100 text-gray-700" },
  processing: { label: "处理中", cls: "bg-blue-100 text-blue-700" },
  ready: { label: "可用", cls: "bg-emerald-100 text-emerald-700" },
  failed: { label: "失败", cls: "bg-red-100 text-red-700" },
};

const MEDIA_RUN_STATUS: Record<MediaRunStatus, { label: string; cls: string }> = {
  queued: { label: "排队中", cls: "bg-blue-100 text-blue-700" },
  running: { label: "分析中", cls: "bg-blue-100 text-blue-700" },
  completed: { label: "已拆镜头", cls: "bg-emerald-100 text-emerald-700" },
  failed: { label: "分析失败", cls: "bg-red-100 text-red-700" },
  cancelled: { label: "已取消", cls: "bg-gray-100 text-gray-600" },
};

export function Badge({ label, cls }: { label: string; cls: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

export function AssetStatusBadge({ status }: { status: AssetStatus }) {
  const info = ASSET_STATUS[status] ?? { label: status, cls: "bg-gray-100 text-gray-700" };
  return <Badge label={info.label} cls={info.cls} />;
}

export function ScanStatusBadge({ status }: { status: ScanStatus }) {
  const info = SCAN_STATUS[status] ?? { label: status, cls: "bg-gray-100 text-gray-700" };
  return <Badge label={info.label} cls={info.cls} />;
}

export function ShotStatusBadge({ status }: { status: ShotStatus }) {
  const info = SHOT_STATUS[status] ?? { label: status, cls: "bg-gray-100 text-gray-700" };
  return <Badge label={info.label} cls={info.cls} />;
}

export function MediaRunStatusBadge({ status }: { status: MediaRunStatus }) {
  const info = MEDIA_RUN_STATUS[status] ?? { label: status, cls: "bg-gray-100 text-gray-700" };
  return <Badge label={info.label} cls={info.cls} />;
}

// ============================================================
// PR-B 最终成片 / 使用血缘
// ============================================================

const FINAL_VIDEO_STATUS: Record<FinalVideoStatus, { label: string; cls: string }> = {
  draft: { label: "草稿", cls: "bg-gray-100 text-gray-700" },
  ready: { label: "就绪", cls: "bg-blue-100 text-blue-700" },
  completed: { label: "已完成", cls: "bg-emerald-100 text-emerald-700" },
  archived: { label: "已归档", cls: "bg-gray-100 text-gray-500" },
};

export function FinalVideoStatusBadge({ status }: { status: FinalVideoStatus }) {
  const meta = FINAL_VIDEO_STATUS[status];
  return <Badge label={meta.label} cls={meta.cls} />;
}

// 只有 confirmed 计入正式使用次数；其余状态一律不计数（在 UI 中如实区分展示）
const USAGE_STATUS: Record<UsageStatus, { label: string; cls: string }> = {
  proposed: { label: "候选待确认", cls: "bg-amber-100 text-amber-800" },
  suspected: { label: "疑似", cls: "bg-amber-100 text-amber-800" },
  confirmed: { label: "已确认使用", cls: "bg-emerald-100 text-emerald-700" },
  rejected: { label: "已驳回", cls: "bg-red-100 text-red-700" },
  revoked: { label: "已撤销", cls: "bg-gray-100 text-gray-500" },
};

export function UsageStatusBadge({ status }: { status: UsageStatus }) {
  const meta = USAGE_STATUS[status];
  return <Badge label={meta.label} cls={meta.cls} />;
}

const EVIDENCE_LABEL: Record<UsageEvidenceMethod, string> = {
  manual: "人工添加",
  clipmind_project: "项目候选",
  editor_project: "剪辑工程（未实现）",
  visual_match: "视觉反查（未实现）",
  audio_match: "音频指纹（未实现）",
  legacy_path_rule: "历史目录（未实现）",
};

export function EvidenceBadge({ method }: { method: UsageEvidenceMethod }) {
  return (
    <Badge label={EVIDENCE_LABEL[method] ?? method} cls="bg-indigo-50 text-indigo-700" />
  );
}
