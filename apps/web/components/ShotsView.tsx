"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AnalysisBanner } from "@/components/AnalysisBanner";
import { Pagination } from "@/components/Pagination";
import { ShotCard } from "@/components/ShotCard";
import { ShotDetail } from "@/components/ShotDetail";
import { TopNav } from "@/components/TopNav";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { exportDownloadUrl } from "@/lib/api";
import {
  useAnalyzeMutation,
  useAssetShots,
  useExportMutation,
  useExportStatus,
  useShotAnalysis,
  useShots,
} from "@/lib/hooks";
import type { Shot } from "@/lib/types";

const PAGE_SIZE = 24;

type SortKey = "seq" | "longest" | "shortest";

// AI 筛选维度（PR-03 引入大模型理解后启用）。当前禁用，不伪造数据。
const AI_FILTER_GROUPS = ["产品", "场景 / 镜别", "画面标签", "口播 / 字幕"];

function FilterSidebar({
  sort,
  onSort,
}: {
  sort: SortKey;
  onSort: (k: SortKey) => void;
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
  return (
    <aside className="shrink-0 space-y-4 lg:w-52">
      <div className="rounded-lg border border-gray-100 bg-white p-3 shadow-sm">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">排序</h3>
        <div className="flex flex-wrap gap-1.5">
          {sortBtn("seq", "按序号")}
          {sortBtn("longest", "时长长→短")}
          {sortBtn("shortest", "时长短→长")}
        </div>
      </div>
      <div className="rounded-lg border border-gray-100 bg-white p-3 shadow-sm">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
          智能筛选
        </h3>
        <div className="space-y-2">
          {AI_FILTER_GROUPS.map((g) => (
            <div key={g} className="rounded-md border border-dashed border-gray-200 px-2 py-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">{g}</span>
                <span className="rounded bg-gray-100 px-1 py-0.5 text-[10px] text-gray-400">
                  待 AI
                </span>
              </div>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-gray-400">
          按画面 / 产品 / 标签筛选将在接入 AI 理解后启用，当前不展示占位假数据。
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

  const analysisQ = useShotAnalysis(scoped ? assetId : null);
  const analyzeMut = useAnalyzeMutation();
  const assetShotsQ = useAssetShots(scoped ? assetId : null, page, PAGE_SIZE);
  const allShotsQ = useShots({ page, page_size: PAGE_SIZE }, !scoped);
  const shotsQ = scoped ? assetShotsQ : allShotsQ;

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
    grid = <Loading />;
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
        title={scoped ? "尚未拆镜头" : "还没有任何镜头"}
        description={
          scoped ? "点击上方“开始分析”对该素材拆镜头" : "请到素材库对素材发起镜头分析"
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
              ← 返回素材库
            </Link>
            <h1 className="text-base font-semibold">
              {scoped ? `素材 #${assetId} 的镜头` : "全部镜头"}
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

        {scoped ? <AnalysisBanner analysis={analysis} pending={analyzeMut.isPending} /> : null}
        {exportMut.isError ? (
          <p className="text-xs text-red-600">
            导出失败：{(exportMut.error as Error)?.message ?? "未知错误"}
          </p>
        ) : null}

        <div className="flex flex-col gap-4 lg:flex-row">
          <FilterSidebar sort={sort} onSort={setSort} />
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
