"use client";

import { useState } from "react";

import { Pagination } from "@/components/Pagination";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { Button, Dialog } from "@/components/ui";
import { ApiError } from "@/lib/api";
import {
  useLegacyBulkReview,
  useLegacyEvidence,
  useLegacyEvidenceAction,
  useLegacyEvidenceEvents,
} from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";
import type { LegacyEvidence, LegacyReviewStatus } from "@/lib/types";

import {
  ACCEPT_WARNING,
  MATCH_TARGET_LABELS,
  ReviewStatusChip,
  locationStatusLabel,
} from "./legacyShared";

const PAGE_SIZE = 20;

/** mode=pending：待审核工作台（含批量）；mode=reviewed：已审核列表（可重置/标冲突）。 */
export function EvidencePanel({ mode }: { mode: "pending" | "reviewed" }) {
  const [page, setPage] = useState(1);
  const [reviewedFilter, setReviewedFilter] = useState<LegacyReviewStatus>("accepted");
  const [selected, setSelected] = useState<number[]>([]);
  const [eventsFor, setEventsFor] = useState<LegacyEvidence | null>(null);

  const status: LegacyReviewStatus = mode === "pending" ? "pending" : reviewedFilter;
  const query = useLegacyEvidence({ page, page_size: PAGE_SIZE, review_status: status });
  const action = useLegacyEvidenceAction();
  const bulk = useLegacyBulkReview();

  const items = query.data?.items ?? [];
  const allSelected = items.length > 0 && items.every((e) => selected.includes(e.id));

  const toggleAll = () => {
    setSelected(allSelected ? [] : items.map((e) => e.id));
  };
  const toggleOne = (id: number) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };
  const runBulk = (bulkAction: "bulk-accept" | "bulk-reject") => {
    if (selected.length === 0) return;
    bulk.mutate(
      { action: bulkAction, payload: { evidence_ids: selected } },
      { onSuccess: () => setSelected([]) },
    );
  };

  return (
    <section aria-label={mode === "pending" ? "待审核证据" : "已审核证据"}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-amber-800" data-testid="accept-warning">
          {ACCEPT_WARNING}
        </p>
        {mode === "reviewed" ? (
          <select
            value={reviewedFilter}
            onChange={(e) => {
              setReviewedFilter(e.target.value as LegacyReviewStatus);
              setPage(1);
              setSelected([]);
            }}
            aria-label="已审核状态筛选"
            className="w-32 rounded border border-gray-300 px-2 py-1.5 text-sm"
            data-testid="reviewed-filter"
          >
            <option value="accepted">已接受</option>
            <option value="rejected">已驳回</option>
            <option value="conflict">冲突</option>
          </select>
        ) : null}
      </div>

      {mode === "pending" ? (
        <div className="mb-3 flex items-center gap-2">
          <Button
            size="sm"
            disabled={selected.length === 0 || bulk.isPending}
            onClick={() => runBulk("bulk-accept")}
            data-testid="bulk-accept-button"
          >
            批量接受（{selected.length}）
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={selected.length === 0 || bulk.isPending}
            onClick={() => runBulk("bulk-reject")}
            data-testid="bulk-reject-button"
          >
            批量驳回（{selected.length}）
          </Button>
          {bulk.isError ? (
            <span className="text-xs text-red-600">
              {bulk.error instanceof ApiError ? bulk.error.message : "批量操作失败"}
            </span>
          ) : bulk.data ? (
            <span className="text-xs text-gray-500" data-testid="bulk-result">
              成功 {bulk.data.succeeded}，跳过 {bulk.data.skipped}
            </span>
          ) : null}
        </div>
      ) : null}

      {query.isLoading ? (
        <Loading rows={5} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => void query.refetch()} />
      ) : items.length === 0 ? (
        <Empty
          title={mode === "pending" ? "没有待审核的历史证据" : "此状态下没有证据"}
          description={
            mode === "pending"
              ? "先在「导入任务」中运行只读预览并正式导入。"
              : "切换筛选或先在待审核里处理证据。"
          }
        />
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="w-full min-w-[960px] text-sm" data-testid="evidence-table">
              <thead>
                <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                  {mode === "pending" ? (
                    <th className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={toggleAll}
                        aria-label="全选本页"
                        data-testid="select-all-checkbox"
                      />
                    </th>
                  ) : null}
                  <th className="px-3 py-2 font-medium">素材</th>
                  <th className="px-3 py-2 font-medium">命中路径</th>
                  <th className="px-3 py-2 font-medium">命中内容</th>
                  <th className="px-3 py-2 font-medium">规则</th>
                  <th className="px-3 py-2 font-medium">观察次数</th>
                  <th className="px-3 py-2 font-medium">正式使用（对照）</th>
                  <th className="px-3 py-2 font-medium">状态</th>
                  <th className="px-3 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((ev) => (
                  <tr
                    key={ev.id}
                    data-testid={`evidence-row-${ev.id}`}
                    className="border-b border-gray-50 last:border-0 hover:bg-gray-50"
                  >
                    {mode === "pending" ? (
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          checked={selected.includes(ev.id)}
                          onChange={() => toggleOne(ev.id)}
                          aria-label={`选择证据 ${ev.id}`}
                          data-testid={`select-evidence-${ev.id}`}
                        />
                      </td>
                    ) : null}
                    <td className="max-w-[180px] px-3 py-2">
                      <div className="truncate font-medium text-gray-800" title={ev.asset_filename ?? undefined}>
                        {ev.asset_filename ?? `素材 #${ev.asset_id}`}
                      </div>
                      {ev.product_name ? (
                        <div className="truncate text-xs text-gray-400">{ev.product_name}</div>
                      ) : null}
                    </td>
                    <td className="max-w-[240px] px-3 py-2">
                      <div className="truncate text-xs text-gray-600" title={ev.location_relative_path ?? undefined}>
                        {ev.location_relative_path ?? "—"}
                      </div>
                      <div className="text-[10px] text-gray-400">
                        {ev.source_root_name ?? ""}（{locationStatusLabel(ev.location_status)}）
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <code className="rounded bg-gray-100 px-1 py-0.5 text-xs">{ev.matched_component}</code>
                      <div className="text-[10px] text-gray-400">
                        {MATCH_TARGET_LABELS[ev.matched_target] ?? ev.matched_target}
                      </div>
                    </td>
                    <td className="max-w-[140px] truncate px-3 py-2 text-xs text-gray-500" title={ev.rule_name ?? undefined}>
                      {ev.rule_name ?? "（规则已删除）"}
                    </td>
                    <td className="px-3 py-2 text-gray-600">{ev.observation_count}</td>
                    <td className="px-3 py-2 text-xs text-gray-500">
                      {/* 对照列：正式 confirmed 次数只来自成片血缘，证据审核绝不改变它 */}
                      {ev.confirmed_usage_count > 0
                        ? `已确认 ${ev.confirmed_usage_count} 次`
                        : ev.has_final_video_usage
                          ? "有候选引用"
                          : "无正式记录"}
                    </td>
                    <td className="px-3 py-2">
                      <ReviewStatusChip status={ev.review_status} />
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1.5">
                        {ev.review_status === "pending" ? (
                          <>
                            <Button
                              size="sm"
                              disabled={action.isPending}
                              onClick={() => action.mutate({ id: ev.id, action: "accept" })}
                              data-testid={`accept-evidence-${ev.id}`}
                            >
                              接受
                            </Button>
                            <Button
                              size="sm"
                              variant="secondary"
                              disabled={action.isPending}
                              onClick={() => action.mutate({ id: ev.id, action: "reject" })}
                              data-testid={`reject-evidence-${ev.id}`}
                            >
                              驳回
                            </Button>
                            <Button
                              size="sm"
                              variant="secondary"
                              disabled={action.isPending}
                              onClick={() => action.mutate({ id: ev.id, action: "mark-conflict" })}
                            >
                              标冲突
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button
                              size="sm"
                              variant="secondary"
                              disabled={action.isPending}
                              onClick={() => action.mutate({ id: ev.id, action: "reset" })}
                              data-testid={`reset-evidence-${ev.id}`}
                            >
                              重置待审
                            </Button>
                            {ev.review_status !== "conflict" ? (
                              <Button
                                size="sm"
                                variant="secondary"
                                disabled={action.isPending}
                                onClick={() => action.mutate({ id: ev.id, action: "mark-conflict" })}
                              >
                                标冲突
                              </Button>
                            ) : null}
                          </>
                        )}
                        <Button size="sm" variant="ghost" onClick={() => setEventsFor(ev)}>
                          历史
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={query.data?.total ?? 0}
            onPageChange={(p) => {
              setPage(p);
              setSelected([]);
            }}
          />
        </>
      )}

      {action.isError ? (
        <p className="mt-2 text-xs text-red-600">
          {action.error instanceof ApiError ? action.error.message : "操作失败"}
        </p>
      ) : null}

      {eventsFor ? (
        <EvidenceEventsDialog evidence={eventsFor} onClose={() => setEventsFor(null)} />
      ) : null}
    </section>
  );
}

