// PR-05 脚本匹配 UI 共享常量与展示助手（标签/格式化纯函数，绝不改写后端数据）。

import type {
  DurationFitStatus,
  ScriptMatchStatusKind,
  ScriptParseStatus,
  SelectionStatus,
  StructuredRequirements,
} from "./types";

// 与后端 schema 对齐（packages/shared/clipmind_shared/script/schema.py）
export const MAX_SCRIPT_LENGTH = 20_000;
export const MAX_SEGMENTS = 50;
// 候选数上限（editlist.MAX_CANDIDATE_LIMIT）
export const MAX_CANDIDATE_LIMIT = 50;

// 候选 final_score（[0,1]）→ 整数百分比（不增加虚假精度）
export function scorePercent(score: number | null | undefined): number {
  if (score == null) return 0;
  return Math.round(score * 100);
}

// 分项分（[0,1]）→ 展示字符串；null = 未参与该通道（绝不当 0）
export function subScoreLabel(v: number | null | undefined): string {
  return v == null ? "未参与" : `${Math.round(v * 100)}%`;
}

export function parseStatusLabel(s: ScriptParseStatus): string {
  return { pending: "待拆段", ok: "拆段成功", degraded: "规则降级", failed: "拆段失败" }[s];
}

export function matchStatusLabel(s: ScriptMatchStatusKind): string {
  return { pending: "未匹配", matched: "已匹配", gap: "缺口", degraded: "降级匹配" }[s];
}

export function matchStatusTone(s: ScriptMatchStatusKind): string {
  return {
    pending: "bg-gray-100 text-gray-600",
    matched: "bg-emerald-50 text-emerald-700",
    gap: "bg-red-100 text-red-700",
    degraded: "bg-amber-50 text-amber-700",
  }[s];
}

export function selectionStatusLabel(s: SelectionStatus): string {
  return { locked: "已锁定", selected: "已选择", recommended: "系统推荐", none: "未选用" }[s];
}

export function selectionStatusTone(s: SelectionStatus): string {
  return {
    locked: "bg-brand text-white",
    selected: "bg-brand-light text-brand-dark",
    recommended: "bg-gray-100 text-gray-600",
    none: "bg-gray-50 text-gray-400",
  }[s];
}

export function durationStatusLabel(s: DurationFitStatus | null): string {
  if (s == null) return "—";
  return { fit: "时长合适", too_long: "偏长", too_short: "偏短", no_target: "无目标" }[s];
}

// 结构化需求 → 用于段落概览的去重标签数组（仅展示，不参与匹配计算）
export function structuredTerms(s: StructuredRequirements | null): string[] {
  if (!s) return [];
  const out: string[] = [];
  const push = (label: string, arr?: string[]) => {
    if (arr && arr.length) out.push(`${label}：${arr.slice(0, 4).join("、")}`);
  };
  push("场景", s.scenes);
  push("动作", s.actions);
  push("镜头", s.shot_types);
  push("营销", s.marketing_uses);
  return out;
}

// 时长范围展示
export function durationRangeLabel(min: number | null, max: number | null): string {
  if (min == null && max == null) return "未设";
  const lo = min == null ? "" : `${min}s`;
  const hi = max == null ? "" : `${max}s`;
  return `${lo}~${hi}`;
}
