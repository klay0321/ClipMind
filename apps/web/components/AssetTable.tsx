"use client";

import Link from "next/link";

import { ProcessingChain } from "@/components/assets/ProcessingChain";
import { AssetStatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Menu, type MenuItem } from "@/components/ui/Menu";
import { assetPosterUrl, shotThumbnailUrl } from "@/lib/api";
import { formatBytes, formatDuration } from "@/lib/format";
import type { Asset } from "@/lib/types";

function Cover({ asset, onPreview }: { asset: Asset; onPreview: (shotId: number) => void }) {
  // 已分析：用首镜头关键帧（可点 ▶ 预览代理）
  if (asset.cover_shot_id != null) {
    return (
      <button
        type="button"
        data-testid="asset-cover"
        onClick={() => onPreview(asset.cover_shot_id as number)}
        className="group relative h-12 w-20 shrink-0 overflow-hidden rounded bg-gray-900"
        title="预览"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={shotThumbnailUrl(asset.cover_shot_id)}
          alt={`${asset.filename} 封面`}
          className="h-full w-full object-cover opacity-90 group-hover:opacity-100"
          loading="lazy"
        />
        <span className="absolute inset-0 flex items-center justify-center">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-black/50 text-white">
            ▶
          </span>
        </span>
      </button>
    );
  }
  // 未分析但有海报：用 FFmpeg 抽帧的素材海报（静态，无代理可播）
  if (asset.has_poster) {
    return (
      <div
        data-testid="asset-cover-poster"
        className="h-12 w-20 shrink-0 overflow-hidden rounded bg-gray-100"
        title="素材海报（分析后可逐镜头预览）"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={assetPosterUrl(asset.id)}
          alt={`${asset.filename} 海报`}
          className="h-full w-full object-cover"
          loading="lazy"
        />
      </div>
    );
  }
  return (
    <div className="flex h-12 w-20 shrink-0 items-center justify-center rounded bg-gray-100 text-[10px] text-gray-400">
      待生成封面
    </div>
  );
}

function AssetActions({
  asset,
  analyzing,
  rescanning,
  onAnalyze,
  onAnalyzeAi,
  onRescan,
  onPreview,
  onShowDetail,
}: {
  asset: Asset;
  analyzing: boolean;
  rescanning: boolean;
  onAnalyze: (id: number, retry: boolean) => void;
  onAnalyzeAi?: (id: number, retry: boolean) => void;
  onRescan: (id: number) => void;
  onPreview: (shotId: number) => void;
  onShowDetail?: (asset: Asset) => void;
}) {
  // 图片没有镜头概念：不提供拆镜头/AI 分析入口（后端对图片 analyze 返回 422）
  if (asset.media_kind === "image") {
    const imageMenu: MenuItem[] = [
      {
        key: "rescan",
        label: rescanning ? "重扫中…" : "重新扫描",
        disabled: rescanning,
        onSelect: () => onRescan(asset.id),
      },
    ];
    return (
      <div className="flex items-center justify-end gap-1.5">
        {onShowDetail ? (
          <Button size="sm" variant="secondary" onClick={() => onShowDetail(asset)}>
            查看详情
          </Button>
        ) : null}
        <Link
          href="/product-media"
          className="inline-flex items-center whitespace-nowrap rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
        >
          去标注产品
        </Link>
        <Menu items={imageMenu} align="right" triggerAriaLabel={`${asset.filename} 更多操作`} />
      </div>
    );
  }
  const isProcessing =
    asset.status === "processing" ||
    asset.analysis_status === "queued" ||
    asset.analysis_status === "running" ||
    analyzing;
  const hasShots = asset.shot_count > 0;
  const failed = asset.analysis_status === "failed";
  const disabledAnalyze = isProcessing || asset.status === "source_missing";

  const aiStatus = asset.ai_analysis_status ?? null;
  const aiActive = aiStatus === "queued" || aiStatus === "running";
  const aiAnalyzed = (asset.ai_analyzed_total ?? 0) > 0;
  const disabledAi = aiActive || !hasShots || asset.status === "source_missing";

  let primaryLabel = "开始分析";
  if (isProcessing) primaryLabel = "分析中…";
  else if (failed) primaryLabel = "重试分析";
  else if (hasShots) primaryLabel = "继续分析";

  // 次要操作收进 ⋮ 菜单，避免每行堆同权重按钮
  const menuItems: MenuItem[] = [];
  if (onAnalyzeAi && hasShots) {
    menuItems.push({
      key: "ai",
      label: aiActive ? "AI 分析中…" : aiAnalyzed ? "继续 AI 分析" : "AI 分析",
      disabled: disabledAi,
      onSelect: () => onAnalyzeAi(asset.id, aiAnalyzed),
    });
  }
  menuItems.push({
    key: "rescan",
    label: rescanning ? "重扫中…" : "重新扫描",
    disabled: rescanning,
    onSelect: () => onRescan(asset.id),
  });
  if (onShowDetail) {
    menuItems.push({ key: "detail", label: "查看详情", onSelect: () => onShowDetail(asset) });
  }

  return (
    <div className="flex items-center justify-end gap-1.5">
      <Button
        size="sm"
        variant="primary"
        onClick={() => onAnalyze(asset.id, hasShots || failed)}
        disabled={disabledAnalyze}
      >
        {primaryLabel}
      </Button>
      {hasShots ? (
        <Link
          href={`/shots?asset_id=${asset.id}`}
          className="inline-flex items-center whitespace-nowrap rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
        >
          查看镜头
        </Link>
      ) : null}
      {asset.cover_shot_id != null ? (
        <Button size="sm" variant="secondary" onClick={() => onPreview(asset.cover_shot_id as number)}>
          预览
        </Button>
      ) : null}
      <Menu items={menuItems} align="right" triggerAriaLabel={`${asset.filename} 更多操作`} />
    </div>
  );
}

