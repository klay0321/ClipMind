"use client";

import { useEffect, useState } from "react";

import { Chip } from "@/components/ui/Chip";
import {
  useEffectiveResult,
  useProductCandidates,
  useReviewActionMutation,
  useReviewEvents,
  useReviewState,
  useShotAi,
} from "@/lib/hooks";
import type {
  ProductInfo,
  ReviewActionKind,
  ReviewStatus,
  ShotAnalysisResult,
} from "@/lib/types";

const STATUS_LABEL: Record<string, string> = {
  unreviewed: "未审核",
  pending_review: "待审核",
  confirmed: "已确认",
  modified: "已修改",
  rejected: "已驳回",
  unable: "无法判断",
};

const STATUS_TONE: Record<string, "neutral" | "warning" | "success" | "danger" | "muted"> = {
  unreviewed: "neutral",
  pending_review: "warning",
  confirmed: "success",
  modified: "success",
  rejected: "danger",
  unable: "muted",
};

function productLabel(p: ProductInfo | string | null | undefined): string | null {
  if (!p) return null;
  if (typeof p === "string") return p || null;
  return [p.name, p.model].filter(Boolean).join(" ") || null;
}

// 只读结果字段渲染（AI 区 / 最终区共用）。绝不在此处编辑。
function ResultFields({ result }: { result: Partial<ShotAnalysisResult> | null }) {
  if (!result) return <p className="text-[11px] text-gray-400">暂无结果。</p>;
  const product = productLabel(result.product as ProductInfo | undefined);
  return (
    <div className="space-y-1.5">
      {result.one_line ? <p className="text-xs text-gray-800">{result.one_line}</p> : null}
      {result.detailed ? <p className="text-[11px] text-gray-500">{result.detailed}</p> : null}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-600">
        {product ? <span>产品：{product}</span> : null}
        {result.scene ? <span>场景：{result.scene}</span> : null}
        {result.action ? <span>动作：{result.action}</span> : null}
        {result.shot_type ? <span>镜头：{result.shot_type}</span> : null}
        {typeof result.confidence === "number" ? (
          <span>置信度 {Math.round((result.confidence ?? 0) * 100)}%</span>
        ) : null}
      </div>
      {(result.marketing_use?.length ?? 0) > 0 ? (
        <div className="flex flex-wrap gap-1">
          {result.marketing_use!.map((m) => (
            <Chip key={m} tone="info">
              {m}
            </Chip>
          ))}
        </div>
      ) : null}
      {(result.risk_flags?.length ?? 0) > 0 ? (
        <div className="flex flex-wrap gap-1">
          {result.risk_flags!.map((r) => (
            <Chip key={r} tone="danger">
              {r}
            </Chip>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ReviewPanel({ shotId }: { shotId: number }) {
  const aiQ = useShotAi(shotId);
  const effQ = useEffectiveResult(shotId);
  const stateQ = useReviewState(shotId);
  const eventsQ = useReviewEvents(shotId);
  const candQ = useProductCandidates(shotId);
  const mut = useReviewActionMutation();

  const [editing, setEditing] = useState(false);
  const [oneLine, setOneLine] = useState("");
  const [scene, setScene] = useState("");
  const [comment, setComment] = useState("");

  const ai = aiQ.data;
  const eff = effQ.data;
  const state = stateQ.data;
  const lock = state?.lock_version ?? 0;
  const effResult = eff?.result ?? null;
  const humanResult = state?.confirmed_result ?? null;

  useEffect(() => {
    setEditing(false);
    setComment("");
  }, [shotId]);

  const act = (
    action: ReviewActionKind,
    extra?: Partial<{
      confirmed_result: Partial<ShotAnalysisResult>;
      confirmed_product_id: number | null;
    }>,
  ) => {
    mut.mutate({
      shotId,
      action,
      body: { lock_version: lock, comment: comment || undefined, ...extra },
    });
  };

  const startEdit = () => {
    setOneLine(humanResult?.one_line ?? effResult?.one_line ?? "");
    setScene(humanResult?.scene ?? effResult?.scene ?? "");
    setEditing(true);
  };
  const submitModify = () => {
    act("modify", {
      confirmed_result: { ...(humanResult ?? effResult ?? {}), one_line: oneLine, scene },
    });
    setEditing(false);
  };

  const status = (state?.review_status ?? "unreviewed") as ReviewStatus;
  const reviewed = status === "confirmed" || status === "modified";

  return (
    <div className="space-y-3" data-testid="review-panel">
      {mut.isError ? (
        <p role="alert" className="rounded bg-red-50 p-2 text-[11px] text-red-700">
          操作失败：{(mut.error as Error)?.message ?? "可能是版本冲突或非法状态转换，请刷新后重试"}
        </p>
      ) : null}

      {/* ===== 区域 1：AI 自动分析（只读，蓝色）===== */}
      <section className="rounded-lg border border-blue-100 bg-blue-50/40 p-2.5" data-testid="zone-ai">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-xs font-semibold text-blue-800">AI 自动分析</span>
          {ai?.has_analysis ? (
            <Chip tone="info">{ai.status === "completed" ? "AI 已完成" : ai.status ?? "—"}</Chip>
          ) : (
            <Chip tone="muted">未分析</Chip>
          )}
        </div>
        {aiQ.isLoading ? (
          <p className="text-[11px] text-gray-400">加载中…</p>
        ) : (
          <ResultFields result={(ai?.result as Partial<ShotAnalysisResult>) ?? null} />
        )}
        <p className="mt-1.5 text-[10px] text-blue-700/70">AI 结果仅供参考；重新分析不会覆盖已确认的人工结果。</p>
      </section>

      {/* ===== 区域 2：人工审核结果（可编辑，绿色）===== */}
      <section className="rounded-lg border border-emerald-200 bg-emerald-50/40 p-2.5" data-testid="zone-human">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-xs font-semibold text-emerald-800">人工审核结果</span>
          <Chip tone={STATUS_TONE[status] ?? "neutral"}>{STATUS_LABEL[status]}</Chip>
        </div>

        {eff?.review_is_stale ? (
          <p className="mb-1.5 rounded bg-amber-50 p-1.5 text-[11px] text-amber-700">
            历史人工结果已过期（{eff.stale_reason ?? "重拆镜头"}），需重新审核。
          </p>
        ) : eff?.has_newer_ai_result ? (
          <p className="mb-1.5 rounded bg-blue-50 p-1.5 text-[11px] text-blue-700">
            存在更新的 AI 结果；人工结果仍有效，可选择重新审核。
          </p>
        ) : null}

        {reviewed && humanResult ? (
          <ResultFields result={humanResult} />
        ) : (
          <p className="text-[11px] text-gray-400">尚未人工确认；确认后将以人工结果为准。</p>
        )}

        {/* 产品候选（AI 候选，需人工确认；不自动绑定） */}
        {(candQ.data?.length ?? 0) > 0 ? (
          <div className="mt-2 space-y-1" data-testid="product-candidates">
            <div className="text-[11px] text-gray-400">AI 产品候选（点击确认归属）</div>
            {candQ.data!.slice(0, 5).map((c) => (
              <button
                key={c.product_id}
                type="button"
                onClick={() =>
                  act(reviewed ? "modify" : "confirm", {
                    confirmed_product_id: c.product_id,
                    confirmed_result: humanResult ?? effResult ?? undefined,
                  })
                }
                disabled={mut.isPending}
                className="flex w-full items-center justify-between rounded border border-gray-200 bg-white px-2 py-1 text-[11px] hover:bg-gray-50 disabled:opacity-50"
              >
                <span className="text-gray-700">
                  {c.product_name}
                  {c.sku ? ` · ${c.sku}` : ""}
                </span>
                <span className="text-gray-400">
                  {c.match_type} {Math.round(c.match_score * 100)}%
                </span>
              </button>
            ))}
          </div>
        ) : null}

        {/* 修改编辑（简化：一句话 + 场景） */}
        {editing ? (
          <div className="mt-2 space-y-1 rounded border border-gray-200 bg-white p-2">
            <input
              value={oneLine}
              onChange={(e) => setOneLine(e.target.value)}
              placeholder="一句话画面描述"
              aria-label="人工描述"
              className="w-full rounded border border-gray-200 px-2 py-1 text-xs"
            />
            <input
              value={scene}
              onChange={(e) => setScene(e.target.value)}
              placeholder="场景"
              aria-label="人工场景"
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
          aria-label="审核意见"
          className="mt-2 w-full rounded border border-gray-200 px-2 py-1 text-[11px]"
        />

        <div className="mt-1.5 flex flex-wrap gap-1" data-testid="review-actions">
          <button
            type="button"
            data-testid="review-confirm"
            onClick={() => act("confirm", { confirmed_result: effResult ?? undefined })}
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
      </section>

      {/* ===== 区域 3：最终检索内容（只读汇总）===== */}
      <section className="rounded-lg border border-gray-200 bg-gray-50 p-2.5" data-testid="zone-effective">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-xs font-semibold text-gray-700">最终检索内容</span>
          <div className="flex items-center gap-1">
            <Chip tone={eff?.source === "human" ? "success" : eff?.source === "ai" ? "info" : "muted"}>
              {eff?.source === "human"
                ? "采用人工结果"
                : eff?.source === "ai"
                  ? "采用 AI 结果"
                  : eff?.source === "rejected"
                    ? "已驳回"
                    : eff?.source === "unable"
                      ? "无法判断"
                      : "无"}
            </Chip>
            <Chip tone={eff?.searchable ? "success" : "muted"}>
              {eff?.searchable ? "可搜索" : "未入索引"}
            </Chip>
          </div>
        </div>
        {eff?.source === "rejected" || eff?.source === "unable" ? (
          <p className="text-[11px] text-gray-500">该镜头已被排除，不进入搜索与匹配。</p>
        ) : (
          <ResultFields result={effResult} />
        )}
        <p className="mt-1.5 text-[10px] text-gray-400">这是当前真正用于搜索 / 匹配的内容（人工优先于 AI）。</p>
      </section>

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
