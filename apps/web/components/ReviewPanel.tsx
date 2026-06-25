"use client";

import { useEffect, useState } from "react";

import {
  useEffectiveResult,
  useProductCandidates,
  useReviewActionMutation,
  useReviewEvents,
  useReviewState,
} from "@/lib/hooks";
import type { ReviewActionKind, ReviewStatus, ShotAnalysisResult } from "@/lib/types";

const STATUS_LABEL: Record<string, string> = {
  unreviewed: "未审核",
  pending_review: "待审核",
  confirmed: "已确认",
  modified: "已修改",
  rejected: "已驳回",
  unable: "无法判断",
};
const STATUS_COLOR: Record<string, string> = {
  unreviewed: "bg-gray-100 text-gray-600",
  pending_review: "bg-amber-50 text-amber-700",
  confirmed: "bg-emerald-50 text-emerald-700",
  modified: "bg-emerald-50 text-emerald-700",
  rejected: "bg-red-50 text-red-700",
  unable: "bg-gray-100 text-gray-500",
};

function Chips({ label, items, tone }: { label: string; items: string[]; tone: string }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="text-[11px] text-gray-400">{label}</span>
      {items.map((x) => (
        <span key={x} className={`rounded px-1.5 py-0.5 text-[11px] ${tone}`}>
          {x}
        </span>
      ))}
    </div>
  );
}

