import { Chip, type Tone } from "@/components/ui";
import type {
  LegacyImportRunStatus,
  LegacyMatchOperator,
  LegacyMatchTarget,
  LegacyReviewStatus,
  LegacyUsageState,
} from "@/lib/types";

// 固定警示文案（产品语义冻结，测试锁定；勿改写）
export const ACCEPT_WARNING =
  "接受历史证据不等于确认使用次数，也不等于确认对应成片或具体镜头";
export const IMPORT_WARNING =
  "本操作只创建历史使用证据，不会修改文件、不会创建正式使用次数、不会绑定最终成片";

export const MATCH_TARGET_LABELS: Record<LegacyMatchTarget, string> = {
  directory_segment: "目录名",
  filename: "文件名",
  filename_stem: "文件名（不含扩展名）",
  extension: "扩展名",
  relative_path: "完整相对路径",
};

export const MATCH_OPERATOR_LABELS: Record<LegacyMatchOperator, string> = {
  equals: "等于",
  contains: "包含",
  starts_with: "开头是",
  ends_with: "结尾是",
};

const REVIEW_STATUS_META: Record<LegacyReviewStatus, { label: string; tone: Tone }> = {
  pending: { label: "待审核", tone: "warning" },
  accepted: { label: "已接受", tone: "success" },
  rejected: { label: "已驳回", tone: "muted" },
  conflict: { label: "冲突", tone: "danger" },
};

export function ReviewStatusChip({ status }: { status: LegacyReviewStatus }) {
  const meta = REVIEW_STATUS_META[status] ?? { label: status, tone: "neutral" as Tone };
  return (
    <Chip tone={meta.tone} dot>
      {meta.label}
    </Chip>
  );
}

// 派生历史使用状态 —— legacy_used_unknown 的展示语义是"历史上用过（次数未知）"，
// 绝不允许显示成"已使用 1 次"。
const LEGACY_STATE_META: Record<LegacyUsageState, { label: string; tone: Tone }> = {
  no_legacy_evidence: { label: "无历史使用证据", tone: "muted" },
  legacy_evidence_pending: { label: "历史证据待审核", tone: "warning" },
  legacy_used_unknown: { label: "历史上用过（次数未知）", tone: "info" },
  legacy_evidence_rejected: { label: "历史证据已驳回", tone: "muted" },
  legacy_evidence_conflict: { label: "历史证据冲突", tone: "danger" },
};

export function LegacyStateChip({ state }: { state: LegacyUsageState }) {
  const meta = LEGACY_STATE_META[state] ?? { label: state, tone: "neutral" as Tone };
  return <Chip tone={meta.tone}>{meta.label}</Chip>;
}

const RUN_STATUS_META: Record<LegacyImportRunStatus, { label: string; tone: Tone }> = {
  pending: { label: "排队中", tone: "neutral" },
  running: { label: "执行中", tone: "info" },
  completed: { label: "已完成", tone: "success" },
  completed_with_errors: { label: "完成（含错误）", tone: "warning" },
  failed: { label: "失败", tone: "danger" },
  cancelled: { label: "已取消", tone: "muted" },
};

export function RunStatusChip({ status }: { status: LegacyImportRunStatus }) {
  const meta = RUN_STATUS_META[status] ?? { label: status, tone: "neutral" as Tone };
  return (
    <Chip tone={meta.tone} dot>
      {meta.label}
    </Chip>
  );
}

const LOCATION_STATUS_LABELS: Record<string, string> = {
  present: "在库",
  missing: "缺失",
  historical: "历史位置",
};

export function locationStatusLabel(status: string | null): string {
  if (!status) return "—";
  return LOCATION_STATUS_LABELS[status] ?? status;
}
