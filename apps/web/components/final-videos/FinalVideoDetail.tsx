"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { EvidenceBadge, FinalVideoStatusBadge, UsageStatusBadge } from "@/components/StatusBadge";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { TopNav } from "@/components/TopNav";
import { Button, ConfirmDialog, Dialog, Field } from "@/components/ui";
import { MediaThumb } from "@/components/ui/MediaThumb";
import { ApiError, assetPosterUrl, shotThumbnailUrl } from "@/lib/api";
import {
  useAssets,
  useCreateUsage,
  useFinalVideoLifecycle,
  useFinalVideoLineage,
  useOccurrenceMutation,
  useProposeFromProject,
  useShots,
  useUsageAction,
  useUsageEvents,
} from "@/lib/hooks";
import { formatDateTime, formatDuration } from "@/lib/format";
import type {
  ProposeFromProjectResult,
  UsageOccurrence,
  UsageWithOccurrences,
} from "@/lib/types";

const fmtMs = (ms: number) => formatDuration(ms / 1000);

export function FinalVideoDetail({ finalVideoId }: { finalVideoId: number }) {
  const lineage = useFinalVideoLineage(finalVideoId);
  const lifecycle = useFinalVideoLifecycle(finalVideoId);
  const propose = useProposeFromProject(finalVideoId);
  const action = useUsageAction();

  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [proposeResult, setProposeResult] = useState<ProposeFromProjectResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  if (lineage.isLoading) {
    return (
      <Shell>
        <Loading rows={6} />
      </Shell>
    );
  }
  if (lineage.isError || !lineage.data) {
    return (
      <Shell>
        <ErrorState
          message={lineage.error instanceof Error ? lineage.error.message : "加载失败"}
          onRetry={() => void lineage.refetch()}
        />
      </Shell>
    );
  }

  const { final_video: fv, usages } = lineage.data;
  const archived = fv.status === "archived";
  const proposedIds = usages.filter((u) => u.status === "proposed").map((u) => u.id);
  const selectedProposed = proposedIds.filter((id) => selectedIds.has(id));
  const selectedConfirmed = usages
    .filter((u) => u.status === "confirmed" && selectedIds.has(u.id))
    .map((u) => u.id);

  const runAction = (
    usageId: number,
    kind: "confirm" | "reject" | "revoke" | "restore-proposal",
  ) => {
    setActionError(null);
    action.mutate(
      { usageId, action: kind },
      {
        onError: (err) =>
          setActionError(err instanceof ApiError ? err.message : "操作失败"),
      },
    );
  };

  const runBatch = async (ids: number[], kind: "confirm" | "reject") => {
    setActionError(null);
    for (const id of ids) {
      try {
        await action.mutateAsync({ usageId: id, action: kind });
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "批量操作部分失败");
      }
    }
    setSelectedIds(new Set());
  };

  return (
    <Shell>
      {/* ===== 头部 ===== */}
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Link href="/final-videos" className="text-sm text-gray-400 hover:text-gray-600">
              ← 成片列表
            </Link>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold text-gray-800" data-testid="fv-title">
              {fv.title}
            </h1>
            <FinalVideoStatusBadge status={fv.status} />
            {fv.version_label ? (
              <span className="text-xs text-gray-400">{fv.version_label}</span>
            ) : null}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {archived ? (
            <Button
              variant="secondary"
              onClick={() => lifecycle.mutate("restore")}
              data-testid="fv-restore"
            >
              恢复成片
            </Button>
          ) : (
            <Button variant="secondary" onClick={() => setConfirmArchive(true)} data-testid="fv-archive">
              归档
            </Button>
          )}
        </div>
      </div>

      {/* ===== 成片信息 ===== */}
      <div className="mb-4 grid gap-4 md:grid-cols-[240px,1fr]">
        <MediaThumb
          src={fv.asset_has_poster ? assetPosterUrl(fv.asset_id) : null}
          alt={fv.title}
          ratio="video"
        />
        <div className="rounded-lg border border-gray-200 bg-white p-3 text-sm">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-gray-600 md:grid-cols-3">
            <InfoItem label="成片文件" value={fv.asset_filename ?? "—"} />
            <InfoItem
              label="成片时长"
              value={fv.asset_duration != null ? formatDuration(fv.asset_duration) : "未知"}
            />
            <InfoItem label="绑定项目" value={fv.project_name ?? "未绑定"} />
            <InfoItem label="绑定脚本" value={fv.script_project_name ?? "未绑定"} />
            <InfoItem
              label="完成时间"
              value={fv.completed_at ? formatDateTime(fv.completed_at) : "—"}
            />
            <InfoItem label="登记时间" value={formatDateTime(fv.created_at)} />
          </dl>
          {fv.description ? (
            <p className="mt-2 border-t border-gray-100 pt-2 text-xs text-gray-500">
              {fv.description}
            </p>
          ) : null}
        </div>
      </div>

      {/* ===== 血缘统计与说明 ===== */}
      <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        项目中已选择或锁定的镜头只会生成<b>候选引用（proposed）</b>；
        <b>人工确认（confirmed）后才计入正式使用次数</b>。同一镜头在本成片内出现多次仍只计 1
        次，多个出现位置请记录为 occurrence。
      </div>

      {/* ===== 工具栏 ===== */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => setShowAdd(true)} disabled={archived} data-testid="fv-add-shot">
          + 手工添加镜头
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={archived || propose.isPending}
          onClick={() =>
            propose.mutate(undefined, {
              onSuccess: setProposeResult,
              onError: (err) =>
                setActionError(err instanceof ApiError ? err.message : "生成候选失败"),
            })
          }
          data-testid="fv-propose"
        >
          {propose.isPending ? "生成中…" : "从项目生成候选"}
        </Button>
        <span className="mx-1 h-4 w-px bg-gray-200" />
        <Button
          size="sm"
          variant="secondary"
          disabled={archived || selectedProposed.length === 0 || action.isPending}
          onClick={() => void runBatch(selectedProposed, "confirm")}
          data-testid="fv-batch-confirm"
        >
          批量确认（{selectedProposed.length}）
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={archived || selectedProposed.length === 0 || action.isPending}
          onClick={() => void runBatch(selectedProposed, "reject")}
          data-testid="fv-batch-reject"
        >
          批量驳回（{selectedProposed.length}）
        </Button>
        {selectedConfirmed.length > 0 ? (
          <span className="text-xs text-gray-400">
            已选 {selectedConfirmed.length} 条已确认引用（撤销请逐条操作）
          </span>
        ) : null}
        <span className="ml-auto text-xs text-gray-500" data-testid="fv-usage-stats">
          共 {fv.usage_stats.source_shot_count} 条引用 · 已确认{" "}
          <b className="text-emerald-700">{fv.usage_stats.confirmed_count}</b> · 候选{" "}
          {fv.usage_stats.proposed_count} · 已驳回 {fv.usage_stats.rejected_count} · 已撤销{" "}
          {fv.usage_stats.revoked_count}
          {" · "}
          <Link
            href="/usage-review"
            className="text-brand hover:underline"
            data-testid="fv-open-review-center"
          >
            进入统一审核中心 →
          </Link>
        </span>
      </div>

      {proposeResult ? (
        <div
          className="mb-3 rounded border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800"
          data-testid="propose-result"
        >
          从项目生成候选完成：新增 {proposeResult.created} · 已存在 {proposeResult.existing} ·
          跳过不可用 {proposeResult.skipped_unavailable} · 冲突 {proposeResult.conflicts}（扫描段落{" "}
          {proposeResult.segments_scanned}）
          <button className="ml-2 underline" onClick={() => setProposeResult(null)}>
            关闭
          </button>
        </div>
      ) : null}
      {actionError ? (
        <div className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700" data-testid="usage-action-error">
          {actionError}
        </div>
      ) : null}

      {/* ===== 血缘表 ===== */}
      {usages.length === 0 ? (
        <Empty
          title="还没有使用血缘"
          description="手工添加来源镜头，或在绑定项目后从项目已选择/锁定的镜头生成候选。"
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="w-full min-w-[980px] text-sm" data-testid="usage-table">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                <th className="w-8 px-2 py-2" />
                <th className="px-2 py-2 font-medium">来源镜头</th>
                <th className="px-2 py-2 font-medium">来源素材</th>
                <th className="px-2 py-2 font-medium">原始时间段</th>
                <th className="px-2 py-2 font-medium">出现</th>
                <th className="px-2 py-2 font-medium">产品</th>
                <th className="px-2 py-2 font-medium">证据来源</th>
                <th className="px-2 py-2 font-medium">状态</th>
                <th className="px-2 py-2 font-medium">置信度</th>
                <th className="px-2 py-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {usages.map((u) => (
                <UsageRow
                  key={u.id}
                  usage={u}
                  archived={archived}
                  selected={selectedIds.has(u.id)}
                  expanded={expandedId === u.id}
                  onToggleSelect={() =>
                    setSelectedIds((prev) => {
                      const next = new Set(prev);
                      if (next.has(u.id)) next.delete(u.id);
                      else next.add(u.id);
                      return next;
                    })
                  }
                  onToggleExpand={() => setExpandedId((cur) => (cur === u.id ? null : u.id))}
                  onAction={runAction}
                  actionPending={action.isPending}
                  finalDurationMs={
                    fv.asset_duration != null ? Math.ceil(fv.asset_duration * 1000) : null
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAdd ? (
        <AddShotDialog
          finalVideoId={finalVideoId}
          finalAssetId={fv.asset_id}
          existingShotIds={new Set(usages.map((u) => u.source_shot_id))}
          onClose={() => setShowAdd(false)}
        />
      ) : null}
      <ConfirmDialog
        open={confirmArchive}
        title="归档成片"
        message="归档后成片进入只读状态：历史已确认引用继续计入使用次数，只有明确撤销才会减少。不会删除任何媒体文件。"
        confirmLabel="归档"
        onConfirm={() => {
          lifecycle.mutate("archive");
          setConfirmArchive(false);
        }}
        onClose={() => setConfirmArchive(false)}
      />
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="final-videos" />
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-gray-400">{label}</dt>
      <dd className="truncate text-gray-700" title={value}>
        {value}
      </dd>
    </div>
  );
}

// ============================ 血缘行 ============================

function UsageRow({
  usage: u,
  archived,
  selected,
  expanded,
  onToggleSelect,
  onToggleExpand,
  onAction,
  actionPending,
  finalDurationMs,
}: {
  usage: UsageWithOccurrences;
  archived: boolean;
  selected: boolean;
  expanded: boolean;
  onToggleSelect: () => void;
  onToggleExpand: () => void;
  onAction: (usageId: number, kind: "confirm" | "reject" | "revoke" | "restore-proposal") => void;
  actionPending: boolean;
  finalDurationMs: number | null;
}) {
  const shot = u.shot;
  return (
    <>
      <tr data-testid="usage-row" className="border-b border-gray-50 last:border-0 hover:bg-gray-50">
        <td className="px-2 py-2 align-top">
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggleSelect}
            aria-label={`选择引用 ${u.id}`}
            data-testid={`usage-select-${u.id}`}
          />
        </td>
        <td className="px-2 py-2">
          <div className="flex items-center gap-2">
            <div className="w-20 shrink-0">
              <MediaThumb
                src={shot?.has_thumbnail ? shotThumbnailUrl(shot.id) : null}
                alt={`镜头 ${shot?.sequence_no ?? u.source_shot_id}`}
                ratio="video"
              />
            </div>
            <div className="min-w-0 text-xs">
              <Link
                href={`/shots?shot=${u.source_shot_id}`}
                className="font-medium text-brand hover:underline"
              >
                镜头 #{shot?.sequence_no ?? u.source_shot_id}
              </Link>
              <div className="text-gray-400">id {u.source_shot_id}</div>
            </div>
          </div>
        </td>
        <td className="max-w-[150px] truncate px-2 py-2 text-xs text-gray-600" title={u.source_asset_filename ?? undefined}>
          {u.source_asset_filename ?? `asset ${u.source_asset_id}`}
        </td>
        <td className="px-2 py-2 text-xs text-gray-600">
          {shot ? `${formatDuration(shot.start_time)} – ${formatDuration(shot.end_time)}` : "—"}
        </td>
        <td className="px-2 py-2 text-xs">
          <button
            type="button"
            onClick={onToggleExpand}
            className="text-brand hover:underline"
            data-testid={`usage-occ-toggle-${u.id}`}
          >
            {u.occurrence_count} 段{expanded ? " ▴" : " ▾"}
          </button>
        </td>
        <td className="max-w-[110px] truncate px-2 py-2 text-xs text-gray-600">
          {u.product_name ?? "—"}
        </td>
        <td className="px-2 py-2">
          <EvidenceBadge method={u.evidence_method} />
        </td>
        <td className="px-2 py-2">
          <UsageStatusBadge status={u.status} />
        </td>
        <td className="px-2 py-2 text-xs text-gray-600">
          {u.confidence != null ? u.confidence.toFixed(2) : "—"}
        </td>
        <td className="px-2 py-2">
          <div className="flex flex-wrap gap-1">
            {u.status === "proposed" ? (
              <>
                <Button
                  size="sm"
                  disabled={archived || actionPending}
                  onClick={() => onAction(u.id, "confirm")}
                  data-testid={`usage-confirm-${u.id}`}
                >
                  确认
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={archived || actionPending}
                  onClick={() => onAction(u.id, "reject")}
                  data-testid={`usage-reject-${u.id}`}
                >
                  驳回
                </Button>
              </>
            ) : null}
            {u.status === "confirmed" ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={actionPending}
                onClick={() => onAction(u.id, "revoke")}
                data-testid={`usage-revoke-${u.id}`}
              >
                撤销
              </Button>
            ) : null}
            {u.status === "rejected" || u.status === "revoked" ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={archived || actionPending}
                onClick={() => onAction(u.id, "restore-proposal")}
                data-testid={`usage-restore-${u.id}`}
              >
                恢复候选
              </Button>
            ) : null}
          </div>
        </td>
      </tr>
      {expanded ? (
        <tr className="border-b border-gray-50 bg-gray-50/60">
          <td />
          <td colSpan={9} className="px-2 pb-3 pt-1">
            <OccurrencePanel usage={u} archived={archived} finalDurationMs={finalDurationMs} />
            <EventTimeline usageId={u.id} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

// ============================ occurrence 编辑 ============================

function OccurrencePanel({
  usage,
  archived,
  finalDurationMs,
}: {
  usage: UsageWithOccurrences;
  archived: boolean;
  finalDurationMs: number | null;
}) {
  const mutation = useOccurrenceMutation();
  const [error, setError] = useState<string | null>(null);
  const shot = usage.shot;
  const shotStartMs = shot ? Math.floor(shot.start_time * 1000) : 0;
  const shotEndMs = shot ? Math.ceil(shot.end_time * 1000) : 0;

  const [form, setForm] = useState({
    source_start_ms: shotStartMs,
    source_end_ms: shotEndMs,
    final_start_ms: 0,
    final_end_ms: Math.max(shotEndMs - shotStartMs, 1),
  });

  const add = () => {
    setError(null);
    mutation.mutate(
      { kind: "create", usageId: usage.id, payload: form },
      {
        onError: (err) => setError(err instanceof ApiError ? err.message : "添加失败"),
      },
    );
  };

  return (
    <div className="rounded border border-gray-200 bg-white p-2 text-xs">
      <div className="mb-1 font-medium text-gray-700">
        出现时间段（多段不重复计数；源侧须在镜头 {fmtMs(shotStartMs)} – {fmtMs(shotEndMs)} 范围内
        {finalDurationMs != null ? `，成片侧 ≤ ${fmtMs(finalDurationMs)}` : ""}）
      </div>
      {usage.occurrences.length ? (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-gray-400">
              <th className="py-1 font-normal">#</th>
              <th className="py-1 font-normal">原素材时间段</th>
              <th className="py-1 font-normal">成片时间段</th>
              <th className="py-1 font-normal" />
            </tr>
          </thead>
          <tbody>
            {usage.occurrences.map((o) => (
              <OccurrenceRow key={o.id} occ={o} archived={archived} onError={setError} />
            ))}
          </tbody>
        </table>
      ) : (
        <p className="py-1 text-gray-400">尚未记录出现时间段。</p>
      )}
      {!archived ? (
        <div className="mt-2 flex flex-wrap items-end gap-2" data-testid={`occ-add-form-${usage.id}`}>
          <MsInput
            label="源开始"
            value={form.source_start_ms}
            onChange={(v) => setForm((f) => ({ ...f, source_start_ms: v }))}
          />
          <MsInput
            label="源结束"
            value={form.source_end_ms}
            onChange={(v) => setForm((f) => ({ ...f, source_end_ms: v }))}
          />
          <MsInput
            label="成片开始"
            value={form.final_start_ms}
            onChange={(v) => setForm((f) => ({ ...f, final_start_ms: v }))}
          />
          <MsInput
            label="成片结束"
            value={form.final_end_ms}
            onChange={(v) => setForm((f) => ({ ...f, final_end_ms: v }))}
          />
          <Button size="sm" variant="secondary" onClick={add} disabled={mutation.isPending} data-testid={`occ-add-${usage.id}`}>
            + 添加时间段
          </Button>
        </div>
      ) : null}
      {error ? (
        <p className="mt-1 text-red-600" data-testid="occ-error">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function OccurrenceRow({
  occ,
  archived,
  onError,
}: {
  occ: UsageOccurrence;
  archived: boolean;
  onError: (msg: string | null) => void;
}) {
  const mutation = useOccurrenceMutation();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    source_start_ms: occ.source_start_ms,
    source_end_ms: occ.source_end_ms,
    final_start_ms: occ.final_start_ms,
    final_end_ms: occ.final_end_ms,
  });

  if (editing) {
    return (
      <tr>
        <td className="py-1 text-gray-500">{occ.occurrence_index + 1}</td>
        <td colSpan={2} className="py-1">
          <div className="flex flex-wrap items-end gap-2">
            <MsInput label="源开始" value={form.source_start_ms} onChange={(v) => setForm((f) => ({ ...f, source_start_ms: v }))} />
            <MsInput label="源结束" value={form.source_end_ms} onChange={(v) => setForm((f) => ({ ...f, source_end_ms: v }))} />
            <MsInput label="成片开始" value={form.final_start_ms} onChange={(v) => setForm((f) => ({ ...f, final_start_ms: v }))} />
            <MsInput label="成片结束" value={form.final_end_ms} onChange={(v) => setForm((f) => ({ ...f, final_end_ms: v }))} />
          </div>
        </td>
        <td className="py-1 text-right">
          <div className="flex justify-end gap-1">
            <Button
              size="sm"
              onClick={() => {
                onError(null);
                mutation.mutate(
                  { kind: "update", occurrenceId: occ.id, payload: form },
                  {
                    onSuccess: () => setEditing(false),
                    onError: (err) =>
                      onError(err instanceof ApiError ? err.message : "保存失败"),
                  },
                );
              }}
              disabled={mutation.isPending}
            >
              保存
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setEditing(false)}>
              取消
            </Button>
          </div>
        </td>
      </tr>
    );
  }

  return (
    <tr data-testid={`occ-row-${occ.id}`}>
      <td className="py-1 text-gray-500">{occ.occurrence_index + 1}</td>
      <td className="py-1 text-gray-700">
        {fmtMs(occ.source_start_ms)} – {fmtMs(occ.source_end_ms)}
      </td>
      <td className="py-1 text-gray-700">
        {fmtMs(occ.final_start_ms)} – {fmtMs(occ.final_end_ms)}
      </td>
      <td className="py-1 text-right">
        {!archived ? (
          <div className="flex justify-end gap-1">
            <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
              编辑
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                onError(null);
                mutation.mutate(
                  { kind: "delete", occurrenceId: occ.id },
                  {
                    onError: (err) =>
                      onError(err instanceof ApiError ? err.message : "删除失败"),
                  },
                );
              }}
              disabled={mutation.isPending}
            >
              删除
            </Button>
          </div>
        ) : null}
      </td>
    </tr>
  );
}

function MsInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-0.5 text-[11px] text-gray-500">
      {label}（ms）
      <input
        type="number"
        min={0}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-24 rounded border border-gray-300 px-1.5 py-1 text-xs"
      />
    </label>
  );
}

