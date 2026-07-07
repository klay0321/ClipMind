"use client";

import Link from "next/link";

import { AssetIdentityPanel } from "@/components/assets/AssetIdentityPanel";
import { ImageReviewPanel } from "@/components/assets/ImageReviewPanel";
import { ProductLinkPanel } from "@/components/product-media/ProductLinkPanel";
import { ProcessingChain } from "@/components/assets/ProcessingChain";
import { AssetLegacyPanel } from "@/components/usage-evidence/AssetLegacyPanel";
import { AssetUsagePanel } from "@/components/usage-review/AssetUsagePanel";
import { AssetStatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Drawer } from "@/components/ui/overlay";
import { MediaThumb } from "@/components/ui/MediaThumb";
import { assetPosterUrl, shotThumbnailUrl } from "@/lib/api";
import {
  formatBytes,
  formatCodec,
  formatDateTime,
  formatDuration,
  formatResolution,
} from "@/lib/format";
import type { Asset } from "@/lib/types";

// 素材详情抽屉：只用 Asset 已有字段，不发额外请求；提供预览、完整处理链、重试与进入镜头工作台。
export function AssetDetailDrawer({
  asset,
  onClose,
  onAnalyze,
  onAnalyzeAi,
  onPreview,
}: {
  asset: Asset | null;
  onClose: () => void;
  onAnalyze: (id: number, retry: boolean) => void;
  onAnalyzeAi?: (id: number, retry: boolean) => void;
  onPreview: (shotId: number) => void;
}) {
  const open = asset != null;
  if (!asset) {
    return <Drawer open={false} onClose={onClose} title="素材详情">{null}</Drawer>;
  }

  const hasShots = asset.shot_count > 0;
  const failed = asset.analysis_status === "failed";
  const isProcessing =
    asset.status === "processing" ||
    asset.analysis_status === "queued" ||
    asset.analysis_status === "running";
  const aiStatus = asset.ai_analysis_status ?? null;
  const aiActive = aiStatus === "queued" || aiStatus === "running";
  const aiAnalyzed = (asset.ai_analyzed_total ?? 0) > 0;

  const coverSrc =
    asset.cover_shot_id != null
      ? shotThumbnailUrl(asset.cover_shot_id)
      : asset.has_poster
        ? assetPosterUrl(asset.id)
        : null;

  const info: { label: string; value: string }[] = [
    { label: "时长", value: formatDuration(asset.duration) },
    { label: "分辨率", value: formatResolution(asset.width, asset.height, asset.orientation) },
    { label: "编码", value: formatCodec(asset.video_codec, asset.audio_codec) },
    { label: "大小", value: formatBytes(asset.file_size) },
    { label: "最近扫描", value: formatDateTime(asset.last_seen_at) },
  ];

  return (
    <Drawer open={open} onClose={onClose} title={asset.filename} widthClass="max-w-lg">
      <div className="space-y-4">
        <div className="relative">
          <MediaThumb src={coverSrc} alt={`${asset.filename} 封面`} ratio="video" fallbackText="分析后生成封面" />
          {asset.cover_shot_id != null ? (
            <button
              type="button"
              onClick={() => onPreview(asset.cover_shot_id as number)}
              className="absolute inset-0 flex items-center justify-center bg-black/0 text-white transition hover:bg-black/30"
              aria-label="预览代理视频"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-black/55 text-xl">
                ▶
              </span>
            </button>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <AssetStatusBadge status={asset.status} />
          <Chip tone="neutral">{hasShots ? `${asset.shot_count} 个镜头` : "未拆镜头"}</Chip>
          {aiAnalyzed ? <Chip tone="brand">AI 已分析 {asset.ai_analyzed_total}</Chip> : null}
        </div>

        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">处理进度</h3>
          <ProcessingChain asset={asset} variant="full" />
        </section>

        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">基础信息</h3>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
            {info.map((row) => (
              <div key={row.label} className="flex justify-between gap-2">
                <dt className="text-gray-400">{row.label}</dt>
                <dd className="truncate text-gray-700" title={row.value}>
                  {row.value}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-2 break-all text-xs text-gray-400">路径：{asset.relative_path}</p>
        </section>

        {asset.status === "error" && asset.error_message ? (
          <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            分析失败：{asset.error_message}
          </div>
        ) : null}

        {/* IMG-REVIEW：图片 AI 理解 + 人工审核（仅图片素材） */}
        {asset.media_kind === "image" ? <ImageReviewPanel assetId={asset.id} /> : null}

        {/* PR-C：素材身份 / 文件位置历史 / 分析代次（只读派生） */}
        <ProductLinkPanel targetType="asset" targetId={asset.id} />
        <AssetIdentityPanel assetId={asset.id} onOpenShot={onPreview} />

        {/* PR-D：统一使用摘要（正式与历史并列，口径不同不相加） */}
        <AssetUsagePanel assetId={asset.id} />

        {/* PR-C Gate B：历史使用证据（弱证据只读区；绝不显示"已使用 N 次"） */}
        <AssetLegacyPanel assetId={asset.id} />
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-gray-100 pt-4">
        <Button
          variant="primary"
          size="sm"
          disabled={isProcessing || asset.status === "source_missing"}
          onClick={() => onAnalyze(asset.id, hasShots || failed)}
        >
          {isProcessing ? "分析中…" : failed ? "重试分析" : hasShots ? "继续分析" : "开始分析"}
        </Button>
        {onAnalyzeAi && hasShots ? (
          <Button
            variant="outline"
            size="sm"
            disabled={aiActive || asset.status === "source_missing"}
            onClick={() => onAnalyzeAi(asset.id, aiAnalyzed)}
          >
            {aiActive ? "AI 分析中…" : aiAnalyzed ? "继续 AI 分析" : "AI 分析"}
          </Button>
        ) : null}
        {hasShots ? (
          <Link
            href={`/shots?asset_id=${asset.id}`}
            className="inline-flex items-center whitespace-nowrap rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            进入镜头工作台 →
          </Link>
        ) : null}
      </div>
    </Drawer>
  );
}
