"use client";

import { Loading } from "@/components/states/Loading";
import { ErrorState } from "@/components/states/ErrorState";
import { Button, Drawer } from "@/components/ui";
import { useUsageReviewItemDetail } from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";
import type { ReviewItem, ReviewItemType } from "@/lib/types";

import { ItemTypeChip, REVIEW_STATUS_LABELS, StrengthChip } from "./reviewShared";

const EVENT_LABELS: Record<string, string> = {
  // formal（FinalVideoUsageEvent；USAGE_EVENT_ACTIONS 白名单）
  create_proposal: "项目生成候选",
  manual_add: "人工添加候选",
  confirm: "确认",
  reject: "驳回",
  revoke: "撤销",
  restore_proposal: "恢复候选",
  occurrence_add: "新增出现时间段",
  occurrence_update: "修改出现时间段",
  occurrence_delete: "删除出现时间段",
  // legacy（LegacyUsageEvidenceEvent）
  detected: "首次检测",
  observed_again: "再次观察",
  accepted: "接受",
  marked_conflict: "标记冲突",
  reset_to_pending: "重置待审",
  bulk_accepted: "批量接受",
  bulk_rejected: "批量驳回",
};

/** 统一详情抽屉：统一头 + 原始领域数据 + 各自事件时间线（两类事件不拼成单一对象）。 */
export function ReviewDetailDrawer({
  itemType,
  itemId,
  onClose,
  onOpenClue,
}: {
  itemType: ReviewItemType;
  itemId: number;
  onClose: () => void;
  onOpenClue?: (item: ReviewItem) => void;
}) {
  const detail = useUsageReviewItemDetail(itemType, itemId);
  const data = detail.data;

  return (
    <Drawer
      open
      onClose={onClose}
      title={itemType === "final_video_usage" ? "正式血缘详情" : "历史证据详情"}
      widthClass="max-w-lg"
    >
      {detail.isLoading ? (
        <Loading rows={4} />
      ) : detail.isError ? (
        <ErrorState
          message={(detail.error as Error).message}
          onRetry={() => void detail.refetch()}
        />
      ) : data ? (
        <div className="space-y-4" data-testid="review-detail">
          <div className="flex flex-wrap items-center gap-2">
            <ItemTypeChip
              type={data.item.item_type}
              confirmed={data.item.review_status === "confirmed"}
            />
            <StrengthChip strength={data.item.source_strength} />
            <span className="text-xs text-gray-500">
              状态：{REVIEW_STATUS_LABELS[data.item.review_status] ?? data.item.review_status}
            </span>
          </div>

          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              关联对象
            </h3>
            <dl className="grid grid-cols-1 gap-1.5 text-sm">
              <div className="flex justify-between gap-2">
                <dt className="text-gray-400">素材</dt>
                <dd className="truncate text-gray-700">
                  {data.item.asset_filename ?? "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-gray-400">镜头</dt>
                <dd className="text-gray-700" data-testid="detail-shot">
                  {data.item.shot_id != null
                    ? `#${data.item.shot_sequence_no ?? data.item.shot_id}`
                    : "—（历史证据无法定位镜头）"}
                </dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-gray-400">成片</dt>
                <dd className="truncate text-gray-700" data-testid="detail-final-video">
                  {data.item.final_video_id != null
                    ? data.item.final_video_title ?? `#${data.item.final_video_id}`
                    : "—（历史证据无法定位成片）"}
                </dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-gray-400">产品</dt>
                <dd className="text-gray-700">{data.item.product ?? "—"}</dd>
              </div>
            </dl>
          </section>

          {data.formal_usage ? (
            <section data-testid="detail-formal">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                正式血缘数据
              </h3>
              <dl className="grid grid-cols-1 gap-1.5 text-xs text-gray-600">
                <div className="flex justify-between gap-2">
                  <dt className="text-gray-400">证据方式</dt>
                  <dd>{String(data.formal_usage.evidence_method ?? "—")}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-gray-400">置信度</dt>
                  <dd>
                    {data.formal_usage.confidence != null
                      ? String(data.formal_usage.confidence)
                      : "—（人工不伪造置信度）"}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-gray-400">出现次数</dt>
                  <dd>{String(data.formal_usage.occurrence_count ?? 0)}</dd>
                </div>
                {data.formal_usage.review_note ? (
                  <div className="flex justify-between gap-2">
                    <dt className="text-gray-400">备注</dt>
                    <dd className="truncate">{String(data.formal_usage.review_note)}</dd>
                  </div>
                ) : null}
              </dl>
            </section>
          ) : null}

          {data.legacy_evidence ? (
            <section data-testid="detail-legacy">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                历史证据数据
              </h3>
              <dl className="grid grid-cols-1 gap-1.5 text-xs text-gray-600">
                <div className="flex justify-between gap-2">
                  <dt className="text-gray-400">命中片段</dt>
                  <dd>
                    <code className="rounded bg-gray-100 px-1">
                      {String(data.legacy_evidence.matched_component ?? "—")}
                    </code>
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-gray-400">规则</dt>
                  <dd>
                    {String(data.legacy_evidence.rule_name ?? "已删除")} v
                    {String(data.legacy_evidence.rule_version ?? 1)}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-gray-400">观察次数</dt>
                  <dd>{String(data.legacy_evidence.observation_count ?? 1)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-gray-400">命中路径</dt>
                  <dd className="max-w-[260px] truncate">
                    {String(data.legacy_evidence.location_relative_path ?? "—")}
                  </dd>
                </div>
              </dl>
              {onOpenClue ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-2"
                  onClick={() => onOpenClue(data.item)}
                  data-testid="detail-open-clue"
                >
                  建立正式成片血缘
                </Button>
              ) : null}
            </section>
          ) : null}

          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              事件时间线
            </h3>
            <ul className="space-y-1.5" data-testid="detail-events">
              {data.events.length === 0 ? (
                <li className="text-xs text-gray-400">暂无事件</li>
              ) : (
                data.events.map((e) => (
                  <li
                    key={e.id}
                    className="rounded border border-gray-100 px-2.5 py-1.5 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-700">
                        {EVENT_LABELS[e.action] ?? e.action}
                      </span>
                      <span className="text-gray-400">{formatDateTime(e.created_at)}</span>
                    </div>
                    <div className="mt-0.5 text-gray-500">
                      {e.before_status ?? "—"} → {e.after_status ?? "—"}
                      {e.actor_label ? `，操作人：${e.actor_label}` : ""}
                    </div>
                    {e.note ? <div className="mt-0.5 text-gray-500">备注：{e.note}</div> : null}
                  </li>
                ))
              )}
            </ul>
          </section>
        </div>
      ) : null}
    </Drawer>
  );
}
