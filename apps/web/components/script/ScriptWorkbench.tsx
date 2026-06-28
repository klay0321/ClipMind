// 脚本匹配工作台：双 Tab（脚本与匹配 / 剪辑清单）。左脚本+段落、右候选；顶栏全脚本匹配；
// 预览弹窗。所有数据来自真实 Gate A/B API，绝不前端伪造候选/分数/理由。
"use client";

import { useEffect, useMemo, useState } from "react";

import {
  useMatchScript,
  useParseScript,
  useProducts,
  useScriptMatchStatus,
  useScriptProject,
} from "@/lib/hooks";
import type { ScriptMatchResponse } from "@/lib/types";
import { PreviewModal } from "@/components/PreviewModal";
import { TopNav } from "@/components/TopNav";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";

import { CandidatePanel } from "./CandidatePanel";
import { EditListTab } from "./EditListTab";
import { ScriptInputPanel } from "./ScriptInputPanel";
import { ScriptTopBar } from "./ScriptTopBar";
import { SegmentList } from "./SegmentList";

type Tab = "match" | "editlist";

export function ScriptWorkbench({ scriptId }: { scriptId: number | null }) {
  const projectQ = useScriptProject(scriptId);
  const statusQ = useScriptMatchStatus(scriptId);
  const productsQ = useProducts();
  const matchAll = useMatchScript(scriptId ?? 0);
  const parse = useParseScript(scriptId ?? 0);

  const [tab, setTab] = useState<Tab>("match");
  const [selectedSegmentId, setSelectedSegmentId] = useState<number | null>(null);
  const [previewShotId, setPreviewShotId] = useState<number | null>(null);
  const [matchResult, setMatchResult] = useState<ScriptMatchResponse | null>(null);

  const project = projectQ.data;
  // useMemo 让 segments 引用随 project 变化才更新，避免每次 render 触发下方 useEffect。
  const segments = useMemo(() => project?.segments ?? [], [project]);

  // 项目加载后默认选中第一段（仅当当前选中已不存在时）
  useEffect(() => {
    if (segments.length === 0) {
      setSelectedSegmentId(null);
      return;
    }
    setSelectedSegmentId((cur) =>
      cur != null && segments.some((s) => s.id === cur) ? cur : segments[0].id,
    );
  }, [segments]);

  if (scriptId == null) {
    return (
      <div className="min-h-screen bg-gray-50">
        <TopNav active="script" />
        <main className="mx-auto max-w-3xl px-4 py-10">
          <ErrorState message="脚本 id 无效" />
        </main>
      </div>
    );
  }

  const selectedIndex = segments.findIndex((s) => s.id === selectedSegmentId);
  const selectedSegment = selectedIndex >= 0 ? segments[selectedIndex] : null;
  const hasLocked = segments.some((s) => s.locked_shot_id != null);
  const canMatch = segments.length > 0;

  const onMatchAll = () => {
    if (!canMatch || matchAll.isPending) return;
    matchAll.mutate({}, { onSuccess: (res) => setMatchResult(res) });
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="script" />
      <main className="mx-auto max-w-7xl space-y-3 px-4 py-5">
        {projectQ.isLoading ? (
          <Loading rows={4} />
        ) : projectQ.isError ? (
          <ErrorState
            message={(projectQ.error as Error)?.message ?? "脚本项目加载失败"}
            onRetry={() => void projectQ.refetch()}
          />
        ) : project == null ? (
          <Empty title="未找到脚本项目" description="返回列表选择或新建脚本项目。" />
        ) : (
          <>
            <ScriptTopBar
              project={project}
              status={statusQ.data}
              onMatchAll={onMatchAll}
              matchingAll={matchAll.isPending}
              canMatch={canMatch}
            />

            {matchResult ? (
              <div
                className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded bg-emerald-50 px-3 py-1.5 text-[11px] text-emerald-700"
                data-testid="match-result"
                role="status"
              >
                <span>全脚本匹配完成</span>
                <span>已匹配 {matchResult.completed_segments.length}</span>
                {matchResult.skipped_locked_segments.length ? (
                  <span className="text-brand-dark">
                    跳过锁定 {matchResult.skipped_locked_segments.length}
                  </span>
                ) : null}
                {matchResult.failed_segments.length ? (
                  <span className="text-red-600">失败 {matchResult.failed_segments.length}</span>
                ) : null}
              </div>
            ) : null}

            {/* Tabs */}
            <div role="tablist" aria-label="脚本工作台视图" className="flex gap-1 border-b border-gray-200">
              {([
                ["match", "脚本与匹配"],
                ["editlist", "剪辑清单"],
              ] as [Tab, string][]).map(([key, label]) => (
                <button
                  key={key}
                  role="tab"
                  id={`tab-${key}`}
                  data-testid={`tab-${key}`}
                  aria-selected={tab === key}
                  aria-controls={`panel-${key}`}
                  onClick={() => setTab(key)}
                  className={`-mb-px rounded-t px-3 py-1.5 text-sm ${
                    tab === key
                      ? "border-x border-t border-gray-200 bg-white font-medium text-brand"
                      : "text-gray-500 hover:text-gray-800"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {tab === "match" ? (
              <div role="tabpanel" id="panel-match" aria-labelledby="tab-match" className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(320px,420px)_1fr]">
                <div className="space-y-3">
                  <ScriptInputPanel
                    project={project}
                    hasLocked={hasLocked}
                    onParse={(opts) => parse.mutate(opts)}
                    parsing={parse.isPending}
                    parseError={parse.error}
                  />
                  {segments.length === 0 ? (
                    <Empty title="尚未拆段" description="点击「AI 拆段」把脚本拆成可匹配的段落。" />
                  ) : (
                    <SegmentList
                      scriptId={scriptId}
                      segments={segments}
                      products={productsQ.data ?? []}
                      selectedSegmentId={selectedSegmentId}
                      onSelect={setSelectedSegmentId}
                    />
                  )}
                </div>
                <CandidatePanel
                  scriptId={scriptId}
                  segment={selectedSegment}
                  segmentIndex={selectedIndex >= 0 ? selectedIndex : null}
                  onPreview={setPreviewShotId}
                />
              </div>
            ) : (
              <div role="tabpanel" id="panel-editlist" aria-labelledby="tab-editlist">
                <EditListTab scriptId={scriptId} active={tab === "editlist"} onPreview={setPreviewShotId} />
              </div>
            )}
          </>
        )}
      </main>
      <PreviewModal shotId={previewShotId} onClose={() => setPreviewShotId(null)} />
    </div>
  );
}