// ============================ 事件时间线 ============================

const EVENT_LABEL: Record<string, string> = {
  create_proposal: "生成候选",
  manual_add: "人工添加",
  confirm: "确认使用",
  reject: "驳回",
  revoke: "撤销",
  restore_proposal: "恢复候选",
  occurrence_add: "新增时间段",
  occurrence_update: "修改时间段",
  occurrence_delete: "删除时间段",
};

function EventTimeline({ usageId }: { usageId: number }) {
  const events = useUsageEvents(usageId);
  if (events.isLoading) return <p className="mt-2 text-xs text-gray-400">加载事件…</p>;
  const items = events.data?.items ?? [];
  if (!items.length) return null;
  return (
    <div className="mt-2 rounded border border-gray-200 bg-white p-2 text-xs" data-testid={`usage-events-${usageId}`}>
      <div className="mb-1 font-medium text-gray-700">使用事件（append-only）</div>
      <ul className="space-y-0.5">
        {items.map((e) => (
          <li key={e.id} className="flex flex-wrap items-center gap-1 text-gray-600">
            <span className="text-gray-400">{formatDateTime(e.created_at)}</span>
            <span className="font-medium">{EVENT_LABEL[e.action] ?? e.action}</span>
            {e.before_status || e.after_status ? (
              <span className="text-gray-400">
                {e.before_status ?? "—"} → {e.after_status ?? "—"}
              </span>
            ) : null}
            {e.actor_label ? <span className="text-gray-400">by {e.actor_label}</span> : null}
            {e.note ? <span className="text-gray-400">（{e.note}）</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ============================ 手工添加镜头 ============================

function AddShotDialog({
  finalVideoId,
  finalAssetId,
  existingShotIds,
  onClose,
}: {
  finalVideoId: number;
  finalAssetId: number;
  existingShotIds: Set<number>;
  onClose: () => void;
}) {
  const [assetQ, setAssetQ] = useState("");
  const [assetId, setAssetId] = useState<number | null>(null);
  const create = useCreateUsage(finalVideoId);
  const [error, setError] = useState<string | null>(null);

  const assets = useAssets({ page: 1, page_size: 20, q: assetQ.trim() || undefined });
  const shots = useShots(
    { asset_id: assetId ?? undefined, page: 1, page_size: 60 },
    assetId != null,
  );
  const selectableAssets = useMemo(
    () => (assets.data?.items ?? []).filter((a) => a.id !== finalAssetId),
    [assets.data, finalAssetId],
  );

  const add = (shotId: number) => {
    setError(null);
    create.mutate(
      { source_shot_id: shotId },
      { onError: (err) => setError(err instanceof ApiError ? err.message : "添加失败") },
    );
  };

  return (
    <Dialog open title="手工添加来源镜头（先加为候选，确认后才计数）" onClose={onClose} widthClass="max-w-2xl">
      <div className="flex flex-col gap-3" data-testid="add-shot-dialog">
        <Field label="选择来源素材（成片文件本身已排除）">
          <input
            value={assetQ}
            onChange={(e) => {
              setAssetQ(e.target.value);
              setAssetId(null);
            }}
            placeholder="搜索素材文件名…"
            data-testid="add-shot-asset-search"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none"
          />
          <div className="mt-1 max-h-32 overflow-y-auto rounded border border-gray-200">
            {selectableAssets.length ? (
              selectableAssets.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => setAssetId(a.id)}
                  data-testid={`add-shot-asset-${a.id}`}
                  className={`block w-full truncate px-2 py-1.5 text-left text-xs ${
                    assetId === a.id ? "bg-brand/10 font-medium text-brand" : "hover:bg-gray-50"
                  }`}
                >
                  #{a.id} {a.filename}（{a.shot_count ?? 0} 镜头）
                </button>
              ))
            ) : (
              <div className="px-2 py-2 text-xs text-gray-400">没有匹配素材</div>
            )}
          </div>
        </Field>
        {assetId != null ? (
          <div className="max-h-72 overflow-y-auto rounded border border-gray-200 p-2">
            {shots.isLoading ? (
              <Loading rows={2} />
            ) : shots.data?.items.length ? (
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                {shots.data.items.map((s) => {
                  const added = existingShotIds.has(s.id);
                  return (
                    <button
                      key={s.id}
                      type="button"
                      disabled={added || create.isPending}
                      onClick={() => add(s.id)}
                      data-testid={`add-shot-${s.id}`}
                      className={`rounded border p-1 text-left text-[11px] ${
                        added
                          ? "cursor-not-allowed border-gray-100 opacity-50"
                          : "border-gray-200 hover:border-brand"
                      }`}
                      title={added ? "已在血缘中" : "添加为候选引用"}
                    >
                      <MediaThumb
                        src={s.has_thumbnail ? shotThumbnailUrl(s.id) : null}
                        alt={`镜头 ${s.sequence_no}`}
                        ratio="video"
                      />
                      <div className="mt-0.5 truncate text-gray-600">
                        #{s.sequence_no} · {formatDuration(s.start_time)}–{formatDuration(s.end_time)}
                        {added ? "（已添加）" : ""}
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="py-2 text-xs text-gray-400">该素材没有可用镜头</p>
            )}
          </div>
        ) : (
          <p className="text-xs text-gray-400">选择素材后展示其镜头。</p>
        )}
        {error ? (
          <p className="text-xs text-red-600" data-testid="add-shot-error">
            {error}
          </p>
        ) : null}
        <div className="flex justify-end">
          <Button variant="secondary" onClick={onClose}>
            完成
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
