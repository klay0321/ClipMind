// 段落列表：选中（驱动右侧候选）+ 单段匹配/重匹配 + 行内编辑（乐观锁 409）+ 上下重排。
"use client";

import { useState } from "react";

import { ApiError } from "@/lib/api";
import { useMatchSegment, useReorderSegments, useUpdateSegment } from "@/lib/hooks";
import {
  durationRangeLabel,
  matchStatusLabel,
  matchStatusTone,
  structuredTerms,
} from "@/lib/script";
import type { Product, ScriptSegment, SegmentUpdateRequest } from "@/lib/types";

import { SegmentEditor } from "./SegmentEditor";

export function SegmentList({
  scriptId,
  segments,
  products,
  selectedSegmentId,
  onSelect,
}: {
  scriptId: number;
  segments: ScriptSegment[];
  products: Product[];
  selectedSegmentId: number | null;
  onSelect: (segmentId: number) => void;
}) {
  const update = useUpdateSegment(scriptId);
  const match = useMatchSegment(scriptId);
  const reorder = useReorderSegments(scriptId);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [conflictId, setConflictId] = useState<number | null>(null);
  const productName = (id: number | null) =>
    id == null ? null : (products.find((p) => p.id === id)?.name ?? `产品#${id}`);

  const onSave = (segmentId: number, req: SegmentUpdateRequest) => {
    setConflictId(null);
    update.mutate(
      { segmentId, req },
      {
        onSuccess: () => setEditingId(null),
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) setConflictId(segmentId);
        },
      },
    );
  };

  const move = (index: number, dir: -1 | 1) => {
    const target = index + dir;
    if (target < 0 || target >= segments.length || reorder.isPending) return;
    const ids = segments.map((s) => s.id);
    [ids[index], ids[target]] = [ids[target], ids[index]];
    reorder.mutate(ids);
  };

  return (
    <ul className="space-y-2" data-testid="segment-list">
      {segments.map((seg, i) => {
        const selected = seg.id === selectedSegmentId;
        const locked = seg.locked_shot_id != null;
        const terms = structuredTerms(seg.structured_requirements);
        return (
          <li
            key={seg.id}
            data-testid="segment-row"
            data-selected={selected}
            className={`rounded-lg border p-2 ${selected ? "border-brand bg-brand-light/40" : "border-gray-200 bg-white"}`}
          >
            <div className="flex items-start gap-2">
              <button
                type="button"
                onClick={() => onSelect(seg.id)}
                className="flex min-w-0 flex-1 flex-col items-start gap-1 text-left focus:outline-none focus:ring-2 focus:ring-brand"
                aria-pressed={selected}
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-white">
                    {i + 1}
                  </span>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] ${matchStatusTone(seg.match_status)}`} data-testid="seg-match-status">
                    {matchStatusLabel(seg.match_status)}
                  </span>
                  <span className="text-[10px] text-gray-400">代次 {seg.current_generation}</span>
                  {locked ? (
                    <span className="rounded bg-brand px-1.5 py-0.5 text-[10px] text-white" data-testid="seg-locked">🔒 锁定</span>
                  ) : seg.selected_shot_id != null ? (
                    <span className="rounded bg-brand-light px-1.5 py-0.5 text-[10px] text-brand-dark">已选择</span>
                  ) : null}
                  {seg.candidates_stale ? (
                    <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700" data-testid="seg-stale">
                      候选过期
                    </span>
                  ) : null}
                </div>
                <p className="line-clamp-2 text-xs text-gray-700">{seg.segment_text}</p>
                <div className="flex flex-wrap gap-1 text-[10px] text-gray-400">
                  <span>时长 {durationRangeLabel(seg.target_duration_min, seg.target_duration_max)}</span>
                  {productName(seg.product_id) ? <span>· 产品 {productName(seg.product_id)}</span> : null}
                  {terms.map((t) => (
                    <span key={t}>· {t}</span>
                  ))}
                </div>
              </button>
              <div className="flex flex-col items-center gap-0.5">
                <button
                  type="button"
                  aria-label="上移段落"
                  onClick={() => move(i, -1)}
                  disabled={i === 0 || reorder.isPending}
                  className="rounded px-1 text-xs text-gray-400 hover:bg-gray-100 disabled:opacity-30"
                >
                  ▲
                </button>
                <button
                  type="button"
                  aria-label="下移段落"
                  onClick={() => move(i, 1)}
                  disabled={i === segments.length - 1 || reorder.isPending}
                  className="rounded px-1 text-xs text-gray-400 hover:bg-gray-100 disabled:opacity-30"
                >
                  ▼
                </button>
              </div>
            </div>

            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                data-testid="seg-match"
                onClick={() => {
                  onSelect(seg.id);
                  match.mutate({ segmentId: seg.id });
                }}
                disabled={match.isPending && match.variables?.segmentId === seg.id}
                className="rounded border border-brand px-2 py-0.5 text-[11px] text-brand hover:bg-brand-light disabled:opacity-50"
              >
                {match.isPending && match.variables?.segmentId === seg.id
                  ? "匹配中…"
                  : seg.match_status === "pending"
                    ? "匹配本段"
                    : "重新匹配"}
              </button>
              <button
                type="button"
                data-testid="seg-edit"
                onClick={() => setEditingId(editingId === seg.id ? null : seg.id)}
                className="rounded border border-gray-300 px-2 py-0.5 text-[11px] text-gray-600 hover:bg-gray-50"
              >
                {editingId === seg.id ? "收起" : "编辑"}
              </button>
            </div>

            {conflictId === seg.id ? (
              <p className="mt-1 text-[11px] text-red-600" role="alert" data-testid="seg-conflict">
                数据已被其他操作更新，请刷新后重试。
              </p>
            ) : null}

            {editingId === seg.id ? (
              <div className="mt-2">
                <SegmentEditor
                  segment={seg}
                  products={products}
                  onSave={(req) => onSave(seg.id, req)}
                  saving={update.isPending && update.variables?.segmentId === seg.id}
                  onCancel={() => {
                    setEditingId(null);
                    setConflictId(null);
                  }}
                />
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
