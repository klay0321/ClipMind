"use client";

import { USAGE_MODE_LABELS, USAGE_PRESET_LABELS } from "@/lib/search";
import type { SearchFormState } from "@/lib/search";
import { cn } from "@/lib/cn";
import type { UsageMode, UsagePreset, UsageScope } from "@/lib/types";

const MODES = Object.keys(USAGE_MODE_LABELS) as UsageMode[];

/** 快捷使用模式（点击即提交；default 与旧行为逐位一致）。 */
export function UsageModePills({
  value,
  onSelect,
}: {
  value: UsageMode;
  onSelect: (mode: UsageMode) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="usage-mode-pills">
      <span className="text-xs text-gray-400">使用情况：</span>
      {MODES.map((m) => (
        <button
          key={m}
          type="button"
          data-testid={`usage-mode-${m}`}
          aria-pressed={value === m}
          onClick={() => onSelect(m)}
          className={cn(
            "rounded-full border px-2.5 py-1 text-xs transition",
            value === m
              ? "border-brand bg-brand/10 font-medium text-brand"
              : "border-gray-300 bg-white text-gray-600 hover:bg-gray-50",
          )}
        >
          {USAGE_MODE_LABELS[m]}
        </button>
      ))}
    </div>
  );
}

/** 高级使用筛选（阈值 / 作用域 / 弱证据展示 / 排序预设 / 解释开关）。 */
export function UsageAdvancedFilters({
  form,
  onChange,
}: {
  form: SearchFormState;
  onChange: (patch: Partial<SearchFormState>) => void;
}) {
  return (
    <fieldset
      className="grid grid-cols-2 gap-3 rounded border border-gray-200 p-3 md:grid-cols-3"
      data-testid="usage-advanced-filters"
    >
      <legend className="px-1 text-xs font-medium text-gray-500">使用情况筛选与排序</legend>
      <label className="flex flex-col gap-1 text-xs text-gray-600">
        最大正式使用次数
        <input
          type="number"
          min={0}
          value={form.maxConfirmedUsage}
          onChange={(e) => onChange({ maxConfirmedUsage: e.target.value })}
          placeholder="不限"
          data-testid="usage-max-count"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-gray-600">
        最近 N 天未使用
        <input
          type="number"
          min={0}
          value={form.excludeRecentDays}
          onChange={(e) => onChange({ excludeRecentDays: e.target.value })}
          placeholder="不限"
          data-testid="usage-recent-days"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-gray-600">
        统计范围
        <select
          value={form.usageScope}
          onChange={(e) => onChange({ usageScope: e.target.value as UsageScope })}
          data-testid="usage-scope"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
        >
          <option value="combined">镜头为主 + 素材辅助</option>
          <option value="shot">仅镜头</option>
          <option value="asset">仅素材</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-gray-600">
        排序预设
        <select
          value={form.usagePreset}
          onChange={(e) => onChange({ usagePreset: e.target.value as UsagePreset })}
          data-testid="usage-preset"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
        >
          {(Object.keys(USAGE_PRESET_LABELS) as UsagePreset[]).map((p) => (
            <option key={p} value={p}>
              {USAGE_PRESET_LABELS[p]}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1.5 text-xs text-gray-600">
        <input
          type="checkbox"
          checked={form.includeLegacyUnknown}
          onChange={(e) => onChange({ includeLegacyUnknown: e.target.checked })}
          data-testid="usage-include-legacy"
        />
        展示历史弱证据提示
      </label>
      <label className="flex items-center gap-1.5 text-xs text-gray-600">
        <input
          type="checkbox"
          checked={form.showUsageExplanation}
          onChange={(e) => onChange({ showUsageExplanation: e.target.checked })}
          data-testid="usage-show-explanation"
        />
        显示排序解释
      </label>
    </fieldset>
  );
}