export function ReviewPanel({ shotId }: { shotId: number }) {
  const effQ = useEffectiveResult(shotId);
  const stateQ = useReviewState(shotId);
  const eventsQ = useReviewEvents(shotId);
  const candQ = useProductCandidates(shotId);
  const mut = useReviewActionMutation();

  const [editing, setEditing] = useState(false);
  const [oneLine, setOneLine] = useState("");
  const [scene, setScene] = useState("");
  const [comment, setComment] = useState("");

  const eff = effQ.data;
  const state = stateQ.data;
  const lock = state?.lock_version ?? 0;
  const result = eff?.result ?? null;

  useEffect(() => {
    setEditing(false);
    setComment("");
  }, [shotId]);

  const act = (action: ReviewActionKind, extra?: Partial<{ confirmed_result: Partial<ShotAnalysisResult>; confirmed_product_id: number | null }>) => {
    mut.mutate({
      shotId,
      action,
      body: { lock_version: lock, comment: comment || undefined, ...extra },
    });
  };

  const startEdit = () => {
    setOneLine(result?.one_line ?? "");
    setScene(result?.scene ?? "");
    setEditing(true);
  };
  const submitModify = () => {
    act("modify", { confirmed_result: { ...(result ?? {}), one_line: oneLine, scene } });
    setEditing(false);
  };

  const status = (state?.review_status ?? "unreviewed") as ReviewStatus;
  const sourceLabel =
    eff?.source === "human" ? "人工确认结果" : eff?.source === "ai" ? "AI 结果（未确认）" : null;

  return (
    <div className="space-y-2 rounded border border-gray-100 bg-gray-50/60 p-3" data-testid="review-panel">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-700">AI 画面理解 · 人工审核</span>
        <span className={`rounded px-1.5 py-0.5 text-[11px] ${STATUS_COLOR[status]}`}>
          {STATUS_LABEL[status]}
        </span>
      </div>

      {mut.isError ? (
        <p className="rounded bg-red-50 p-2 text-[11px] text-red-700">
          操作失败：{(mut.error as Error)?.message ?? "可能是版本冲突或非法状态转换，请刷新后重试"}
        </p>
      ) : null}

      {eff?.review_is_stale ? (
        <p className="rounded bg-amber-50 p-2 text-[11px] text-amber-700">
          历史人工结果已过期（{eff.stale_reason ?? "重拆镜头"}），需重新审核；当前展示最新 AI 结果。
        </p>
      ) : eff?.has_newer_ai_result ? (
        <p className="rounded bg-blue-50 p-2 text-[11px] text-blue-700">
          存在更新的 AI 结果；人工结果仍有效，可选择重新审核。
        </p>
      ) : null}

      {effQ.isLoading ? <div className="text-[11px] text-gray-400">加载中…</div> : null}

      {sourceLabel ? (
        <span
          className={`inline-block rounded px-1.5 py-0.5 text-[10px] ${
            eff?.source === "human" ? "bg-emerald-100 text-emerald-700" : "bg-gray-200 text-gray-600"
          }`}
        >
          {sourceLabel}
        </span>
      ) : eff?.source === "rejected" || eff?.source === "unable" ? (
        <span className="inline-block rounded bg-gray-200 px-1.5 py-0.5 text-[10px] text-gray-600">
          {eff.source === "rejected" ? "已驳回（不进入搜索）" : "无法判断"}
        </span>
      ) : null}

      {result ? (
        <div className="space-y-1.5">
          {result.one_line ? <p className="text-xs text-gray-800">{result.one_line}</p> : null}
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-600">
            {result.scene ? <span>场景：{result.scene}</span> : null}
            {result.action ? <span>动作：{result.action}</span> : null}
            {result.shot_type ? <span>镜头：{result.shot_type}</span> : null}
            {typeof result.confidence === "number" ? (
              <span>置信度 {Math.round((result.confidence ?? 0) * 100)}%</span>
            ) : null}
          </div>
          <Chips label="营销" items={result.marketing_use ?? []} tone="bg-indigo-50 text-indigo-700" />
          <Chips label="质量" items={result.quality_issues ?? []} tone="bg-amber-50 text-amber-700" />
          <Chips label="风险" items={result.risk_flags ?? []} tone="bg-red-100 text-red-700" />
        </div>
      ) : (
        <p className="text-[11px] text-gray-400">尚无有效结果（未分析或被驳回）。</p>
      )}

      {/* 产品候选（AI 候选，需人工确认；不自动绑定） */}
      {(candQ.data?.length ?? 0) > 0 ? (
        <div className="space-y-1" data-testid="product-candidates">
          <div className="text-[11px] text-gray-400">AI 产品候选（点击确认归属）</div>
          {candQ.data!.slice(0, 5).map((c) => (
            <button
              key={c.product_id}
              type="button"
              onClick={() => act(status === "confirmed" || status === "modified" ? "modify" : "confirm", { confirmed_product_id: c.product_id, confirmed_result: result ?? undefined })}
              disabled={mut.isPending}
              className="flex w-full items-center justify-between rounded border border-gray-200 bg-white px-2 py-1 text-[11px] hover:bg-gray-50 disabled:opacity-50"
            >
              <span className="text-gray-700">{c.product_name}{c.sku ? ` · ${c.sku}` : ""}</span>
              <span className="text-gray-400">{c.match_type} {Math.round(c.match_score * 100)}%</span>
            </button>
          ))}
        </div>
      ) : null}

      {/* 修改编辑（简化：一句话 + 场景） */}
      {editing ? (
        <div className="space-y-1 rounded border border-gray-200 bg-white p-2">
          <input
            value={oneLine}
            onChange={(e) => setOneLine(e.target.value)}
            placeholder="一句话画面描述"
            className="w-full rounded border border-gray-200 px-2 py-1 text-xs"
          />
          <input
            value={scene}
            onChange={(e) => setScene(e.target.value)}
            placeholder="场景"
            className="w-full rounded border border-gray-200 px-2 py-1 text-xs"
          />
          <div className="flex gap-1">
            <button
              type="button"
              data-testid="review-modify-submit"
              onClick={submitModify}
              disabled={mut.isPending}
              className="flex-1 rounded bg-brand px-2 py-1 text-xs text-white hover:bg-brand-dark disabled:opacity-50"
            >
              保存并确认
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600"
            >
              取消
            </button>
          </div>
        </div>
      ) : null}

      <input
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="审核意见（可选）"
        className="w-full rounded border border-gray-200 px-2 py-1 text-[11px]"
      />

      {/* 审核动作 */}
      <div className="flex flex-wrap gap-1" data-testid="review-actions">
        <button
          type="button"
          data-testid="review-confirm"
          onClick={() => act("confirm", { confirmed_result: result ?? undefined })}
          disabled={mut.isPending || status === "confirmed"}
          className="rounded bg-emerald-600 px-2 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          ✓ 确认
        </button>
        <button
          type="button"
          onClick={startEdit}
          disabled={mut.isPending}
          className="rounded border border-emerald-300 bg-white px-2 py-1 text-xs text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
        >
          ✎ 修改
        </button>
        <button
          type="button"
          onClick={() => act("reject")}
          disabled={mut.isPending}
          className="rounded border border-red-300 bg-white px-2 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50"
        >
          ✕ 驳回
        </button>
        <button
          type="button"
          onClick={() => act("unable")}
          disabled={mut.isPending}
          className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        >
          ? 无法判断
        </button>
        {status !== "unreviewed" && status !== "pending_review" ? (
          <button
            type="button"
            onClick={() => act("reopen")}
            disabled={mut.isPending}
            className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          >
            ↻ 重新审核
          </button>
        ) : null}
      </div>

      {(eventsQ.data?.length ?? 0) > 0 ? (
        <details className="text-[11px] text-gray-500">
          <summary className="cursor-pointer">审核记录（{eventsQ.data!.length}）</summary>
          <ul className="mt-1 space-y-0.5">
            {eventsQ.data!.slice(-5).map((e) => (
              <li key={e.id}>
                {STATUS_LABEL[e.action] ?? e.action} · {e.reviewer_label ?? "本地"} ·{" "}
                {new Date(e.created_at).toLocaleString()}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
