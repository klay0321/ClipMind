"use client";

import { useState } from "react";

import { TopNav } from "@/components/TopNav";
import { cn } from "@/lib/cn";

import { EvidencePanel } from "./EvidencePanel";
import { ImportsPanel } from "./ImportsPanel";
import { RulesPanel } from "./RulesPanel";

type TabKey = "rules" | "imports" | "pending" | "reviewed";

const TABS: { key: TabKey; label: string; testId: string }[] = [
  { key: "rules", label: "规则管理", testId: "tab-rules" },
  { key: "imports", label: "导入任务", testId: "tab-imports" },
  { key: "pending", label: "待审核", testId: "tab-pending" },
  { key: "reviewed", label: "已审核", testId: "tab-reviewed" },
];

export function UsageEvidenceView() {
  const [tab, setTab] = useState<TabKey>("pending");

  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="usage-evidence" />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <h1 className="text-xl font-semibold text-gray-800">历史使用证据</h1>
        <p className="mb-4 mt-1 text-xs text-gray-500">
          把历史遗留的&ldquo;已使用&rdquo;目录/文件名标记转换为<span className="font-medium text-gray-700">弱证据</span>并人工审核。
          接受证据只代表素材<span className="font-medium text-gray-700">历史上很可能用过（次数未知）</span>，
          不会创建正式使用记录，也不会改变任何 confirmed 使用次数。
        </p>

        <div className="mb-4 flex gap-1 border-b border-gray-200" role="tablist" aria-label="历史使用证据分区">
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

        {tab === "rules" ? <RulesPanel /> : null}
        {tab === "imports" ? <ImportsPanel /> : null}
        {tab === "pending" ? <EvidencePanel mode="pending" /> : null}
        {tab === "reviewed" ? <EvidencePanel mode="reviewed" /> : null}
      </main>
    </div>
  );
}
