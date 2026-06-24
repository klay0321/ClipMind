"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AnalysisBanner } from "@/components/AnalysisBanner";
import { Pagination } from "@/components/Pagination";
import { ShotCard } from "@/components/ShotCard";
import { ShotDetail } from "@/components/ShotDetail";
import { TopNav } from "@/components/TopNav";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import {
  useAnalyzeMutation,
  useAssetShots,
  useShotAnalysis,
  useShots,
} from "@/lib/hooks";

const PAGE_SIZE = 24;

export function ShotsView({ assetId }: { assetId: number | null }) {
  const scoped = assetId != null;
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const analysisQ = useShotAnalysis(scoped ? assetId : null);
  const analyzeMut = useAnalyzeMutation();
  const assetShotsQ = useAssetShots(scoped ? assetId : null, page, PAGE_SIZE);
  const allShotsQ = useShots({ page, page_size: PAGE_SIZE }, !scoped);
  const shotsQ = scoped ? assetShotsQ : allShotsQ;

  const items = shotsQ.data?.items ?? [];
  useEffect(() => {
    if (items.length > 0 && !items.some((s) => s.id === selectedId)) {
      setSelectedId(items[0].id);
    }
    if (items.length === 0) setSelectedId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shotsQ.data]);

  const analysis = analysisQ.data;
  const isAnalyzing =
    analyzeMut.isPending ||
    analysis?.status === "queued" ||
    analysis?.status === "running";

  const handleAnalyze = () => {
    if (assetId == null) return;
    const retry =
      (analysis?.shot_count ?? 0) > 0 || analysis?.status === "failed";
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
          scoped
            ? "点击上方“开始分析”对该素材拆镜头"
            : "请到素材库对素材发起镜头分析"
        }
      />
    );
  } else {
    grid = (
      <>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((s) => (
            <ShotCard
              key={s.id}
              shot={s}
              selected={s.id === selectedId}
              onSelect={setSelectedId}
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

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <section className="space-y-3 lg:col-span-2">{grid}</section>
          <aside className="rounded-lg border border-gray-100 bg-white shadow-sm lg:sticky lg:top-4 lg:self-start">
            <ShotDetail shotId={selectedId} />
          </aside>
        </div>
      </main>
    </div>
  );
}
