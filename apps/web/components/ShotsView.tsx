"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AnalysisBanner } from "@/components/AnalysisBanner";
import { Pagination } from "@/components/Pagination";
import { ReviewSummaryBar } from "@/components/ReviewSummaryBar";
import { ShotCard } from "@/components/ShotCard";
import { ShotDetail } from "@/components/ShotDetail";
import { ShotCompletenessBar } from "@/components/shots/ShotCompletenessBar";
import { TopNav } from "@/components/TopNav";
import { Button } from "@/components/ui/Button";
import { CardGridSkeleton } from "@/components/ui/Skeleton";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { exportDownloadUrl } from "@/lib/api";
import {
  useAnalyzeMutation,
  useAssetShots,
  useExportMutation,
  useExportStatus,
  useProducts,
  useShotAnalysis,
  useShotFilterOptions,
  useShots,
  useShotSearch,
} from "@/lib/hooks";
import type { Product, Shot } from "@/lib/types";

const PAGE_SIZE = 24;

type SortKey = "seq" | "longest" | "shortest";

// 智能筛选维度（PR-03B 起：走 /shot-search 投影，有效标签 = 人工优先，rejected/unable 默认排除）
type Filters = {
  review_status?: string;
  has_ai_result?: boolean;
  stale?: boolean;
  risk?: string;
  scene?: string;
  action?: string;
  shot_type?: string;
  marketing_use?: string;
  product_id?: number;
  include_excluded?: boolean;
};

const REVIEW_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部" },
  { value: "unreviewed", label: "未审核" },
  { value: "pending_review", label: "待审核" },
  { value: "confirmed", label: "已确认" },
  { value: "modified", label: "已修改" },
  { value: "rejected", label: "已驳回" },
  { value: "unable", label: "无法判断" },
];

