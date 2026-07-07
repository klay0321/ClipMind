// 高级筛选（可折叠）。覆盖产品/品牌/型号/SKU/场景/动作/镜头类型/营销用途/质量/风险包含排除/
// 时长/画幅/审核状态/仅人工确认/stale/来源目录/创建时间/include_excluded。
// 危险项（include_excluded）放醒目危险区，不默认暴露，避免误操作。
"use client";

import { usePmSummary, useProducts, useSourceDirectories } from "@/lib/hooks";
import { ASPECT_RATIO_OPTIONS, REVIEW_STATUS_LABELS, countActiveFilters } from "@/lib/search";
import type { SearchFormState, StaleFilter } from "@/lib/search";
import type { AspectRatioValue, ReviewStatus } from "@/lib/types";

import { UsageAdvancedFilters } from "./UsageControls";

const REVIEW_OPTIONS: ReviewStatus[] = [
  "unreviewed",
  "pending_review",
  "confirmed",
  "modified",
  "rejected",
  "unable",
];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-gray-500">{label}</span>
      {children}
    </label>
  );
}

const textCls =
  "rounded border border-gray-300 px-2 py-1 text-xs focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand";

export function AdvancedFilters({
  form,
  onChange,
  onApply,
  onReset,
  open,
  onToggle,
}: {
  form: SearchFormState;
  onChange: (patch: Partial<SearchFormState>) => void;
  onApply: () => void;
  onReset: () => void;
  open: boolean;
  onToggle: () => void;
}) {
  const productsQ = useProducts();
  const pmSummaryQ = usePmSummary();
  const dirsQ = useSourceDirectories();
  const activeCount = countActiveFilters(form);

  const toggleAspect = (a: AspectRatioValue) => {
    const has = form.aspectRatios.includes(a);
    onChange({
      aspectRatios: has ? form.aspectRatios.filter((x) => x !== a) : [...form.aspectRatios, a],
    });
  };
  const toggleReview = (r: ReviewStatus) => {
    const has = form.reviewStatuses.includes(r);
    onChange({
      reviewStatuses: has ? form.reviewStatuses.filter((x) => x !== r) : [...form.reviewStatuses, r],
    });
  };

  return (
    <section className="rounded-lg border border-gray-200 bg-white" data-testid="advanced-filters">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        data-testid="advanced-filters-toggle"
        className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium text-gray-700"
      >
        <span className="flex items-center gap-2">
          高级筛选
          {activeCount > 0 ? (
            <span className="rounded-full bg-brand px-1.5 py-0.5 text-[10px] font-medium text-white">
              {activeCount}
            </span>
          ) : null}
        </span>
        <span className="text-gray-400" aria-hidden>
          {open ? "收起 ▴" : "展开 ▾"}
        </span>
      </button>

      {open ? (
        <div className="space-y-3 border-t border-gray-100 p-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <Field label="产品">
              <select
                data-testid="filter-product"
                value={form.productId ?? ""}
                onChange={(e) => onChange({ productId: e.target.value ? Number(e.target.value) : null })}
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
            </Field>
            <Field label="目录产品（素材关联）">
              <select
                data-testid="filter-product-family"
                value={form.productFamilyId ?? ""}
                onChange={(e) =>
                  onChange({
                    productFamilyId: e.target.value ? Number(e.target.value) : null,
                  })
                }
                className={textCls}
                title="按产品素材库的正式关联过滤（含镜头继承）"
              >
                <option value="">不限</option>
                {(pmSummaryQ.data ?? []).map((f) => (
                  <option key={f.family_id} value={f.family_id}>
                    {f.name_zh}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="品牌">
              <input
                value={form.brands}
                onChange={(e) => onChange({ brands: e.target.value })}
                placeholder="逗号分隔"
                className={textCls}
              />
            </Field>
            <Field label="型号">
              <input
                value={form.models}
                onChange={(e) => onChange({ models: e.target.value })}
                placeholder="逗号分隔"
                className={textCls}
              />
            </Field>
            <Field label="SKU">
              <input
                value={form.skus}
                onChange={(e) => onChange({ skus: e.target.value })}
                placeholder="逗号分隔"
                className={textCls}
              />
            </Field>
            <Field label="场景">
              <input
                data-testid="filter-scenes"
                value={form.scenes}
                onChange={(e) => onChange({ scenes: e.target.value })}
                placeholder="如 室内,桌面"
                className={textCls}
              />
            </Field>
            <Field label="动作">
              <input
                data-testid="filter-actions"
                value={form.actions}
                onChange={(e) => onChange({ actions: e.target.value })}
                placeholder="如 充电,安装"
                className={textCls}
              />
            </Field>
            <Field label="镜头类型">
              <input
                value={form.shotTypes}
                onChange={(e) => onChange({ shotTypes: e.target.value })}
                placeholder="如 特写"
                className={textCls}
              />
            </Field>
            <Field label="营销用途">
              <input
                value={form.marketingUses}
                onChange={(e) => onChange({ marketingUses: e.target.value })}
                placeholder="如 开箱"
                className={textCls}
              />
            </Field>
            <Field label="质量">
              <input
                value={form.qualityLevels}
                onChange={(e) => onChange({ qualityLevels: e.target.value })}
                placeholder="如 高清"
                className={textCls}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <Field label="风险包含">
              <input
                data-testid="filter-include-risks"
                value={form.includeRisks}
                onChange={(e) => onChange({ includeRisks: e.target.value })}
                placeholder="逗号分隔"
                className={textCls}
              />
            </Field>
            <Field label="风险排除">
              <input
                data-testid="filter-exclude-risks"
                value={form.excludeRisks}
                onChange={(e) => onChange({ excludeRisks: e.target.value })}
                placeholder="如 competitor,blur"
                className={textCls}
              />
            </Field>
            <Field label="来源目录">
              <select
                value={form.sourceDirectoryId ?? ""}
                onChange={(e) =>
                  onChange({ sourceDirectoryId: e.target.value ? Number(e.target.value) : null })
                }
                className={textCls}
              >
                <option value="">全部目录</option>
                {(dirsQ.data ?? []).map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="最短时长(秒)">
              <input
                type="number"
                min={0}
                data-testid="filter-duration-min"
                value={form.durationMin}
                onChange={(e) => onChange({ durationMin: e.target.value })}
                className={textCls}
              />
            </Field>
            <Field label="最长时长(秒)">
              <input
                type="number"
                min={0}
                data-testid="filter-duration-max"
                value={form.durationMax}
                onChange={(e) => onChange({ durationMax: e.target.value })}
                className={textCls}
              />
            </Field>
            <Field label="stale（审核过期）">
              <select
                value={form.stale}
                onChange={(e) => onChange({ stale: e.target.value as StaleFilter })}
                className={textCls}
              >
                <option value="">不限</option>
                <option value="true">仅已过期</option>
                <option value="false">仅未过期</option>
              </select>
            </Field>
            <Field label="创建起">
              <input
                type="date"
                value={form.createdFrom}
                onChange={(e) => onChange({ createdFrom: e.target.value })}
                className={textCls}
              />
            </Field>
            <Field label="创建止">
              <input
                type="date"
                value={form.createdTo}
                onChange={(e) => onChange({ createdTo: e.target.value })}
                className={textCls}
              />
            </Field>
          </div>

          {/* 画幅 */}
          <div className="space-y-1">
            <span className="text-xs text-gray-500">画幅</span>
            <div className="flex flex-wrap gap-1">
              {ASPECT_RATIO_OPTIONS.map((a) => (
                <button
                  key={a}
                  type="button"
                  data-testid={`filter-aspect-${a}`}
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

          {/* 审核状态 + 仅人工确认 */}
          <div className="space-y-1">
            <span className="text-xs text-gray-500">审核状态</span>
            <div className="flex flex-wrap gap-1">
              {REVIEW_OPTIONS.map((r) => (
                <button
                  key={r}
                  type="button"
                  data-testid={`filter-review-${r}`}
                  aria-pressed={form.reviewStatuses.includes(r)}
                  onClick={() => toggleReview(r)}
                  className={`rounded-full px-2 py-0.5 text-[11px] ${
                    form.reviewStatuses.includes(r)
                      ? "bg-brand text-white"
                      : "border border-gray-200 text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  {REVIEW_STATUS_LABELS[r]}
                </button>
              ))}
            </div>
            <label className="mt-1 flex items-center gap-1.5 text-xs text-gray-600">
              <input
                type="checkbox"
                data-testid="filter-confirmed-only"
                checked={form.confirmedOnly}
                onChange={(e) => onChange({ confirmedOnly: e.target.checked })}
              />
              仅人工确认（已确认 / 已修改）
            </label>
          </div>

          {/* 危险区：include_excluded */}
          <div className="rounded-md border border-amber-200 bg-amber-50/60 p-2">
            <div className="mb-1 text-[11px] font-medium text-amber-700">⚠ 谨慎选项</div>
            <label className="flex items-center gap-1.5 text-xs text-amber-800">
              <input
                type="checkbox"
                data-testid="filter-include-excluded"
                checked={form.includeExcluded}
                onChange={(e) => onChange({ includeExcluded: e.target.checked })}
              />
              包含已排除镜头（已驳回 / 无法判断 / 非当前代次）—— 仅排查用，结果可能含不可用镜头
            </label>
          </div>

          <UsageAdvancedFilters form={form} onChange={onChange} />

          <div className="flex justify-end gap-2 border-t border-gray-100 pt-2">
            <button
              type="button"
              data-testid="filters-reset"
              onClick={onReset}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
            >
              重置筛选
            </button>
            <button
              type="button"
              data-testid="filters-apply"
              onClick={onApply}
              className="rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark"
            >
              应用筛选
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
