// 画面描述匹配视图（对照 UI 参考图 04）：左侧画面描述 + 匹配设置；右侧按综合匹配度排序的候选镜头。
// 体现独立语义：target_description / recommendation_level / requires_human_confirmation /
// target_requirements / matched_requirements / minimum_score / filtered_total / truncated。
"use client";

import { useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import { useDescriptionMatch, useProducts } from "@/lib/hooks";
import {
  ASPECT_RATIO_OPTIONS,
  DESCRIPTION_EXAMPLES,
  EMPTY_DESCRIPTION_FORM,
  buildDescriptionRequest,
} from "@/lib/search";
import type { DescriptionFormState } from "@/lib/search";
import type {
  AspectRatioValue,
  DescriptionMatchItem,
  DescriptionMatchRequest,
} from "@/lib/types";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";

import { DegradedNotice } from "./DegradedNotice";
import { MatchResultRow } from "./MatchResultRow";

const MAX_DESC = 500;
const textCls =
  "rounded border border-gray-300 px-2 py-1 text-xs focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand";

export function DescriptionMatchView({
  onOpenItem,
  onPreview,
}: {
  onOpenItem: (item: DescriptionMatchItem) => void;
  onPreview: (shotId: number) => void;
}) {
  const [form, setForm] = useState<DescriptionFormState>(EMPTY_DESCRIPTION_FORM);
  const [committed, setCommitted] = useState<DescriptionFormState | null>(null);
  const productsQ = useProducts();

  const req: DescriptionMatchRequest | null = useMemo(
    () => (committed && committed.target.trim() ? buildDescriptionRequest(committed) : null),
    [committed],
  );
  const q = useDescriptionMatch(req);
  const data = q.data;

  const patch = (p: Partial<DescriptionFormState>) => setForm((f) => ({ ...f, ...p }));
  const match = () => {
    if (form.target.trim()) setCommitted(form);
  };
  const clear = () => {
    setForm(EMPTY_DESCRIPTION_FORM);
    setCommitted(null);
  };
  const toggleAspect = (a: AspectRatioValue) => {
    const has = form.aspectRatios.includes(a);
    patch({ aspectRatios: has ? form.aspectRatios.filter((x) => x !== a) : [...form.aspectRatios, a] });
  };

  const loading = q.isFetching && !data;
  const isError = q.isError && !data;
  const errMsg =
    q.error instanceof ApiError ? q.error.message : (q.error as Error)?.message ?? "匹配失败";

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
      {/* 左：画面描述 + 匹配设置 */}
      <aside className="space-y-3 lg:sticky lg:top-4 lg:self-start">
        <section className="rounded-lg border border-gray-200 bg-white p-3">
          <div className="mb-1 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-800">画面描述</h2>
            <span className="text-[11px] text-gray-400">
              {form.target.length}/{MAX_DESC}
            </span>
          </div>
          <label htmlFor="desc-input" className="sr-only">
            画面描述
          </label>
          <textarea
            id="desc-input"
            data-testid="desc-input"
            value={form.target}
            maxLength={MAX_DESC}
            onChange={(e) => patch({ target: e.target.value })}
            rows={4}
            placeholder="输入脚本画面或镜头描述，例如：酒店桌面插墙充电，手机正在连接充电，画面要能直接做使用演示"
            className="w-full resize-y rounded border border-gray-300 px-2 py-2 text-xs focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
          <div className="mt-1 flex flex-wrap items-center gap-1">
            <span className="text-[10px] text-gray-400">示例</span>
            {DESCRIPTION_EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                data-testid="desc-example"
                onClick={() => patch({ target: ex })}
                title={ex}
                className="max-w-full truncate rounded-full bg-gray-100 px-2 py-0.5 text-[10px] text-gray-600 hover:bg-gray-200"
              >
                {ex.length > 16 ? `${ex.slice(0, 16)}…` : ex}
              </button>
            ))}
          </div>
        </section>

        <section className="space-y-2 rounded-lg border border-gray-200 bg-white p-3">
          <h3 className="text-xs font-semibold text-gray-700">匹配设置</h3>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-500">产品</span>
            <select
              data-testid="desc-product"
              value={form.productId ?? ""}
              onChange={(e) => patch({ productId: e.target.value ? Number(e.target.value) : null })}
              className={textCls}
            >
              <option value="">全部产品</option>
              {(productsQ.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.sku ? ` · ${p.sku}` : ""}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-500">返回数量</span>
            <input
              type="number"
              min={1}
              max={100}
              data-testid="desc-limit"
              value={form.limit}
              onChange={(e) => patch({ limit: Math.max(1, Math.min(100, Number(e.target.value) || 1)) })}
              className={textCls}
            />
          </label>

          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-500">最低匹配度 ≥ {Math.round(form.minimumScore * 100)}%</span>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              data-testid="desc-min-score"
              value={Math.round(form.minimumScore * 100)}
              onChange={(e) => patch({ minimumScore: Number(e.target.value) / 100 })}
            />
          </label>

          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-500">风险排除</span>
            <input
              data-testid="desc-exclude-risks"
              value={form.excludeRisks}
              onChange={(e) => patch({ excludeRisks: e.target.value })}
              placeholder="如 competitor,blur"
              className={textCls}
            />
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-gray-500">最短时长(秒)</span>
              <input
                type="number"
                min={0}
                value={form.durationMin}
                onChange={(e) => patch({ durationMin: e.target.value })}
                className={textCls}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-gray-500">最长时长(秒)</span>
              <input
                type="number"
                min={0}
                value={form.durationMax}
                onChange={(e) => patch({ durationMax: e.target.value })}
                className={textCls}
              />
            </label>
          </div>

          <div className="space-y-1">
            <span className="text-xs text-gray-500">画幅</span>
            <div className="flex flex-wrap gap-1">
              {ASPECT_RATIO_OPTIONS.map((a) => (
                <button
                  key={a}
                  type="button"
                  aria-pressed={form.aspectRatios.includes(a)}
                  onClick={() => toggleAspect(a)}
                  className={`rounded-full px-2 py-0.5 text-[11px] ${
                    form.aspectRatios.includes(a)
                      ? "bg-brand text-white"
                      : "border border-gray-200 text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  {a}
                </button>
              ))}
            </div>
          </div>

          <label className="flex items-center gap-1.5 text-xs text-gray-600">
            <input
              type="checkbox"
              data-testid="desc-include-risky"
              checked={!form.confirmedOnly}
              onChange={(e) => patch({ confirmedOnly: !e.target.checked })}
            />
            包含需人工确认 / 风险镜头
          </label>
          <label className="flex items-center gap-1.5 text-xs text-gray-600">
            <input
              type="checkbox"
              checked={form.allowSimilarScene}
              onChange={(e) => patch({ allowSimilarScene: e.target.checked })}
            />
            允许相似场景
          </label>
          <label className="flex items-center gap-1.5 text-xs text-gray-600">
            <input
              type="checkbox"
              checked={form.allowSimilarAction}
              onChange={(e) => patch({ allowSimilarAction: e.target.checked })}
            />
            允许相似动作
          </label>

          <div className="flex gap-2 pt-1">
            <button
              type="button"
              data-testid="desc-clear"
              onClick={clear}
              className="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
            >
              清空
            </button>
            <button
              type="button"
              data-testid="desc-match"
              onClick={match}
              disabled={!form.target.trim() || q.isFetching}
              className="flex-1 rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-50"
            >
              {q.isFetching ? "匹配中…" : "🔍 匹配"}
            </button>
          </div>

          {data ? (
            <div className="flex items-center gap-1.5 rounded bg-emerald-50 px-2 py-1.5 text-[11px] text-emerald-700" data-testid="desc-status">
              <span aria-hidden>✓</span>
              匹配完成，找到 {data.total} 个候选镜头
            </div>
          ) : null}
        </section>
      </aside>

      {/* 右：匹配结果 */}
      <section className="space-y-2">
        <div>
          <h2 className="text-sm font-semibold text-gray-800">匹配结果</h2>
          <p className="text-[11px] text-gray-500">按综合匹配度排序；风险镜头会扣分并显示提示。</p>
        </div>

        {data ? (
          <DegradedNotice
            parserStatus={data.parser_status}
            embeddingStatus={data.embedding_status}
            degradationReasons={data.degradation_reasons}
          />
        ) : null}

        {data ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500" data-testid="desc-meta">
            <span>
              共 <strong className="text-gray-700">{data.filtered_total}</strong> 条可检索
            </span>
            <span>
              候选 <strong className="text-gray-700">{data.total}</strong>
              {data.truncated ? <span className="text-amber-600">+（已截断）</span> : null}
            </span>
            <span>最低匹配度 ≥ {Math.round(data.minimum_score * 100)}%</span>
            <span>用时 {data.elapsed_ms}ms</span>
          </div>
        ) : null}

        {committed == null ? (
          <Empty
            title="输入画面描述开始匹配"
            description="左侧填写脚本画面或镜头描述，系统会按标签、描述、卖点和风险状态推荐多个可用镜头。"
          />
        ) : loading ? (
          <Loading rows={5} />
        ) : isError ? (
          <ErrorState message={errMsg} onRetry={() => void q.refetch()} />
        ) : data && data.items.length === 0 ? (
          <Empty
            title="没有达到匹配阈值的镜头"
            description="可尝试：降低最低匹配度、放宽风险排除、允许相似场景/动作、或勾选包含需人工确认镜头。"
          />
        ) : data ? (
          <>
            <div className="rounded-lg border border-gray-200 bg-white px-2" data-testid="desc-results" aria-busy={q.isFetching}>
              {data.items.map((item) => (
                <MatchResultRow
                  key={item.shot_id}
                  item={item}
                  onSelect={() => onOpenItem(item)}
                  onPreview={onPreview}
                />
              ))}
            </div>
            <p className="text-center text-[11px] text-gray-400">
              已显示 {data.items.length}/{data.total} 个候选镜头
              {data.items.length < data.total ? "（提高返回数量可查看更多）" : ""}
            </p>
          </>
        ) : null}
      </section>
    </div>
  );
}