function FilterSidebar({
  sort,
  onSort,
  filters,
  onFilters,
  onClear,
  products,
  options,
}: {
  sort: SortKey;
  onSort: (k: SortKey) => void;
  filters: Filters;
  onFilters: (f: Filters) => void;
  onClear: () => void;
  products: Product[];
  options: Record<string, string[]>;
}) {
  const sortBtn = (k: SortKey, label: string) => (
    <button
      type="button"
      onClick={() => onSort(k)}
      className={`rounded-md px-2 py-1 text-xs ${
        sort === k ? "bg-brand text-white" : "border border-gray-200 text-gray-600 hover:bg-gray-50"
      }`}
    >
      {label}
    </button>
  );
  const set = (patch: Partial<Filters>) => onFilters({ ...filters, ...patch });
  // 字符串维度下拉：选项来自真实 /search/suggestions（按 type 分组），不前端伪造
  const strSelect = (
    key: "scene" | "action" | "shot_type" | "marketing_use",
    label: string,
    values: string[],
    testid?: string,
  ) => (
    <label className="block">
      <span className="text-gray-500">{label}</span>
      <select
        data-testid={testid}
        value={filters[key] ?? ""}
        onChange={(e) => set({ [key]: e.target.value || undefined })}
        className="mt-0.5 w-full rounded border border-gray-200 px-1.5 py-1 text-xs"
      >
        <option value="">全部</option>
        {values.map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </select>
    </label>
  );
  const text = (key: "risk", placeholder: string, testid?: string) => (
    <label className="block">
      <span className="text-gray-500">{placeholder}</span>
      <input
        data-testid={testid}
        placeholder={placeholder}
        value={filters[key] ?? ""}
        onChange={(e) => set({ [key]: e.target.value || undefined })}
        className="mt-0.5 w-full rounded border border-gray-200 px-1.5 py-1 text-xs"
      />
    </label>
  );
  const check = (
    key: "has_ai_result" | "stale" | "include_excluded",
    label: string,
  ) => (
    <label className="flex items-center gap-1.5 text-gray-600">
      <input
        type="checkbox"
        checked={filters[key] === true}
        onChange={(e) => set({ [key]: e.target.checked ? true : undefined })}
      />
      {label}
    </label>
  );
  return (
    <aside className="shrink-0 space-y-4 lg:w-56">
      <div className="rounded-lg border border-gray-100 bg-white p-3 shadow-sm">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">排序</h3>
        <div className="flex flex-wrap gap-1.5">
          {sortBtn("seq", "按序号")}
          {sortBtn("longest", "时长长→短")}
          {sortBtn("shortest", "时长短→长")}
        </div>
      </div>
      <div className="rounded-lg border border-gray-100 bg-white p-3 shadow-sm" data-testid="ai-filters">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">筛选镜头</h3>
          <button
            type="button"
            data-testid="filter-clear"
            onClick={onClear}
            className="text-[11px] text-gray-400 hover:text-brand"
          >
            清空
          </button>
        </div>
        <div className="space-y-2 text-xs">
          <label className="block">
            <span className="text-gray-500">产品</span>
            <select
              data-testid="filter-product"
              value={filters.product_id ?? ""}
              onChange={(e) => set({ product_id: e.target.value ? Number(e.target.value) : undefined })}
              className="mt-0.5 w-full rounded border border-gray-200 px-1.5 py-1 text-xs"
            >
              <option value="">全部产品</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          {strSelect("marketing_use", "营销用途", options.marketing ?? [])}
          {strSelect("scene", "场景", options.scene ?? [])}
          {strSelect("action", "动作", options.action ?? [])}
          {strSelect("shot_type", "镜头类型", options.shot_type ?? [])}
          <label className="block">
            <span className="text-gray-500">审核状态</span>
            <select
              data-testid="filter-review-status"
              value={filters.review_status ?? ""}
              onChange={(e) => set({ review_status: e.target.value || undefined })}
              className="mt-0.5 w-full rounded border border-gray-200 px-1.5 py-1 text-xs"
            >
              {REVIEW_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          {text("risk", "风险标记", "filter-risk")}
          {check("has_ai_result", "仅已 AI 分析")}
          {check("stale", "仅过期需复审")}
          {check("include_excluded", "含已驳回 / 无法判断")}
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-gray-400">
          下拉值来自真实标签聚合；需要自然语言检索请前往「智能匹配」。
        </p>
      </div>
    </aside>
  );
}

export function ShotsView({ assetId }: { assetId: number | null }) {
  const scoped = assetId != null;
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [sort, setSort] = useState<SortKey>("seq");
  const [filters, setFilters] = useState<Filters>({});
  const filterActive = Object.values(filters).some((v) => v != null && v !== "");

  const analysisQ = useShotAnalysis(scoped ? assetId : null);
  const analyzeMut = useAnalyzeMutation();
  const productsQ = useProducts();
  const filterOptionsQ = useShotFilterOptions();
  const assetShotsQ = useAssetShots(scoped && !filterActive ? assetId : null, page, PAGE_SIZE);
  const allShotsQ = useShots({ page, page_size: PAGE_SIZE }, !scoped && !filterActive);
  const searchQ = useShotSearch(
    {
      asset_id: scoped ? (assetId as number) : undefined,
      ...filters,
      sort: "sequence",
      page,
      page_size: PAGE_SIZE,
    },
    filterActive,
  );
  const shotsQ = filterActive ? searchQ : scoped ? assetShotsQ : allShotsQ;

  // 筛选变化时回到第一页
  useEffect(() => {
    setPage(1);
  }, [filters]);

  // 下载：导出该镜头片段，完成后触发浏览器下载
  const exportMut = useExportMutation();
  const [exportShotId, setExportShotId] = useState<number | null>(null);
  const [exportId, setExportId] = useState<number | null>(null);
  const exportStatusQ = useExportStatus(exportId);

  useEffect(() => {
    const e = exportStatusQ.data;
    if (!e) return;
    if (e.status === "completed" && e.has_file) {
      window.location.href = exportDownloadUrl(e.id);
      setExportShotId(null);
      setExportId(null);
    } else if (e.status === "failed") {
      setExportShotId(null);
      setExportId(null);
    }
  }, [exportStatusQ.data]);

  const handleDownload = (shotId: number) => {
    setExportShotId(shotId);
    exportMut.mutate(
      { shotId },
      {
        onSuccess: (r) => setExportId(r.export_id),
        onError: () => setExportShotId(null),
      },
    );
  };

  const rawItems = useMemo(() => shotsQ.data?.items ?? [], [shotsQ.data]);
  const items = useMemo(() => {
    const copy: Shot[] = [...rawItems];
    if (sort === "longest") copy.sort((a, b) => b.duration - a.duration);
    else if (sort === "shortest") copy.sort((a, b) => a.duration - b.duration);
    return copy;
  }, [rawItems, sort]);

  useEffect(() => {
    if (rawItems.length > 0 && !rawItems.some((s) => s.id === selectedId)) {
      setSelectedId(rawItems[0].id);
    }
    if (rawItems.length === 0) setSelectedId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shotsQ.data]);

  const analysis = analysisQ.data;
  const isAnalyzing =
    analyzeMut.isPending || analysis?.status === "queued" || analysis?.status === "running";

  const handleAnalyze = () => {
    if (assetId == null) return;
    const retry = (analysis?.shot_count ?? 0) > 0 || analysis?.status === "failed";
    analyzeMut.mutate({ assetId, retry });
  };

  let grid: React.ReactNode;
  if (shotsQ.isLoading) {
    grid = <CardGridSkeleton count={6} className="sm:grid-cols-3 xl:grid-cols-3" />;
  } else if (shotsQ.isError) {
    grid = (
      <ErrorState
        message={(shotsQ.error as Error)?.message ?? "加载镜头失败"}
        onRetry={() => void shotsQ.refetch()}
      />
    );
  } else if (items.length === 0) {
    grid = (
      <Empty
        title={filterActive ? "没有符合筛选条件的镜头" : scoped ? "尚未拆镜头" : "还没有任何镜头"}
        description={
          filterActive
            ? "调整或清空左侧智能筛选条件"
            : scoped
              ? "点击上方“开始分析”对该素材拆镜头"
              : "请到素材管理对素材发起镜头分析"
        }
      />
    );
  } else {
    grid = (
      <>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {items.map((s) => (
            <ShotCard
              key={s.id}
              shot={s}
              selected={s.id === selectedId}
              onSelect={setSelectedId}
              onDownload={handleDownload}
              downloading={exportShotId === s.id}
            />
          ))}
        </div>
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={shotsQ.data!.total}
          onPageChange={setPage}
        />
      </>
    );
  }

  return (
    <div>
      <TopNav active="shots" />
      <main className="mx-auto max-w-7xl space-y-4 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <Link href="/assets" className="text-sm text-gray-500 hover:text-gray-800">
              ← 返回素材管理
            </Link>
            <h1 className="text-base font-semibold">
              {scoped ? `素材 #${assetId} 的镜头` : "AI 镜头拆解"}
            </h1>
            {shotsQ.data ? (
              <span className="text-xs text-gray-400">共 {shotsQ.data.total} 个镜头</span>
            ) : null}
          </div>
          {scoped ? (
            <button
              type="button"
              data-testid="analyze-btn"
              onClick={handleAnalyze}
              disabled={isAnalyzing}
              className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-brand-dark"
            >
              {isAnalyzing
                ? "分析中…"
                : (analysis?.shot_count ?? 0) > 0 || analysis?.status === "failed"
                  ? "重新分析"
                  : "开始分析"}
            </button>
          ) : null}
        </div>

        {scoped ? <ReviewSummaryBar assetId={assetId} /> : null}
        {scoped ? <AnalysisBanner analysis={analysis} pending={analyzeMut.isPending} /> : null}
        {exportMut.isError ? (
          <p className="text-xs text-red-600">
            导出失败：{(exportMut.error as Error)?.message ?? "未知错误"}
          </p>
        ) : null}

        {!scoped ? <ShotCompletenessBar /> : null}

        <div className="flex flex-col gap-4 lg:flex-row">
          <FilterSidebar
            sort={sort}
            onSort={setSort}
            filters={filters}
            onFilters={setFilters}
            onClear={() => setFilters({})}
            products={productsQ.data ?? []}
            options={filterOptionsQ.data ?? {}}
          />
          <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-3">
            <section className="space-y-3 lg:col-span-2">{grid}</section>
            <aside className="rounded-lg border border-gray-100 bg-white shadow-sm lg:sticky lg:top-4 lg:self-start">
              <ShotDetail shotId={selectedId} />
            </aside>
          </div>
        </div>
      </main>
    </div>
  );
}