const EVENT_ACTION_LABELS: Record<string, string> = {
  detected: "首次检测",
  observed_again: "再次观察",
  accepted: "接受",
  rejected: "驳回",
  marked_conflict: "标记冲突",
  reset_to_pending: "重置待审",
  bulk_accepted: "批量接受",
  bulk_rejected: "批量驳回",
};

function EvidenceEventsDialog({
  evidence,
  onClose,
}: {
  evidence: LegacyEvidence;
  onClose: () => void;
}) {
  const events = useLegacyEvidenceEvents(evidence.id);
  return (
    <Dialog open title={`证据 #${evidence.id} 审核历史`} onClose={onClose}>
      {events.isLoading ? (
        <Loading rows={3} />
      ) : events.isError ? (
        <ErrorState message={(events.error as Error).message} onRetry={() => void events.refetch()} />
      ) : (
        <ul className="flex flex-col gap-2" data-testid="evidence-events-list">
          {(events.data?.items ?? []).map((e) => (
            <li key={e.id} className="rounded border border-gray-100 px-3 py-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-medium text-gray-700">
                  {EVENT_ACTION_LABELS[e.action] ?? e.action}
                </span>
                <span className="text-gray-400">{formatDateTime(e.created_at)}</span>
              </div>
              <div className="mt-0.5 text-gray-500">
                {e.before_status ?? "—"} → {e.after_status ?? "—"}
                {e.actor_label ? `，操作人：${e.actor_label}` : ""}
              </div>
              {e.note ? <div className="mt-0.5 text-gray-500">备注:{e.note}</div> : null}
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}
