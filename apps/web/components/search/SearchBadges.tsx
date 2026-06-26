// 搜索结果用的小徽章：审核状态 / 风险 / degraded / 推荐等级 / 产品匹配方式。
// 全部只读后端事实，颜色非唯一信息载体（均带文字）。

import type { RecommendationLevel } from "@/lib/types";
import {
  RECOMMENDATION_LABELS,
  RECOMMENDATION_TONE,
  REVIEW_STATUS_LABELS,
  REVIEW_STATUS_TONE,
} from "@/lib/search";

function Pill({ label, tone, title }: { label: string; tone: string; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${tone}`}
    >
      {label}
    </span>
  );
}

export function ReviewStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const label = REVIEW_STATUS_LABELS[status] ?? status;
  const tone = REVIEW_STATUS_TONE[status] ?? "bg-gray-100 text-gray-600";
  return <Pill label={`审核：${label}`} tone={tone} />;
}

export function StaleBadge({ stale }: { stale: boolean }) {
  if (!stale) return null;
  return <Pill label="审核已过期" tone="bg-amber-50 text-amber-700" title="历史人工结果已过期，需重新审核" />;
}

/** embedding 降级：中性提示，绝不伪装成错误，也不显示"语义相似"。 */
export function DegradedTag({ degraded }: { degraded: boolean }) {
  if (!degraded) return null;
  return (
    <Pill
      label="语义降级"
      tone="bg-slate-100 text-slate-600"
      title="该镜头未参与语义向量召回，仅由关键词/标签/产品命中"
    />
  );
}

export function RecommendationBadge({ level }: { level: RecommendationLevel }) {
  return <Pill label={RECOMMENDATION_LABELS[level]} tone={RECOMMENDATION_TONE[level]} />;
}

export function HumanConfirmTag({ requires }: { requires: boolean }) {
  if (!requires) return null;
  return (
    <Pill
      label="需人工确认"
      tone="bg-amber-50 text-amber-700"
      title="该镜头审核状态非已确认/已修改，使用前建议人工确认"
    />
  );
}

const MATCH_KIND_LABELS: Record<string, string> = {
  sku: "SKU 精确",
  model: "型号匹配",
  brand: "品牌匹配",
  name: "名称匹配",
  alias: "别名匹配",
  associated: "已关联",
};

export function ProductMatchTag({ kind }: { kind: string | null | undefined }) {
  if (!kind) return null;
  const label = MATCH_KIND_LABELS[kind] ?? kind;
  return <Pill label={label} tone="bg-brand-light text-brand-dark" />;
}