export function AssetTable({
  assets,
  rescanningIds,
  analyzingIds,
  onRescan,
  onAnalyze,
  onAnalyzeAi,
  onPreview,
  onShowDetail,
}: {
  assets: Asset[];
  rescanningIds: Set<number>;
  analyzingIds: Set<number>;
  onRescan: (id: number) => void;
  onAnalyze: (id: number, retry: boolean) => void;
  onAnalyzeAi?: (id: number, retry: boolean) => void;
  onPreview: (shotId: number) => void;
  onShowDetail?: (asset: Asset) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-left text-sm">
        <thead className="border-b border-gray-100 text-xs uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-4 py-3 font-medium">封面</th>
            <th className="px-4 py-3 font-medium">文件名</th>
            <th className="px-4 py-3 font-medium">产品</th>
            <th className="px-4 py-3 font-medium">时长</th>
            <th className="px-4 py-3 font-medium">镜头数</th>
            <th className="px-4 py-3 font-medium">状态</th>
            <th className="px-4 py-3 text-right font-medium">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {assets.map((a) => (
            <tr key={a.id} className="align-top hover:bg-gray-50/60">
              <td className="px-4 py-3">
                <Cover asset={a} onPreview={onPreview} />
              </td>
              <td className="max-w-[20rem] px-4 py-3">
                {onShowDetail ? (
                  <button
                    type="button"
                    onClick={() => onShowDetail(a)}
                    className="block max-w-full truncate text-left font-medium text-gray-900 hover:text-brand-dark hover:underline"
                    title={a.filename}
                  >
                    {a.filename}
                  </button>
                ) : (
                  <div className="truncate font-medium text-gray-900" title={a.filename}>
                    {a.filename}
                  </div>
                )}
                <div className="mt-0.5 text-xs text-gray-400">
                  {formatBytes(a.file_size)} ·{" "}
                  <span className="break-all">{a.relative_path}</span>
                </div>
                {a.status === "error" && a.error_message ? (
                  <div className="mt-1 text-xs text-red-600">原因：{a.error_message}</div>
                ) : null}
              </td>
              <td className="px-4 py-3">
                {a.product_names && a.product_names.length > 0 ? (
                  <div className="flex max-w-[12rem] flex-wrap gap-1">
                    {a.product_names.slice(0, 3).map((n) => (
                      <span
                        key={n}
                        className="rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700"
                        data-testid="asset-product-chip"
                      >
                        {n}
                      </span>
                    ))}
                    {a.product_names.length > 3 ? (
                      <span className="text-xs text-gray-400">+{a.product_names.length - 3}</span>
                    ) : null}
                  </div>
                ) : (
                  <Link href="/product-media" className="text-xs text-gray-400 hover:text-brand hover:underline">
                    去标注
                  </Link>
                )}
              </td>
              <td className="px-4 py-3 text-gray-700">
                {a.media_kind === "image" ? "—" : formatDuration(a.duration)}
              </td>
              <td className="px-4 py-3 text-gray-700">
                {a.media_kind === "image"
                  ? "图片"
                  : a.shot_count > 0
                    ? `${a.shot_count} 个镜头`
                    : "未拆镜头"}
              </td>
              <td className="px-4 py-3">
                <div className="space-y-1.5">
                  <AssetStatusBadge status={a.status} />
                  {a.media_kind === "image" ? null : <ProcessingChain asset={a} />}
                </div>
              </td>
              <td className="px-4 py-3">
                <AssetActions
                  asset={a}
                  analyzing={analyzingIds.has(a.id)}
                  rescanning={rescanningIds.has(a.id)}
                  onAnalyze={onAnalyze}
                  onAnalyzeAi={onAnalyzeAi}
                  onRescan={onRescan}
                  onPreview={onPreview}
                  onShowDetail={onShowDetail}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
