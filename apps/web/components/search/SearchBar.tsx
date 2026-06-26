// 自然语言搜索输入：支持中/英/混合/多行/否定条件；搜索模式选择；示例；防抖建议下拉。
// 建议来自真实 suggestions API（绝不把静态示例伪装成 API 返回）。Enter 提交与按钮一致（Shift+Enter 换行）。
"use client";

import { useEffect, useRef, useState } from "react";

import { useSearchSuggestions } from "@/lib/hooks";
import {
  SEARCH_EXAMPLES,
  SEARCH_MODE_HINTS,
  SEARCH_MODE_LABELS,
  SUGGESTION_TYPE_LABELS,
} from "@/lib/search";
import type { SearchMode, SearchSuggestion, SuggestionType } from "@/lib/types";

const MODES: SearchMode[] = ["hybrid", "semantic", "lexical", "structured"];

function groupSuggestions(items: SearchSuggestion[]): [SuggestionType, SearchSuggestion[]][] {
  const order: SuggestionType[] = ["product", "brand", "scene", "action", "marketing", "shot_type", "tag"];
  const map = new Map<SuggestionType, SearchSuggestion[]>();
  for (const it of items) {
    const arr = map.get(it.type) ?? [];
    arr.push(it);
    map.set(it.type, arr);
  }
  return order.filter((t) => map.has(t)).map((t) => [t, map.get(t)!]);
}

export function SearchBar({
  value,
  onChange,
  mode,
  onModeChange,
  onSubmit,
  onClear,
  loading = false,
}: {
  value: string;
  onChange: (v: string) => void;
  mode: SearchMode;
  onModeChange: (m: SearchMode) => void;
  onSubmit: () => void;
  onClear: () => void;
  loading?: boolean;
}) {
  const [focused, setFocused] = useState(false);
  const [debounced, setDebounced] = useState("");
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 防抖：输入停止 250ms 后才请求建议
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value.trim()), 250);
    return () => clearTimeout(t);
  }, [value]);

  const sugQ = useSearchSuggestions(debounced, focused && debounced.length > 0);
  const groups = groupSuggestions(sugQ.data?.items ?? []);
  const showDropdown = focused && debounced.length > 0 && groups.length > 0;

  const applySuggestion = (s: SearchSuggestion) => {
    const next = value.trim() ? `${value.trim()} ${s.value}` : s.value;
    onChange(next);
  };

  return (
    <div className="space-y-2">
      <label htmlFor="search-input" className="sr-only">
        自然语言搜索
      </label>
      <div className="relative">
        <textarea
          id="search-input"
          data-testid="search-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => {
            if (blurTimer.current) clearTimeout(blurTimer.current);
            setFocused(true);
          }}
          onBlur={() => {
            // 延迟关闭，便于点击下拉项
            blurTimer.current = setTimeout(() => setFocused(false), 150);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
            }
          }}
          rows={2}
          placeholder="用一句话描述你要找的镜头，例如：桌面上给手机充电的竖屏镜头，不要人脸"
          className="w-full resize-y rounded-lg border border-gray-300 px-3 py-2.5 pr-28 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
        />
        <div className="absolute right-2 top-2 flex gap-1.5">
          <button
            type="button"
            data-testid="search-clear"
            onClick={onClear}
            disabled={!value && !loading}
            className="rounded-md border border-gray-300 bg-white px-2.5 py-1.5 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40"
          >
            清空
          </button>
          <button
            type="button"
            data-testid="search-submit"
            onClick={onSubmit}
            disabled={loading}
            className="rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-50"
          >
            {loading ? "搜索中…" : "🔍 搜索"}
          </button>
        </div>

        {/* 建议下拉（真实 API） */}
        {showDropdown ? (
          <div
            role="listbox"
            aria-label="搜索建议"
            data-testid="suggestions"
            className="absolute left-0 right-0 top-full z-30 mt-1 max-h-72 overflow-y-auto rounded-lg border border-gray-200 bg-white p-2 shadow-lg"
          >
            {groups.map(([type, items]) => (
              <div key={type} className="mb-1.5 last:mb-0">
                <div className="px-1 py-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-400">
                  {SUGGESTION_TYPE_LABELS[type]}
                </div>
                <div className="flex flex-wrap gap-1">
                  {items.map((s) => (
                    <button
                      key={`${s.type}-${s.value}`}
                      type="button"
                      role="option"
                      aria-selected={false}
                      data-testid="suggestion-item"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => applySuggestion(s)}
                      className="rounded-full border border-gray-200 px-2 py-0.5 text-[11px] text-gray-700 hover:border-brand hover:bg-brand-light"
                    >
                      {s.value}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      {/* 搜索模式 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-gray-500">搜索模式</span>
        <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="搜索模式">
          {MODES.map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              data-testid={`mode-${m}`}
              onClick={() => onModeChange(m)}
              title={SEARCH_MODE_HINTS[m]}
              className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                mode === m
                  ? "bg-brand text-white"
                  : "border border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
              }`}
            >
              {SEARCH_MODE_LABELS[m]}
            </button>
          ))}
        </div>
        <span className="hidden text-[11px] text-gray-400 sm:inline">{SEARCH_MODE_HINTS[mode]}</span>
      </div>

      {/* 搜索示例（静态示例，明确标注） */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] text-gray-400">示例</span>
        {SEARCH_EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            data-testid="search-example"
            onClick={() => onChange(ex)}
            className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600 hover:bg-gray-200"
          >
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}
