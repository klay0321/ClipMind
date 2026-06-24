"use client";

import { useEffect, useMemo, useState } from "react";

import { AssetTable } from "@/components/AssetTable";
import { Pagination } from "@/components/Pagination";
import { ScanBanner } from "@/components/ScanBanner";
import { SourceDirPanel } from "@/components/SourceDirPanel";
import { Toolbar } from "@/components/Toolbar";
import { TopNav } from "@/components/TopNav";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import type { ApiError } from "@/lib/api";
import {
  useAssets,
  useCreateSourceDirectory,
  useRescanMutation,
  useScanMutation,
  useScanStatus,
  useSourceDirectories,
} from "@/lib/hooks";
import type { AssetStatus, SourceDirectoryCreate } from "@/lib/types";

const PAGE_SIZE = 20;

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

export function AssetsView() {
  const [page, setPage] = useState(1);
  const [qInput, setQInput] = useState("");
  const q = useDebounce(qInput, 400);
  const [status, setStatus] = useState<AssetStatus | "">("");
  const [selectedDirId, setSelectedDirId] = useState<number | null>(null);
  const [rescanningIds, setRescanningIds] = useState<Set<number>>(new Set());

  const dirsQ = useSourceDirectories();
  const dirs = useMemo(() => dirsQ.data ?? [], [dirsQ.data]);

  useEffect(() => {
    if (selectedDirId == null && dirs.length > 0) setSelectedDirId(dirs[0].id);
  }, [dirs, selectedDirId]);

  // 筛选变化时回到第一页
  useEffect(() => {
    setPage(1);
  }, [q, status]);

  const assetsQ = useAssets({
    page,
    page_size: PAGE_SIZE,
    q: q || undefined,
    status: status || undefined,
  });
  const scanStatusQ = useScanStatus(selectedDirId);
  const scanMutation = useScanMutation();
  const rescanMutation = useRescanMutation();
  const createMutation = useCreateSourceDirectory();

  // 扫描结束后刷新素材与目录
  const scanState = scanStatusQ.data?.scan_status;
  useEffect(() => {
    if (scanState === "completed" || scanState === "failed") {
      void assetsQ.refetch();
      void dirsQ.refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanState]);

  const isScanning =
    scanMutation.isPending || scanState === "scanning" || scanState === "queued";

  const handleScan = (id: number) => {
    setSelectedDirId(id);
    scanMutation.mutate(id);
  };

  const handleRescan = (id: number) => {
    setRescanningIds((prev) => new Set(prev).add(id));
    rescanMutation.mutate(id, {
      onSettled: () => {
        setRescanningIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
        void assetsQ.refetch();
      },
    });
  };

  const handleCreate = (payload: SourceDirectoryCreate) => {
    createMutation.mutate(payload, {
      onSuccess: (sd) => setSelectedDirId(sd.id),
    });
  };

  let body: React.ReactNode;
  if (assetsQ.isLoading) {
    body = <Loading />;
  } else if (assetsQ.isError) {
    body = (
      <ErrorState
        message={(assetsQ.error as Error)?.message ?? "请求失败"}
        onRetry={() => void assetsQ.refetch()}
      />
    );
  } else if ((assetsQ.data?.items.length ?? 0) === 0) {
    body = (
      <Empty
        title={dirs.length === 0 ? "还没有素材目录" : "暂无素材"}
        description={
          dirs.length === 0
            ? "请先在上方添加素材目录（/app/source）"
            : "把视频放入只读源目录后，点击“扫描”以建立索引"
        }
      />
    );
  } else {
    body = (
      <>
        <AssetTable
          assets={assetsQ.data!.items}
          rescanningIds={rescanningIds}
          onRescan={handleRescan}
        />
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={assetsQ.data!.total}
          onPageChange={setPage}
        />
      </>
    );
  }

  return (
    <div>
      <TopNav />
      <main className="mx-auto max-w-7xl space-y-4 p-4">
        <SourceDirPanel
          dirs={dirs}
          selectedDirId={selectedDirId}
          onSelect={setSelectedDirId}
          onScan={handleScan}
          scanningDirId={isScanning ? selectedDirId : null}
          onCreate={handleCreate}
          creating={createMutation.isPending}
          createError={(createMutation.error as ApiError | null)?.message ?? null}
        />

        <ScanBanner scanStatus={scanStatusQ.data} pending={scanMutation.isPending} />

        <section className="rounded-lg border border-gray-100 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
            <h2 className="text-base font-semibold">全部原始素材</h2>
            <Toolbar
              q={qInput}
              onQChange={setQInput}
              status={status}
              onStatusChange={setStatus}
              onRefresh={() => void assetsQ.refetch()}
              refreshing={assetsQ.isFetching}
            />
          </div>
          {body}
        </section>

        <p className="px-1 text-xs text-gray-400">
          说明：本页为只读素材索引。镜头拆分、关键帧、AI 标签等将在后续版本提供。
        </p>
      </main>
    </div>
  );
}
