import { Chip, type Tone } from "@/components/ui";
import type { ReviewItemType, SourceStrength } from "@/lib/types";

// 固定双提示（产品语义冻结，测试锁定；勿改写）
export const FORMAL_COUNT_NOTICE = "正式使用次数只来自已确认的成片与镜头血缘。";
export const LEGACY_MEANING_NOTICE =
  "历史路径证据仅表示“可能曾使用，次数和成片未知”。";

// 类型标签：颜色与图标必须明显不同（formal=蓝▶；legacy=琥珀🕘）
export function ItemTypeChip({
  type,
  confirmed = false,
}: {
  type: ReviewItemType;
  confirmed?: boolean;
}) {
  if (type === "final_video_usage") {
    return (
      <Chip tone="brand">
        <span aria-hidden>▶</span> {confirmed ? "正式血缘" : "正式血缘候选"}
      </Chip>
    );
  }
  return (
    <Chip tone="warning">
      <span aria-hidden>🕘</span> 历史弱证据
    </Chip>
  );
}

const STRENGTH_META: Record<SourceStrength, { label: string; tone: Tone }> = {
  confirmed_lineage: { label: "已确认血缘", tone: "success" },
  manual_proposed_lineage: { label: "人工候选", tone: "info" },
  project_proposed_lineage: { label: "项目候选", tone: "info" },
  suspected_lineage: { label: "疑似血缘", tone: "neutral" },
  accepted_legacy_evidence: { label: "历史证据·已接受", tone: "warning" },
  pending_legacy_evidence: { label: "历史证据·待审", tone: "warning" },
  rejected_or_conflict: { label: "已驳回/冲突", tone: "muted" },
};

export function StrengthChip({ strength }: { strength: SourceStrength }) {
  const meta = STRENGTH_META[strength] ?? { label: strength, tone: "neutral" as Tone };
  return (
    <Chip tone={meta.tone} dot>
      {meta.label}
    </Chip>
  );
}

// 行内/批量动作文案（typed；混合类型批次禁用）
export const ACTION_LABELS: Record<string, string> = {
  confirm: "确认",
  reject: "驳回",
  revoke: "撤销",
  restore_proposal: "恢复候选",
  accept: "接受",
  mark_conflict: "标冲突",
  reset: "重置待审",
};

export const REVIEW_STATUS_LABELS: Record<string, string> = {
  proposed: "候选",
  suspected: "疑似",
  confirmed: "已确认",
  rejected: "已驳回",
  revoked: "已撤销",
  pending: "待审核",
  accepted: "已接受",
  conflict: "冲突",
};
