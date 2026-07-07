"use client";

import { useState } from "react";

import { ApiError } from "@/lib/api";
import { useAssetImageAnalysis, useImageReviewAction } from "@/lib/hooks";
import type { ImageAnalysisView } from "@/lib/types";
import { cn } from "@/lib/cn";

// IMG-REVIEW：图片素材的 AI 理解展示 + 人工审核（确认/修改/驳回/重开）。
// 人工确认后成为检索文档的有效结果；驳回后该图片不再可搜（不伪造状态）。
const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  unreviewed: { text: "未审核", cls: "bg-gray-100 text-gray-600" },
  pending_review: { text: "待审核", cls: "bg-amber-50 text-amber-700" },
  confirmed: { text: "已确认", cls: "bg-emerald-50 text-emerald-700" },
  modified: { text: "已修改", cls: "bg-emerald-50 text-emerald-700" },
  rejected: { text: "已驳回", cls: "bg-red-50 text-red-600" },
  unable: { text: "无法判断", cls: "bg-gray-100 text-gray-500" },
};

export function ImageReviewPanel({ assetId }: { assetId: number }) {
  const q = useAssetImageAnalysis(assetId);
  const act = useImageReviewAction(assetId);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const data = q.data;
  if (q.isLoading) {
    return (
      <section data-testid="image-review-panel">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
          AI 图片理解
        </h3>
        <p className="text-xs text-gray-400">加载中…</p>
      </section>
    );
  }
  if (!data) return null;

  const badge = STATUS_LABEL[data.review_status] ?? STATUS_LABEL.unreviewed;
  const effective = data.effective_result;
  const hasAi = data.ai_status === "completed" && data.ai_result;
  const submit = (action: string, confirmed?: Record<string, unknown>) =>
    act.mutate({ action, lock_version: data.lock_version, confirmed_result: confirmed });

  const startModify = () => {
    setDraft(String((effective ?? data.ai_result ?? {})["one_line"] ?? ""));
    setEditing(true);
  };
  const submitModify = () => {
    const base = { ...(effective ?? data.ai_result ?? {}) };
    base["one_line"] = draft.trim();
    submit("modify", base);
    setEditing(false);
  };

  const errMsg =
    act.error instanceof ApiError ? act.error.message : (act.error as Error | null)?.message;

  return (
    <section data-testid="image-review-panel">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          AI 图片理解
        </h3>
        <span
          className={cn("rounded px-1.5 py-0.5 text-[11px] font-medium", badge.cls)}
          data-testid="image-review-status"
        >
          {badge.text}
        </span>
      </div>

      {!hasAi && !effective ? (
        <p className="text-xs text-gray-400" data-testid="image-review-empty">
          还没有 AI 理解结果（等待自动打标或点上方「AI 分析」）
        </p>
      ) : (
        <div className="space-y-1.5 rounded-md border border-gray-200 bg-gray-50 p-2.5 text-sm">
          {data.review_status === "rejected" ? (
            <p className="text-xs text-red-600" data-testid="image-review-rejected-note">
              已驳回：该图片的 AI 描述不会进入搜索。
            </p>
          ) : null}
          <p className="text-gray-800" data-testid="image-review-one-line">
            {String((effective ?? data.ai_result ?? {})["one_line"] ?? "（无描述）")}
          </p>
          {Array.isArray((effective ?? data.ai_result ?? {})["search_keywords"] ) ? (
            <p className="text-xs text-gray-500">
              {((effective ?? data.ai_result ?? {})["search_keywords"] as string[])
                .slice(0, 8)
                .join(" · ")}
            </p>
          ) : null}
          <p className="text-[11px] text-gray-400">
            当前生效：{data.effective_source === "human" ? "人工结果" :
              data.effective_source === "ai" ? "AI 结果（未审核）" :
              data.effective_source === "rejected" ? "无（已驳回）" : "无"}
            {data.reviewer_label ? ` · ${data.reviewer_label}` : ""}
          </p>
        </div>
      )}

      {editing ? (
        <div className="mt-2 space-y-2" data-testid="image-review-editor">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={2}
            aria-label="修改一句话描述"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none"
            data-testid="image-review-draft"
          />
          <div className="flex gap-2">
            <button
              type="button"
              onClick={submitModify}
              disabled={!draft.trim() || act.isPending}
              className="rounded bg-brand px-3 py-1 text-xs font-medium text-white disabled:opacity-40"
              data-testid="image-review-save"
            >
              保存修改
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-600"
            >
              取消
            </button>
          </div>
        </div>
      ) : hasAi || effective ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {["unreviewed", "pending_review"].includes(data.review_status) ? (
            <>
              <button
                type="button"
                onClick={() => submit("confirm")}
                disabled={act.isPending || !hasAi}
                className="rounded bg-emerald-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-40"
                data-testid="image-review-confirm"
              >
                确认 AI 结果
              </button>
              <button
                type="button"
                onClick={startModify}
                disabled={act.isPending}
                className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-700"
                data-testid="image-review-modify"
              >
                修改
              </button>
              <button
                type="button"
                onClick={() => submit("reject")}
                disabled={act.isPending}
                className="rounded border border-red-200 px-3 py-1 text-xs text-red-600"
                data-testid="image-review-reject"
              >
                驳回
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => submit("reopen")}
              disabled={act.isPending}
              className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-600"
              data-testid="image-review-reopen"
            >
              重新打开审核
            </button>
          )}
        </div>
      ) : null}

      {act.isError ? (
        <p className="mt-1 text-xs text-red-600" data-testid="image-review-error">
          {errMsg ?? "操作失败"}
        </p>
      ) : null}
    </section>
  );
}

export type { ImageAnalysisView };
