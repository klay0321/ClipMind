// 素材语义搜索视图：搜索栏 + 高级筛选 + 结果区（元信息/排序/分页/网格 + 加载/空/错误/降级/部分结果）。
// 搜索过程中保留筛选；分页/排序保留 query 与筛选；请求取消与竞态由 hook 的 signal 保证。
"use client";

import { useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import { useSemanticSearch } from "@/lib/hooks";
import {
  EMPTY_SEARCH_FORM,
  SORT_LABELS,
  buildSearchRequest,
  hasSearchSignal,
  requestToForm,
} from "@/lib/search";
import type { SearchFormState } from "@/lib/search";
import type { SavedSearch, SearchResultItem, SearchSort, ShotSearchRequest } from "@/lib/types";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";

import { BundleBar } from "@/components/exports/BundleBar";

import { AdvancedFilters } from "./AdvancedFilters";
import { DegradedNotice } from "./DegradedNotice";
import { SavedSearchPanel } from "./SavedSearchPanel";
import { SearchBar } from "./SearchBar";
import { SearchResultCard } from "./SearchResultCard";
import { UsageModePills } from "./UsageControls";

const SORTS: SearchSort[] = ["relevance", "latest", "duration", "quality"];
const PAGE_SIZE = 24;

export function SemanticSearchView({
  initialForm,
  initialPage,
  onCoreChange,
  onOpenItem,
  onPreview,
  selectedShotId,
}: {
  initialForm: SearchFormState;
  initialPage: number;
  onCoreChange: (form: SearchFormState, page: number) => void;
  onOpenItem: (item: SearchResultItem) => void;
  onPreview: (shotId: number) => void;
  selectedShotId: number | null;
}) {
  const [form, setForm] = useState<SearchFormState>(initialForm);
  const [filtersOpen, setFiltersOpen] = useState(false);
  // 已保存搜索默认收起，不抢占结果区首屏
  const [savedOpen, setSavedOpen] = useState(false);
  // ZIP 打包多选（仅当前页选择；换页/换条件后清空，绝不跨页打包）
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  // committed：已提交的搜索条件（与 form 草稿分离，避免输入即搜索）
  const [committed, setCommitted] = useState<{ form: SearchFormState; page: number } | null>(
    hasSearchSignal(initialForm) ? { form: initialForm, page: initialPage } : null,
  );

  const req: ShotSearchRequest | null = useMemo(
    () => (committed ? buildSearchRequest(committed.form, committed.page, PAGE_SIZE) : null),
    [committed],
  );
  const q = useSemanticSearch(req);
  const data = q.data;

  const commit = (next: SearchFormState, page: number) => {
    // 任何新提交/换页/换序都清空打包选择，保证只对当前结果集操作
    setSelectedIds(new Set());
    if (!hasSearchSignal(next)) {
      setCommitted(null);
      return;
    }
    setCommitted({ form: next, page });
    onCoreChange(next, page);
  };

  const patch = (p: Partial<SearchFormState>) => setForm((f) => ({ ...f, ...p }));
  const submit = () => commit(form, 1);

  // 加载保存的搜索：用 requestToForm 还原真实条件 → 填表单 → 立即重跑（第 1 页）。
  const loadSaved = (saved: SavedSearch) => {
    const restored = requestToForm(saved.query as Partial<ShotSearchRequest>);
    setForm(restored);
    commit(restored, 1);
  };

  // 当前可保存的搜索请求（已提交条件；剥离分页，后端也会剥离）。
  const savedQuery: Record<string, unknown> | null = committed
    ? (() => {
        const r = buildSearchRequest(committed.form, 1, PAGE_SIZE) as unknown as Record<
          string,
          unknown
        >;
        delete r.page;
        delete r.page_size;
        return r;
      })()
    : null;
  const clear = () => {
    setForm(EMPTY_SEARCH_FORM);
    setCommitted(null);
    onCoreChange(EMPTY_SEARCH_FORM, 1);
  };
  const changeSort = (sort: SearchSort) => {
    // 仅同步下拉显示；换序基于**已提交**条件，绝不把未提交的草稿（输入框/未应用的筛选）带入请求
    setForm((f) => ({ ...f, sort }));
    if (committed) commit({ ...committed.form, sort }, 1);
  };
  const changePage = (page: number) => {
    if (committed) commit(committed.form, page);
  };

  const loading = q.isFetching && !data;
  const isError = q.isError && !data;
  const errMsg =
    q.error instanceof ApiError ? q.error.message : (q.error as Error)?.message ?? "搜索失败";

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const curPage = committed?.page ?? 1;

  // 仅统计当前页里仍被选中的镜头（换页后 selectedIds 已清空）
  const pageItems = data?.items ?? [];
  const selectedList = pageItems.filter((it) => selectedIds.has(it.shot_id));
  const bundleSelected = selectedList.map((it) => it.shot_id);
  const bundleDuration = selectedList.reduce((sum, it) => sum + (it.duration ?? 0), 0);

  const toggleSelect = (shotId: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(shotId)) next.delete(shotId);
      else next.add(shotId);
      return next;
    });
  };

  return (
    <div className="space-y-3">
      <SearchBar
        value={form.query}
        onChange={(v) => patch({ query: v })}
        mode={form.mode}
        onModeChange={(m) => patch({ mode: m })}
        onSubmit={submit}
        onClear={clear}
        loading={q.isFetching}
      />

      <UsageModePills
        value={form.usageMode}
        onSelect={(m) => {
          const next = { ...form, usageMode: m };
          setForm(next);
          // 快捷模式点击即提交（有已提交条件时立即重跑第 1 页）
          if (committed) commit(next, 1);
        }}
      />

      <AdvancedFilters
        form={form}
        onChange={patch}
        onApply={submit}
        onReset={() => {
          // 重置筛选但保留查询词与模式
          setForm((f) => ({ ...EMPTY_SEARCH_FORM, query: f.query, mode: f.mode, sort: f.sort }));
        }}
        open={filtersOpen}
        onToggle={() => setFiltersOpen((v) => !v)}
      />

      <div className="flex justify-end">
        <button
          type="button"
          data-testid="toggle-saved-search"
          aria-expanded={savedOpen}
          onClick={() => setSavedOpen((v) => !v)}
          className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
        >
          {savedOpen ? "收起已保存搜索 ▴" : "已保存搜索 / 保存搜索 ▾"}
        </button>
      </div>
      {savedOpen ? (
        <SavedSearchPanel
          searchKind="shot_search"
          currentQuery={savedQuery}
          canSave={committed != null}
          onLoad={loadSaved}
        />
      ) : null}

      {/* 降级提示（真实可见） */}
      {data ? (
        <DegradedNotice
          parserStatus={data.parser_status}
          embeddingStatus={data.embedding_status}
          degradationReasons={data.degradation_reasons}
        />
      ) : null}

      {/* 结果元信息 + 排序 */}
      {data ? (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500" data-testid="results-meta">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              共 <strong className="text-gray-700">{data.filtered_total}</strong> 条可检索
            </span>
            <span>
              本次匹配 <strong className="text-gray-700">{data.total}</strong>
              {data.truncated ? <span className="text-amber-600" title="候选被截断，存在更多匹配未进池">+（已截断）</span> : null}
            </span>
            <span>用时 {data.elapsed_ms}ms</span>
            <span>实际模式：{data.search_mode_used}</span>
          </div>
          <label className="flex items-center gap-1">
            <span>排序</span>
            <select
              data-testid="sort-select"
              value={form.sort}
              onChange={(e) => changeSort(e.target.value as SearchSort)}
              className="rounded border border-gray-300 px-2 py-1 text-xs"
            >
              {SORTS.map((s) => (
                <option key={s} value={s}>
                  {SORT_LABELS[s]}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}

      {/* 结果区 */}
      {committed == null ? (
        <Empty
          title="输入条件开始搜索"
          description="用自然语言描述你要找的镜头，或展开高级筛选按产品 / 场景 / 动作 / 风险等条件检索。"
        />
      ) : loading ? (
        <Loading rows={6} />
      ) : isError ? (
        <ErrorState message={errMsg} onRetry={() => void q.refetch()} />
      ) : data && data.items.length === 0 ? (
        data.total > 0 ? (
          // 当前页越界（候选仍有，但本页为空）：引导回第 1 页，不误报"没有结果"
          <Empty
            title="本页没有结果"
            description={`共有 ${data.total} 条匹配，但当前页码超出范围。`}
            action={
              <button
                type="button"
                data-testid="back-to-first-page"
                onClick={() => changePage(1)}
                className="rounded-md border border-brand px-3 py-1.5 text-sm font-medium text-brand hover:bg-brand-light"
              >
                返回第 1 页
              </button>
            }
          />
        ) : (
          <Empty
            title="没有匹配的镜头"
            description="可尝试：放宽或清除高级筛选、检查否定条件、去掉产品硬过滤、或查看右上角索引状态确认是否仍在建设中。"
          />
        )
      ) : data ? (
        <>
          <BundleBar
            selected={bundleSelected}
            totalDuration={bundleDuration}
            onClear={() => setSelectedIds(new Set())}
          />
          <div
            data-testid="results-grid"
            className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
            aria-busy={q.isFetching}
          >
            {data.items.map((item) => (
              <div key={item.shot_id} className="relative">
                <label
                  className="absolute left-1 top-1 z-10 flex items-center gap-1 rounded bg-white/90 px-1.5 py-0.5 text-[10px] font-medium text-gray-700 shadow-sm"
                  title="选择以加入 ZIP 打包"
                >
                  <input
                    type="checkbox"
                    data-testid={`bundle-select-${item.shot_id}`}
                    checked={selectedIds.has(item.shot_id)}
                    onChange={() => toggleSelect(item.shot_id)}
                    aria-label={`选择镜头 #${item.sequence_no} 加入打包`}
                  />
                  打包
                </label>
                <SearchResultCard
                  item={item}
                  selected={selectedShotId === item.shot_id}
                  onSelect={() => onOpenItem(item)}
                  onPreview={onPreview}
                />
              </div>
            ))}
          </div>

          {/* 分页 */}
          <div className="flex items-center justify-between border-t border-gray-100 px-1 py-3 text-sm text-gray-600">
            <span>
              第 {curPage} / {totalPages} 页{q.isFetching ? " · 更新中…" : ""}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                data-testid="page-prev"
                onClick={() => changePage(curPage - 1)}
                disabled={curPage <= 1 || q.isFetching}
                className="rounded-md border border-gray-300 bg-white px-3 py-1 disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-50"
              >
                上一页
              </button>
              <button
                type="button"
                data-testid="page-next"
                onClick={() => changePage(curPage + 1)}
                disabled={curPage >= totalPages || q.isFetching}
                className="rounded-md border border-gray-300 bg-white px-3 py-1 disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-50"
              >
                下一页
              </button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
