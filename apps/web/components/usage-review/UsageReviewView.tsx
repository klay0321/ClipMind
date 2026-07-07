"use client";

import Link from "next/link";
import { useState } from "react";

import { TopNav } from "@/components/TopNav";
import { FinalVideosPanel } from "@/components/final-videos/FinalVideosView";
import { Loading } from "@/components/states/Loading";
import { useUsageReviewSummary } from "@/lib/hooks";
import { cn } from "@/lib/cn";
import type { ReviewGroup } from "@/lib/types";

import { ReviewTable } from "./ReviewTable";
import { FORMAL_COUNT_NOTICE, LEGACY_MEANING_NOTICE } from "./reviewShared";

type TabKey = "overview" | "pending" | "formal" | "legacy" | "processed" | "final-videos";

const TABS: { key: TabKey; label: string; testId: string }[] = [
  { key: "overview", label: "总览", testId: "tab-overview" },
  { key: "pending", label: "待审核", testId: "tab-pending" },
  { key: "formal", label: "正式血缘", testId: "tab-formal" },
  { key: "legacy", label: "历史证据", testId: "tab-legacy" },
  { key: "processed", label: "已处理", testId: "tab-processed" },
  { key: "final-videos", label: "成片登记", testId: "tab-final-videos" },
];

export function UsageReviewView() {
  const [tab, setTab] = useState<TabKey>("pending");
  const [processedGroup, setProcessedGroup] = useState<ReviewGroup>("accepted_or_confirmed");

  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="usage-review" />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-800">使用记录中心</h1>
          <Link
            href="/usage-evidence"
            className="text-sm text-brand hover:underline"
            data-testid="link-rules-imports"
          >
            规则与导入管理 →
          </Link>
        </div>
        {/* 固定双提示（语义冻结，测试锁定） */}
        <div className="mb-4 mt-2 rounded border border-gray-200 bg-white px-3 py-2 text-xs text-gray-600">
          <p data-testid="formal-count-notice">{FORMAL_COUNT_NOTICE}</p>
          <p data-testid="legacy-meaning-notice">{LEGACY_MEANING_NOTICE}</p>
        </div>

        <div
          className="mb-4 flex gap-1 border-b border-gray-200"
          role="tablist"
          aria-label="使用记录中心分区"
        >
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              data-testid={t.testId}
              onClick={() => setTab(t.key)}
              className={cn(
                "rounded-t px-3 py-2 text-sm",
                tab === t.key
                  ? "border-b-2 border-brand font-medium text-brand"
                  : "text-gray-500 hover:text-gray-800",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "overview" ? <OverviewPanel /> : null}
        {tab === "pending" ? (
          <ReviewTable
            filters={{ review_group: "needs_review" }}
            testId="pending-table"
          />
        ) : null}
        {tab === "formal" ? (
          <ReviewTable
            filters={{ item_type: "final_video_usage" }}
            testId="formal-table"
          />
        ) : null}
        {tab === "legacy" ? (
          <ReviewTable
            filters={{ item_type: "legacy_usage_evidence" }}
            testId="legacy-table"
          />
        ) : null}
        {tab === "processed" ? (
          <div>
            <select
              value={processedGroup}
              onChange={(e) => setProcessedGroup(e.target.value as ReviewGroup)}
              aria-label="已处理分组"
              className="mb-3 w-44 rounded border border-gray-300 px-2 py-1.5 text-sm"
              data-testid="processed-group-filter"
            >
              <option value="accepted_or_confirmed">已确认 / 已接受</option>
              <option value="rejected">已驳回</option>
              <option value="conflict">冲突</option>
              <option value="revoked">已撤销</option>
            </select>
            <ReviewTable
              filters={{ review_group: processedGroup }}
              testId="processed-table"
            />
          </div>
        ) : null}
        {tab === "final-videos" ? <FinalVideosPanel /> : null}
      </main>
    </div>
  );
}

function OverviewPanel() {
  const summary = useUsageReviewSummary();
  const s = summary.data;
  if (summary.isLoading || !s) {
    return <Loading rows={3} />;
  }
  return (
    <div data-testid="overview-panel">
      <p className="mb-2 text-xs text-gray-500">
        两组统计<span className="font-medium text-gray-700">并列展示、口径不同</span>：
        正式血缘按镜头引用计数；历史证据只是素材级线索——两者绝不相加。
      </p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <SummaryCard label="正式确认使用" value={s.formal.confirmed} tone="emerald" testId="card-confirmed" />
        <SummaryCard
          label="正式候选"
          value={s.formal.proposed + s.formal.suspected}
          tone="blue"
          testId="card-proposed"
        />
        <SummaryCard label="历史证据待审核" value={s.legacy.pending} tone="amber" testId="card-legacy-pending" />
        <SummaryCard label="历史证据已接受" value={s.legacy.accepted} tone="amber" testId="card-legacy-accepted" />
        <SummaryCard label="冲突" value={s.legacy.conflict} tone="red" testId="card-conflict" />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <SummaryCard label="待人工处理合计" value={s.needs_review_total} tone="gray" testId="card-needs-review" />
        <SummaryCard label="正式已驳回" value={s.formal.rejected} tone="gray" testId="card-formal-rejected" />
        <SummaryCard label="正式已撤销" value={s.formal.revoked} tone="gray" testId="card-formal-revoked" />
        <SummaryCard label="历史证据已驳回" value={s.legacy.rejected} tone="gray" testId="card-legacy-rejected" />
      </div>
    </div>
  );
}

const CARD_TONES: Record<string, string> = {
  emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
  blue: "border-blue-200 bg-blue-50 text-blue-800",
  amber: "border-amber-200 bg-amber-50 text-amber-800",
  red: "border-red-200 bg-red-50 text-red-800",
  gray: "border-gray-200 bg-white text-gray-700",
};

function SummaryCard({
  label,
  value,
  tone,
  testId,
}: {
  label: string;
  value: number;
  tone: string;
  testId: string;
}) {
  return (
    <div className={cn("rounded-lg border px-3 py-2.5", CARD_TONES[tone])} data-testid={testId}>
      <div className="text-2xl font-semibold">{value}</div>
      <div className="mt-0.5 text-xs opacity-80">{label}</div>
    </div>
  );
}
