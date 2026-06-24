"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AssetTable } from "@/components/AssetTable";
import { Pagination } from "@/components/Pagination";
import { PreviewModal } from "@/components/PreviewModal";
import { ScanBanner } from "@/components/ScanBanner";
import { SourceDirPanel } from "@/components/SourceDirPanel";
import { Toolbar } from "@/components/Toolbar";
import { TopNav } from "@/components/TopNav";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import type { ApiError } from "@/lib/api";
import {
  useAnalyzeAiMutation,
  useAnalyzeMutation,
  useAssets,
  useCreateSourceDirectory,
  useRescanMutation,
  useScanMutation,
  useScanStatus,
  useSourceDirectories,
  useUploadMutation,
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
  const [analyzingIds, setAnalyzingIds] = useState<Set<number>>(new Set());
  const [previewShotId, setPreviewShotId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
  const analyzeMutation = useAnalyzeMutation();
  const analyzeAiMutation = useAnalyzeAiMutation();
  const uploadMutation = useUploadMutation();

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

  const handleUpload = (file: File) => {
    uploadMutation.mutate(file, {
      onSuccess: (res) => {
        // 选中「上传素材」目录：useScanStatus 会轮询它，扫描完成由 scanState effect 自动刷新素材
        setSelectedDirId(res.source_directory_id);
      },
      onSettled: () => {
        void assetsQ.refetch();
        void dirsQ.refetch();
      },
    });
  };

  const handleAnalyze = (id: number, retry: boolean) => {
    setAnalyzingIds((prev) => new Set(prev).add(id));
    analyzeMutation.mutate(
      { assetId: id, retry },
      {
        onSettled: () => {
          setAnalyzingIds((prev) => {
            const next = new Set(prev);
            next.delete(id);
            return next;
          });
          void assetsQ.refetch();
        },
      },
    );
  };

  const handleAnalyzeAi = (id: number, retry: boolean) => {
    analyzeAiMutation.mutate(
      { assetId: id, retry },
      { onSettled: () => void assetsQ.refetch() },
    );
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
            ? "点「上传新素材」上传视频，或在上方添加只读源目录（/app/source）后扫描"
            : "点「上传新素材」上传，或把视频放入源目录后点“扫描”以建立索引"
        }
      />
    );
  } else {
    body = (
      <>
        <AssetTable
          assets={assetsQ.data!.items}
          rescanningIds={rescanningIds}
          analyzingIds={analyzingIds}
          onRescan={handleRescan}
          onAnalyze={handleAnalyze}
          onAnalyzeAi={handleAnalyzeAi}
          onPreview={setPreviewShotId}
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
      <TopNav active="assets" />
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
            <div className="flex flex-wrap items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept="video/*,.mp4,.mov,.mkv,.webm,.avi"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleUpload(f);
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                data-testid="upload-btn"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploadMutation.isPending}
                className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-brand-dark"
              >
                {uploadMutation.isPending ? "上传中…" : "↑ 上传新素材"}
              </button>
              <Toolbar
                q={qInput}
                onQChange={setQInput}
                status={status}
                onStatusChange={setStatus}
                onRefresh={() => void assetsQ.refetch()}
                refreshing={assetsQ.isFetching}
              />
            </div>
          </div>
          {uploadMutation.isError ? (
            <p className="px-4 pt-2 text-xs text-red-600">
              上传失败：{(uploadMutation.error as ApiError)?.message ?? "未知错误"}
            </p>
          ) : null}
          {body}
        </section>

        <p className="px-1 text-xs text-gray-400">
          说明：把视频放入只读源目录后「扫描」，或点「上传新素材」上传到独立上传区，均会建立索引。
          之后可对素材发起镜头分析（拆镜头 + 关键帧 / 缩略图 / 代理），并可发起 AI 画面理解（真实状态可见）。
          标签拆解、产品库与人工审核将在 PR-03B 提供。
        </p>
      </main>
      <PreviewModal shotId={previewShotId} onClose={() => setPreviewShotId(null)} />
    </div>
  );
}
