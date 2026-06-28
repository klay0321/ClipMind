// 右栏：选中段落的候选镜头。代次/历史、缺口与补拍、选择/锁定/解锁（乐观锁 409）、详情抽屉。
"use client";

import { useState } from "react";

import { ApiError } from "@/lib/api";
import {
  useLockCandidate,
  useMatchSegment,
  useSegmentCandidates,
  useSelectCandidate,
  useUnlockSegment,
} from "@/lib/hooks";
import { matchStatusLabel, matchStatusTone, scorePercent } from "@/lib/script";
import type { ScriptCandidate, ScriptSegment } from "@/lib/types";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";

import { CandidateCard } from "./CandidateCard";
import { CandidateDrawer } from "./CandidateDrawer";

export function CandidatePanel({
  scriptId,
  segment,
  segmentIndex,
  onPreview,
}: {
  scriptId: number;
  segment: ScriptSegment | null;
  segmentIndex: number | null;
  onPreview: (shotId: number) => void;
}) {
  const [viewGen, setViewGen] = useState<number | null>(null);
  const [drawer, setDrawer] = useState<ScriptCandidate | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);

  const segId = segment?.id ?? null;
  const q = useSegmentCandidates(scriptId, segId, viewGen ?? undefined);
  const match = useMatchSegment(scriptId);
  const select = useSelectCandidate(scriptId);
  const lock = useLockCandidate(scriptId);
  const unlock = useUnlockSegment(scriptId);

  if (segment == null) {
    return (
      <Empty title="选择左侧段落" description="点击左侧任一段落，查看其候选镜头并进行选择/锁定。" />
    );
  }

  const data = q.data;
  const isHistory = data != null && viewGen != null && viewGen !== data.current_generation;
  const lockedShotId = data?.locked_shot_id ?? null;
  const selectedShotId = data?.selected_shot_id ?? null;

  const onSelect = (shotId: number) => {
    if (data == null || isHistory) return;
    setConflict(null);
    select.mutate(
      { segmentId: segment.id, req: { shot_id: shotId, lock_version: data.lock_version } },
      { onError: (e) => setConflict(e instanceof ApiError && e.status === 409 ? "数据已被更新，请刷新该段后重试。" : (e as Error).message) },
    );
  };
  const onLock = (shotId: number) => {
    if (data == null || isHistory) return;
    setConflict(null);
    const lockedElsewhere = lockedShotId != null && lockedShotId !== shotId;
    lock.mutate(
      { segmentId: segment.id, req: { shot_id: shotId, lock_version: data.lock_version, force: lockedElsewhere } },
      { onError: (e) => setConflict(e instanceof ApiError && e.status === 409 ? "数据已被更新，请刷新该段后重试。" : (e as Error).message) },
    );
  };
  const onUnlock = () => {
    if (data == null) return;
    setConflict(null);
    unlock.mutate({ segmentId: segment.id, lockVersion: data.lock_version });
  };

  const genButtons =
    data && data.current_generation > 1
      ? Array.from({ length: data.current_generation }, (_, i) => i + 1)
      : [];

  return (
    <section className="space-y-2" data-testid="candidate-panel">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-gray-800">
          段 {(segmentIndex ?? 0) + 1} 候选镜头
        </h2>
        {data ? (
          <span className={`rounded px-1.5 py-0.5 text-[10px] ${matchStatusTone(data.match_status)}`}>
            {matchStatusLabel(data.match_status)}
          </span>
        ) : null}
        <button
          type="button"
          data-testid="panel-rematch"
          onClick={() => {
            setViewGen(null);
            match.mutate({ segmentId: segment.id });
          }}
          disabled={match.isPending}
          className="ml-auto rounded border border-brand px-2.5 py-1 text-[11px] text-brand hover:bg-brand-light disabled:opacity-50"
        >
          {match.isPending ? "匹配中…" : segment.match_status === "pending" ? "匹配本段" : "重新匹配（新代次）"}
        </button>
      </div>

      {genButtons.length ? (
        <div className="flex flex-wrap items-center gap-1 text-[11px]" data-testid="gen-switcher">
          <span className="text-gray-400">代次</span>
          {genButtons.map((g) => {
            const isCurrent = data != null && g === data.current_generation;
            const activeGen = (viewGen ?? data?.current_generation) === g;
            return (
              <button
                key={g}
                type="button"
                onClick={() => setViewGen(isCurrent ? null : g)}
                className={`rounded px-1.5 py-0.5 ${activeGen ? "bg-brand text-white" : "border border-gray-200 text-gray-600 hover:bg-gray-50"}`}
              >
                {g}
                {isCurrent ? "（当前）" : ""}
              </button>
            );
          })}
        </div>
      ) : null}

      {isHistory ? (
        <p className="rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-700" data-testid="history-note">
          正在查看历史代次 {viewGen}（只读，不可选择/锁定）。
        </p>
      ) : null}

      {q.isLoading ? (
        <Loading rows={3} />
      ) : q.isError ? (
        <ErrorState message={(q.error as Error)?.message ?? "加载失败"} onRetry={() => void q.refetch()} />
      ) : data == null ? null : (
        <>
          {data.match_status === "gap" ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-2.5" data-testid="gap-notice">
              <p className="text-xs font-semibold text-red-700">本段无合适镜头（缺口）</p>
              {data.gap_reasons.length ? (
                <ul className="mt-1 list-disc pl-4 text-[11px] text-red-700">
                  {data.gap_reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              ) : null}
              {data.reshoot_recommendation.length ? (
                <div className="mt-1.5" data-testid="reshoot">
                  <span className="text-[11px] font-medium text-gray-700">补拍建议</span>
                  <ul className="mt-0.5 list-disc pl-4 text-[11px] text-gray-600">
                    {data.reshoot_recommendation.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}

          {lockedShotId != null && !isHistory ? (
            <div className="flex items-center gap-2 rounded bg-brand-light px-2 py-1.5 text-[11px] text-brand-dark" data-testid="locked-banner">
              <span>🔒 已锁定镜头 #{lockedShotId}（重匹配不覆盖）</span>
              <button
                type="button"
                data-testid="unlock-btn"
                onClick={onUnlock}
                disabled={unlock.isPending}
                className="ml-auto rounded border border-brand px-2 py-0.5 text-brand hover:bg-white disabled:opacity-50"
              >
                {unlock.isPending ? "解锁中…" : "解锁"}
              </button>
            </div>
          ) : null}

          {data.requires_human_confirmation && data.match_status !== "gap" ? (
            <p className="text-[11px] text-amber-700" data-testid="needs-confirm">
              建议人工复核：当前结果置信度有限或镜头未经人工确认。
            </p>
          ) : null}

          {data.degraded ? (
            <p className="text-[11px] text-amber-700">检索降级，结果可能不完整。</p>
          ) : null}

          {conflict ? (
            <p className="text-[11px] text-red-600" role="alert" data-testid="pick-conflict">
              {conflict}{" "}
              <button type="button" onClick={() => void q.refetch()} className="underline">
                刷新
              </button>
            </p>
          ) : null}

          {data.candidates.length === 0 ? (
            data.match_status === "gap" ? null : (
              <Empty title="暂无候选" description="点击「匹配本段」为该段生成候选镜头。" />
            )
          ) : (
            <div className="space-y-2" data-testid="candidate-list" aria-busy={q.isFetching}>
              {data.candidates.map((c) => {
                const isLocked = lockedShotId === c.shot_id;
                const isSelected = !isLocked && selectedShotId === c.shot_id;
                const isRecommended =
                  !isLocked && !isSelected && selectedShotId == null && lockedShotId == null && c.rank === 0;
                return (
                  <CandidateCard
                    key={c.shot_id}
                    candidate={c}
                    isSelected={isSelected}
                    isLocked={isLocked}
                    isRecommended={isRecommended}
                    lockedElsewhere={lockedShotId != null && lockedShotId !== c.shot_id}
                    onSelect={() => onSelect(c.shot_id)}
                    onLock={() => onLock(c.shot_id)}
                    onPreview={onPreview}
                    onOpenDetail={() => setDrawer(c)}
                    selecting={select.isPending && select.variables?.req.shot_id === c.shot_id}
                    locking={lock.isPending && lock.variables?.req.shot_id === c.shot_id}
                  />
                );
              })}
            </div>
          )}

          <p className="text-center text-[10px] text-gray-400">
            代次 {data.generation} · 共 {data.candidate_count} 个候选
            {data.best_score != null ? ` · 最高 ${scorePercent(data.best_score)}%` : ""}
            {isHistory ? "（历史，只读）" : ""}
          </p>
        </>
      )}

      <CandidateDrawer candidate={drawer} onClose={() => setDrawer(null)} onPreview={onPreview} />
    </section>
  );
}
