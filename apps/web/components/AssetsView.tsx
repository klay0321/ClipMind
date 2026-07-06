"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AssetDetailDrawer } from "@/components/AssetDetailDrawer";
import { AssetTable } from "@/components/AssetTable";
import { Pagination } from "@/components/Pagination";
import { PreviewModal } from "@/components/PreviewModal";
import { ScanBanner } from "@/components/ScanBanner";
import { SourceDirPanel } from "@/components/SourceDirPanel";
import { Toolbar } from "@/components/Toolbar";
import { TopNav } from "@/components/TopNav";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/overlay";
import { TableRowSkeleton } from "@/components/ui/Skeleton";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import type { ApiError } from "@/lib/api";
import {
  useAnalyzeAiMutation,
  useAnalyzeMutation,
  useAssets,
  useBatchAnalyze,
  useCreateSourceDirectory,
  useProcessingOverview,
  useRescanMutation,
  useScanMutation,
  useScanStatus,
  useSourceDirectories,
  useUploadMutation,
} from "@/lib/hooks";
import type { Asset, AssetStatus, SourceDirectoryCreate } from "@/lib/types";

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
  const [kind, setKind] = useState<"video" | "image">("video");
  const [batchMsg, setBatchMsg] = useState<string | null>(null);
  const [selectedDirId, setSelectedDirId] = useState<number | null>(null);
  const [rescanningIds, setRescanningIds] = useState<Set<number>>(new Set());
  const [analyzingIds, setAnalyzingIds] = useState<Set<number>>(new Set());
  const [previewShotId, setPreviewShotId] = useState<number | null>(null);
  const [sourceDrawerOpen, setSourceDrawerOpen] = useState(false);
  const [detailAsset, setDetailAsset] = useState<Asset | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const dirsQ = useSourceDirectories();
  const dirs = useMemo(() => dirsQ.data ?? [], [dirsQ.data]);

  useEffect(() => {
    if (selectedDirId == null && dirs.length > 0) setSelectedDirId(dirs[0].id);
  }, [dirs, selectedDirId]);

  useEffect(() => {
    setPage(1);
  }, [q, status, kind]);

  const assetsQ = useAssets({
    page,
    page_size: PAGE_SIZE,
    q: q || undefined,
    status: status || undefined,
    media_kind: kind,
  });
  const overviewQ = useProcessingOverview();
  const batchAnalyze = useBatchAnalyze();
  const scanStatusQ = useScanStatus(selectedDirId);
  const scanMutation = useScanMutation();
  const rescanMutation = useRescanMutation();
  const createMutation = useCreateSourceDirectory();
  const analyzeMutation = useAnalyzeMutation();
  const analyzeAiMutation = useAnalyzeAiMutation();
  const uploadMutation = useUploadMutation();

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

  const total = assetsQ.data?.total ?? 0;

  let body: React.ReactNode;
  if (assetsQ.isLoading) {
    body = <TableRowSkeleton rows={6} cols={4} />;
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
            ? "点「上传新素材」上传视频，或打开「素材来源设置」添加来源目录后扫描建立索引。"
            : "点「上传新素材」上传，或在「素材来源设置」中对来源目录点「扫描」以建立索引。"
        }
        action={
          <Button variant="secondary" onClick={() => setSourceDrawerOpen(true)}>
            素材来源设置
          </Button>
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
          onShowDetail={setDetailAsset}
        />
        <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
      </>
    );
  }

  return (
    <div>
      <TopNav active="assets" />
      <main className="mx-auto max-w-7xl space-y-4 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-gray-900">素材统一管理</h1>
            <p className="mt-1 text-sm text-gray-500">
              统一上传、查看与继续分析原始视频素材。
              {assetsQ.data ? `已上传 ${total} 个素材。` : ""}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept={
                kind === "image"
                  ? "image/*,.jpg,.jpeg,.png,.webp"
                  : "video/*,.mp4,.mov,.mkv,.webm,.avi"
              }
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleUpload(f);
                e.target.value = "";
              }}
            />
            <Button
              variant="primary"
              data-testid="upload-btn"
              onClick={() => fileInputRef.current?.click()}
              loading={uploadMutation.isPending}
            >
              {uploadMutation.isPending ? "上传中…" : "↑ 上传新素材"}
            </Button>
            <Button
              variant="secondary"
              disabled={isScanning}
              onClick={() => setSourceDrawerOpen(true)}
            >
              {isScanning ? "扫描中…" : "扫描素材目录"}
            </Button>
          </div>
        </div>

        {uploadMutation.isError ? (
          <p role="alert" className="text-sm text-red-600">
            上传失败：{(uploadMutation.error as ApiError)?.message ?? "未知错误"}
          </p>
        ) : null}

        <ScanBanner scanStatus={scanStatusQ.data} pending={scanMutation.isPending} />

        {/* AAP：全局处理进度（有活动任务才显示；空闲时只留统计一行） */}
        {overviewQ.data ? (
          <div
            className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-gray-100 bg-white px-4 py-2 text-xs text-gray-600"
            data-testid="processing-overview"
          >
            <span className="font-medium text-gray-700">全库处理状态</span>
            <span>
              视频 {overviewQ.data.totals.videos_with_shots}/{overviewQ.data.totals.videos_total} 已拆镜头
            </span>
            <span>镜头 {overviewQ.data.totals.shots_ai_labeled}/{overviewQ.data.totals.shots_ready} 已 AI 理解</span>
            <span>可搜索 {overviewQ.data.totals.searchable_docs}</span>
            {overviewQ.data.shots.queued + overviewQ.data.shots.running > 0 ? (
              <span className="text-amber-600" data-testid="overview-shots-active">
                拆镜头进行 {overviewQ.data.shots.running} / 排队 {overviewQ.data.shots.queued}
              </span>
            ) : null}
            {overviewQ.data.ai.queued + overviewQ.data.ai.running > 0 ? (
              <span className="text-amber-600">
                AI 理解进行 {overviewQ.data.ai.running} / 排队 {overviewQ.data.ai.queued}
              </span>
            ) : null}
            {overviewQ.data.config.auto_analyze_on_scan ? (
              <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700" data-testid="auto-badge">
                自动分析已开启
              </span>
            ) : null}
            {overviewQ.data.config.ai_daily_budget > 0 ? (
              <span className="text-gray-400">
                AI 今日 {overviewQ.data.config.ai_spent_today.toFixed(2)} /
                预算 {overviewQ.data.config.ai_daily_budget.toFixed(2)}
              </span>
            ) : null}
          </div>
        ) : null}

        {batchMsg ? (
          <p className="rounded bg-emerald-50 px-3 py-2 text-xs text-emerald-700" data-testid="batch-msg">
            {batchMsg}
          </p>
        ) : null}

        <section className="rounded-lg border border-gray-100 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
            <div className="flex items-center gap-3">
              <h2 className="text-base font-semibold">全部原始素材</h2>
              <div className="flex gap-1" role="tablist" aria-label="媒体类型">
                {(["video", "image"] as const).map((k) => (
                  <button
                    key={k}
                    type="button"
                    role="tab"
                    aria-selected={kind === k}
                    data-testid={`kind-tab-${k}`}
                    onClick={() => setKind(k)}
                    className={
                      kind === k
                        ? "rounded-full border border-brand bg-brand/10 px-3 py-1 text-xs font-medium text-brand"
                        : "rounded-full border border-gray-300 px-3 py-1 text-xs text-gray-600 hover:bg-gray-50"
                    }
                  >
                    {k === "video" ? "视频" : "图片"}
                  </button>
                ))}
              </div>
              {kind === "video" && dirs.length > 0 ? (
                <Button
                  size="sm"
                  variant="secondary"
                  data-testid="batch-analyze-btn"
                  loading={batchAnalyze.isPending}
                  onClick={async () => {
                    // 逐目录显式提交（API 不做全库隐式操作）
                    let shots = 0;
                    let ai = 0;
                    let truncated = false;
                    let failed = 0;
                    for (const d of dirs) {
                      try {
                        const r = await batchAnalyze.mutateAsync({
                          source_directory_id: d.id,
                          stages: ["shots", "ai"],
                        });
                        shots += r.enqueued_shots;
                        ai += r.enqueued_ai;
                        truncated = truncated || r.truncated;
                      } catch {
                        failed += 1;
                      }
                    }
                    setBatchMsg(
                      `一键补齐已提交：入队拆镜头 ${shots}、AI 理解 ${ai}` +
                        (truncated ? "（单批超上限已截断，处理完可再点一次）" : "") +
                        (failed ? `；${failed} 个目录提交失败` : "") +
                        "。进度见上方全库处理状态。",
                    );
                  }}
                >
                  一键补齐分析
                </Button>
              ) : null}
            </div>
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
          提示：把视频放入来源目录后「扫描」，或直接「上传新素材」，都会建立索引。
          随后可对素材发起镜头分析（拆镜头 + 关键帧 / 缩略图 / 代理），并发起 AI 画面理解。
          页面只展示真实处理状态，不会伪造 AI 结果。
        </p>
      </main>

      <Drawer
        open={sourceDrawerOpen}
        onClose={() => setSourceDrawerOpen(false)}
        title="素材来源设置"
        widthClass="max-w-xl"
      >
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
      </Drawer>

      <AssetDetailDrawer
        asset={detailAsset}
        onClose={() => setDetailAsset(null)}
        onAnalyze={handleAnalyze}
        onAnalyzeAi={handleAnalyzeAi}
        onPreview={(shotId) => {
          setDetailAsset(null);
          setPreviewShotId(shotId);
        }}
      />

      <PreviewModal shotId={previewShotId} onClose={() => setPreviewShotId(null)} />
    </div>
  );
}
