"use client";

import { useMemo, useState } from "react";

import { Pagination } from "@/components/Pagination";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { Button, ConfirmDialog } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useUsageReviewBulk, useUsageReviewItems } from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";
import type {
  ReviewBulkResult,
  ReviewItem,
  ReviewItemType,
  ReviewListQuery,
} from "@/lib/types";

import { ClueLineageDialog } from "./ClueLineageDialog";
import { ReviewDetailDrawer } from "./ReviewDetailDrawer";
import {
  ACTION_LABELS,
  ItemTypeChip,
  REVIEW_STATUS_LABELS,
  StrengthChip,
} from "./reviewShared";

const PAGE_SIZE = 20;

type SelKey = string; // `${item_type}:${item_id}`

function keyOf(it: { item_type: ReviewItemType; item_id: number }): SelKey {
  return `${it.item_type}:${it.item_id}`;
}

/** 统一审核列表（filters 由外部 Tab 决定；批量为 typed——混合类型选择禁用并说明）。 */
export function ReviewTable({
  filters,
  allowBulk = true,
  testId = "review-table",
}: {
  filters: Omit<ReviewListQuery, "page" | "page_size">;
  allowBulk?: boolean;
  testId?: string;
}) {
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Map<SelKey, ReviewItem>>(new Map());
  const [detail, setDetail] = useState<ReviewItem | null>(null);
  const [clue, setClue] = useState<ReviewItem | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<ReviewBulkResult | null>(null);

  const query = useUsageReviewItems({ ...filters, page, page_size: PAGE_SIZE });
  const bulk = useUsageReviewBulk();
  const items = query.data?.items ?? [];

  const selectedItems = useMemo(() => [...selected.values()], [selected]);
  const selectedTypes = useMemo(
    () => new Set(selectedItems.map((i) => i.item_type)),
    [selectedItems],
  );
  const mixed = selectedTypes.size > 1;
  const soleType: ReviewItemType | null =
    selectedTypes.size === 1 ? selectedItems[0].item_type : null;

  // 所选条目共同可用的动作（typed；由状态机导出的 available_actions 求交集）
  const commonActions = useMemo(() => {
    if (mixed || selectedItems.length === 0) return [] as string[];
    return selectedItems
      .map((i) => new Set(i.available_actions))
      .reduce<string[]>(
        (acc, set) => acc.filter((a) => set.has(a)),
        [...(selectedItems[0]?.available_actions ?? [])],
      );
  }, [selectedItems, mixed]);

  const toggle = (it: ReviewItem) => {
    setSelected((prev) => {
      const next = new Map(prev);
      const k = keyOf(it);
      if (next.has(k)) next.delete(k);
      else next.set(k, it);
      return next;
    });
    setLastResult(null);
  };
  const selectPage = () => {
    setSelected((prev) => {
      const next = new Map(prev);
      items.forEach((it) => next.set(keyOf(it), it));
      return next;
    });
  };
  const clearSelection = () => setSelected(new Map());

  const runBulk = (action: string) => {
    if (soleType == null) return;
    bulk.mutate(
      {
        items: selectedItems.map((i) => ({
          item_type: i.item_type,
          item_id: i.item_id,
        })),
        action,
      },
      {
        onSuccess: (res) => {
          setLastResult(res);
          clearSelection();
        },
      },
    );
    setPendingAction(null);
  };

  const singleAction = (it: ReviewItem, action: string) => {
    bulk.mutate(
      { items: [{ item_type: it.item_type, item_id: it.item_id }], action },
      { onSuccess: setLastResult },
    );
  };

  return (
    <div data-testid={testId}>
      {allowBulk ? (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Button size="sm" variant="secondary" onClick={selectPage} data-testid="select-page">
            选择当前页
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={clearSelection}
            disabled={selected.size === 0}
            data-testid="clear-selection"
          >
            清除选择（{selected.size}）
          </Button>
          {mixed ? (
            <span className="text-xs text-amber-800" data-testid="mixed-type-warning">
              已同时选择正式血缘与历史证据——两类记录的动作不同，请分开批量处理。
            </span>
          ) : (
            commonActions.map((a) => (
              <Button
                key={a}
                size="sm"
                disabled={bulk.isPending || selected.size === 0}
                onClick={() => setPendingAction(a)}
                data-testid={`bulk-${a}`}
              >
                批量{ACTION_LABELS[a] ?? a}（{selected.size}）
              </Button>
            ))
          )}
          {bulk.isError ? (
            <span className="text-xs text-red-600" data-testid="bulk-error">
              {bulk.error instanceof ApiError ? bulk.error.message : "批量操作失败"}
            </span>
          ) : null}
          {lastResult ? (
            <span className="text-xs text-gray-600" data-testid="bulk-result">
              成功 {lastResult.succeeded}，跳过 {lastResult.skipped}，失败{" "}
              {lastResult.failed}
            </span>
          ) : null}
        </div>
      ) : null}

      {query.isLoading ? (
        <Loading rows={5} />
      ) : query.isError ? (
        <ErrorState
          message={(query.error as Error).message}
          onRetry={() => void query.refetch()}
        />
      ) : items.length === 0 ? (
        <Empty title="没有符合条件的记录" description="调整筛选或切换分组查看。" />
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="w-full min-w-[1080px] text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                  {allowBulk ? <th className="w-8 px-3 py-2" /> : null}
                  <th className="px-3 py-2 font-medium">类型</th>
                  <th className="px-3 py-2 font-medium">可信等级</th>
                  <th className="px-3 py-2 font-medium">素材</th>
                  <th className="px-3 py-2 font-medium">镜头</th>
                  <th className="px-3 py-2 font-medium">成片</th>
                  <th className="px-3 py-2 font-medium">产品</th>
                  <th className="px-3 py-2 font-medium">来源</th>
                  <th className="px-3 py-2 font-medium">状态</th>
                  <th className="px-3 py-2 font-medium">创建 / 最近观察</th>
                  <th className="px-3 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr
                    key={keyOf(it)}
                    data-testid={`review-row-${it.item_type}-${it.item_id}`}
                    className="border-b border-gray-50 last:border-0 hover:bg-gray-50"
                  >
                    {allowBulk ? (
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          checked={selected.has(keyOf(it))}
                          onChange={() => toggle(it)}
                          aria-label={`选择 ${it.item_type} ${it.item_id}`}
                          data-testid={`select-${it.item_type}-${it.item_id}`}
                        />
                      </td>
                    ) : null}
                    <td className="px-3 py-2">
                      <ItemTypeChip
                        type={it.item_type}
                        confirmed={it.review_status === "confirmed"}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <StrengthChip strength={it.source_strength} />
                    </td>
                    <td
                      className="max-w-[180px] truncate px-3 py-2 text-gray-700"
                      title={it.asset_filename ?? undefined}
                    >
                      {it.asset_filename ?? (it.asset_id != null ? `#${it.asset_id}` : "—")}
                    </td>
                    <td className="px-3 py-2 text-gray-600">
                      {it.shot_id != null
                        ? `#${it.shot_sequence_no ?? it.shot_id}`
                        : "—"}
                    </td>
                    <td
                      className="max-w-[160px] truncate px-3 py-2 text-gray-600"
                      title={it.final_video_title ?? undefined}
                    >
                      {it.final_video_id != null ? it.final_video_title ?? `#${it.final_video_id}` : "—"}
                    </td>
                    <td className="max-w-[120px] truncate px-3 py-2 text-gray-600">
                      {it.product ?? "—"}
                    </td>
                    <td
                      className="max-w-[160px] truncate px-3 py-2 text-xs text-gray-500"
                      title={it.source_label ?? undefined}
                    >
                      {it.source_label ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600">
                      {REVIEW_STATUS_LABELS[it.review_status] ?? it.review_status}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">
                      {formatDateTime(it.created_at)}
                      {it.last_observed_at ? (
                        <div className="text-[10px] text-gray-400">
                          观察 {formatDateTime(it.last_observed_at)}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1.5">
                        {it.available_actions.slice(0, 2).map((a) => (
                          <Button
                            key={a}
                            size="sm"
                            variant={a === "confirm" || a === "accept" ? "primary" : "secondary"}
                            disabled={bulk.isPending}
                            onClick={() => singleAction(it, a)}
                            data-testid={`action-${a}-${it.item_type}-${it.item_id}`}
                          >
                            {ACTION_LABELS[a] ?? a}
                          </Button>
                        ))}
                        {it.item_type === "legacy_usage_evidence" ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setClue(it)}
                            data-testid={`clue-${it.item_id}`}
                          >
                            建立正式成片血缘
                          </Button>
                        ) : null}
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setDetail(it)}
                          data-testid={`detail-${it.item_type}-${it.item_id}`}
                        >
                          详情
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
            }}
          />
        </>
      )}

      {pendingAction ? (
        <ConfirmDialog
          open
          title={`批量${ACTION_LABELS[pendingAction] ?? pendingAction}`}
          message={`将对 ${selected.size} 条${
            soleType === "final_video_usage" ? "正式血缘" : "历史证据"
          }记录执行「${ACTION_LABELS[pendingAction] ?? pendingAction}」。状态不符的条目会被跳过并逐条回报。`}
          confirmLabel="确认执行"
          onConfirm={() => runBulk(pendingAction)}
          onClose={() => setPendingAction(null)}
        />
      ) : null}
      {detail ? (
        <ReviewDetailDrawer
          itemType={detail.item_type}
          itemId={detail.item_id}
          onClose={() => setDetail(null)}
          onOpenClue={(it) => {
            setDetail(null);
            setClue(it);
          }}
        />
      ) : null}
      {clue ? <ClueLineageDialog clue={clue} onClose={() => setClue(null)} /> : null}
    </div>
  );
}
