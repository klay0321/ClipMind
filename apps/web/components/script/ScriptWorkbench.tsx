// 脚本匹配工作台：剪辑清单为主视图（右侧主表）；左侧脚本原文 + 段落；候选镜头走抽屉。
// 顶栏含全脚本匹配与「导出剪辑清单 ▾」。所有数据来自真实 Gate A/B API，绝不前端伪造候选/分数/理由。
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
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/overlay";
import { PreviewModal } from "@/components/PreviewModal";
import { TopNav } from "@/components/TopNav";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";

import { CandidatePanel } from "./CandidatePanel";
import { EditListTab } from "./EditListTab";
import { ScriptInputPanel } from "./ScriptInputPanel";
import { ScriptMultiExportPanel } from "./ScriptMultiExportPanel";
import { ScriptTopBar } from "./ScriptTopBar";
import { SegmentList } from "./SegmentList";

export function ScriptWorkbench({ scriptId }: { scriptId: number | null }) {
  const projectQ = useScriptProject(scriptId);
  const statusQ = useScriptMatchStatus(scriptId);
  const productsQ = useProducts();
  const matchAll = useMatchScript(scriptId ?? 0);
  const parse = useParseScript(scriptId ?? 0);

  const [selectedSegmentId, setSelectedSegmentId] = useState<number | null>(null);
  const [previewShotId, setPreviewShotId] = useState<number | null>(null);
  const [matchResult, setMatchResult] = useState<ScriptMatchResponse | null>(null);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  const project = projectQ.data;
  const segments = useMemo(() => project?.segments ?? [], [project]);

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

  const openCandidates = (segmentId: number) => {
    setSelectedSegmentId(segmentId);
    setCandidateOpen(true);
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
              onToggleExport={() => setExportOpen((v) => !v)}
              exportOpen={exportOpen}
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

            {exportOpen ? <ScriptMultiExportPanel scriptId={scriptId} /> : null}

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(300px,380px)_1fr]">
              {/* 左：脚本原文 + 段落 */}
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
                  <>
                    <SegmentList
                      scriptId={scriptId}
                      segments={segments}
                      products={productsQ.data ?? []}
                      selectedSegmentId={selectedSegmentId}
                      onSelect={setSelectedSegmentId}
                    />
                    {selectedSegment ? (
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        onClick={() => setCandidateOpen(true)}
                      >
                        查看选中段候选镜头 →
                      </Button>
                    ) : null}
                  </>
                )}
              </div>

              {/* 右：剪辑清单主表 */}
              <EditListTab
                scriptId={scriptId}
                active
                onPreview={setPreviewShotId}
                onViewCandidates={openCandidates}
              />
            </div>
          </>
        )}
      </main>

      {/* 候选镜头抽屉：选择 / 锁定 / 重匹配 */}
      <Drawer
        open={candidateOpen && selectedSegment != null}
        onClose={() => setCandidateOpen(false)}
        title={selectedSegment ? `段 ${selectedIndex + 1} 候选镜头` : "候选镜头"}
        widthClass="max-w-lg"
      >
        <CandidatePanel
          scriptId={scriptId}
          segment={selectedSegment}
          segmentIndex={selectedIndex >= 0 ? selectedIndex : null}
          onPreview={setPreviewShotId}
        />
      </Drawer>

      <PreviewModal shotId={previewShotId} onClose={() => setPreviewShotId(null)} />
    </div>
  );
}
