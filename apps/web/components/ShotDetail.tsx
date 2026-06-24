"use client";

import { useEffect, useState } from "react";

import { ShotStatusBadge } from "@/components/StatusBadge";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import {
  exportDownloadUrl,
  shotKeyframeAtUrl,
  shotKeyframeUrl,
  shotPreviewUrl,
} from "@/lib/api";
import { formatCodec, formatDuration, formatResolution } from "@/lib/format";
import {
  useAnalyzeShotAiMutation,
  useExportMutation,
  useExportStatus,
  useShot,
  useShotAi,
} from "@/lib/hooks";
import type { ShotAI } from "@/lib/types";

function timecode(s: number): string {
  return formatDuration(s);
}

const AI_LABEL: Record<string, string> = {
  completed: "AI 已分析",
  degraded: "已降级",
  failed: "分析失败",
  pending: "待分析",
  skipped: "已复用缓存",
};
const AI_COLOR: Record<string, string> = {
  completed: "bg-emerald-50 text-emerald-700",
  degraded: "bg-amber-50 text-amber-700",
  failed: "bg-red-50 text-red-700",
  pending: "bg-gray-100 text-gray-500",
  skipped: "bg-gray-100 text-gray-500",
};

// AI 画面理解面板：展示**真实** AI 状态与原始结果（待人工审核），不伪造、不显示假标签。
function AiPanel({
  ai,
  loading,
  analyzing,
  onAnalyze,
}: {
  ai: ShotAI | undefined;
  loading: boolean;
  analyzing: boolean;
  onAnalyze: () => void;
}) {
  const status = ai?.status ?? null;
  const result = ai?.result ?? null;
  const analyzed = !!ai?.has_analysis;
  return (
    <div className="space-y-2 rounded border border-gray-100 bg-gray-50/60 p-3" data-testid="ai-panel">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-700">AI 画面理解</span>
        {status ? (
          <span className={`rounded px-1.5 py-0.5 text-[11px] ${AI_COLOR[status] ?? "bg-gray-100 text-gray-500"}`}>
            {AI_LABEL[status] ?? status}
          </span>
        ) : (
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-500">尚未分析</span>
        )}
      </div>

      {loading ? <div className="text-[11px] text-gray-400">加载中…</div> : null}

      {status === "degraded" ? (
        <p className="rounded bg-amber-50 p-2 text-[11px] text-amber-700">
          未做视觉分析（{ai?.degraded_reason ?? "provider 能力不足"}）—— 已标记待人工确认，绝不伪造结果。
        </p>
      ) : null}
      {status === "failed" ? (
        <p className="rounded bg-red-50 p-2 text-[11px] text-red-700">AI 分析失败，可重试或转人工。</p>
      ) : null}

      {analyzed && result ? (
        <div className="space-y-1.5">
          <span className="inline-block rounded bg-gray-200 px-1.5 py-0.5 text-[10px] text-gray-600">
            AI 原始结果 · 待人工审核
          </span>
          {result.one_line ? (
            <p className="text-xs text-gray-800">{result.one_line}</p>
          ) : null}
          <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
            {typeof ai?.confidence === "number" ? (
              <span className="text-gray-500">置信度 {Math.round((ai.confidence ?? 0) * 100)}%</span>
            ) : null}
            {ai?.needs_human_review ? (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-800">待人工确认</span>
            ) : null}
            {(result.risk_flags ?? []).map((r) => (
              <span key={r} className="rounded bg-red-100 px-1.5 py-0.5 text-red-700">
                风险：{r}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <button
        type="button"
        data-testid="ai-analyze-btn"
        onClick={onAnalyze}
        disabled={analyzing}
        className="w-full rounded-md border border-brand px-3 py-1.5 text-xs font-medium text-brand hover:bg-brand-light disabled:cursor-not-allowed disabled:opacity-50"
      >
        {analyzing ? "已入队…" : analyzed ? "重新 AI 分析" : "AI 分析此镜头"}
      </button>
      <p className="text-[10px] text-gray-400">标签拆解、产品库与人工审核将在 PR-03B 提供。</p>
    </div>
  );
}

export function ShotDetail({ shotId }: { shotId: number | null }) {
  const [exportId, setExportId] = useState<number | null>(null);
  // 关键帧条选中帧：null = 主关键帧；数字 = 条上第 N 帧
  const [activeFrame, setActiveFrame] = useState<number | null>(null);
  const [aiPoll, setAiPoll] = useState(false);
  const shotQ = useShot(shotId);
  const exportMut = useExportMutation();
  const exportStatusQ = useExportStatus(exportId);
  const aiQ = useShotAi(shotId, aiPoll);
  const analyzeAiMut = useAnalyzeShotAiMutation();

  // 切换镜头时重置选中帧与 AI 轮询
  useEffect(() => {
    setActiveFrame(null);
    setAiPoll(false);
  }, [shotId]);

  if (shotId == null) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-gray-400">
        选择左侧镜头查看详情
      </div>
    );
  }
  if (shotQ.isLoading) return <Loading />;
  if (shotQ.isError || !shotQ.data) {
    return (
      <ErrorState
        message={(shotQ.error as Error)?.message ?? "加载镜头详情失败"}
        onRetry={() => void shotQ.refetch()}
      />
    );
  }

  const s = shotQ.data;
  const exp = exportStatusQ.data;
  const exporting = exportMut.isPending || (exp != null && (exp.status === "queued" || exp.status === "running"));
  const exportFailed = exp?.status === "failed";

  const handleExport = () => {
    exportMut.mutate(
      { shotId: s.id },
      { onSuccess: (d) => setExportId(d.export_id) },
    );
  };

  return (
    <div className="space-y-3 p-4" data-testid="shot-detail">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">
          镜头 #{s.sequence_no}
        </h3>
        <ShotStatusBadge status={s.status} />
      </div>

      {/* 代理视频播放器（支持 Range 拖动进度条） */}
      {s.has_proxy ? (
        <video
          data-testid="shot-video"
          className="w-full rounded bg-black"
          src={shotPreviewUrl(s.id)}
          controls
          preload="metadata"
        />
      ) : (
        <div className="flex h-40 items-center justify-center rounded bg-gray-100 text-xs text-gray-400">
          代理视频不可用
        </div>
      )}

      {/* 关键帧（主帧 / 关键帧条选中帧） */}
      {s.has_keyframe ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={activeFrame == null ? shotKeyframeUrl(s.id) : shotKeyframeAtUrl(s.id, activeFrame)}
          alt={`镜头 ${s.sequence_no} 关键帧`}
          className="w-full rounded border border-gray-100"
        />
      ) : null}

      {/* 关键帧条：沿镜头均匀采样的多帧（点击放大到上方） */}
      {s.keyframe_count > 0 ? (
        <div className="space-y-1" data-testid="keyframe-strip">
          <div className="text-[11px] text-gray-400">关键帧条（{s.keyframe_count} 帧 · 沿镜头采样）</div>
          <div className="flex gap-1 overflow-x-auto pb-1">
            <button
              type="button"
              onClick={() => setActiveFrame(null)}
              className={`shrink-0 overflow-hidden rounded border ${
                activeFrame == null ? "border-brand ring-1 ring-brand" : "border-gray-200"
              }`}
              title="主关键帧"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={shotKeyframeUrl(s.id)} alt="主关键帧" className="h-12 w-20 object-cover" />
            </button>
            {Array.from({ length: s.keyframe_count }).map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setActiveFrame(i)}
                className={`shrink-0 overflow-hidden rounded border ${
                  activeFrame === i ? "border-brand ring-1 ring-brand" : "border-gray-200"
                }`}
                title={`第 ${i + 1} 帧`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={shotKeyframeAtUrl(s.id, i)}
                  alt={`关键帧 ${i + 1}`}
                  className="h-12 w-20 object-cover"
                  loading="lazy"
                />
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <dt className="text-gray-400">来源视频</dt>
        <dd className="truncate text-gray-700" title={s.asset_filename}>
          {s.asset_filename}
        </dd>
        <dt className="text-gray-400">时间码</dt>
        <dd className="text-gray-700">
          {timecode(s.start_time)} – {timecode(s.end_time)}
        </dd>
        <dt className="text-gray-400">时长</dt>
        <dd className="text-gray-700">{s.duration.toFixed(2)}s</dd>
        <dt className="text-gray-400">来源分辨率</dt>
        <dd className="text-gray-700">
          {formatResolution(s.asset_width, s.asset_height, null)}
        </dd>
        <dt className="text-gray-400">来源编码</dt>
        <dd className="text-gray-700">
          {formatCodec(s.asset_video_codec, s.asset_audio_codec)}
        </dd>
        <dt className="text-gray-400">检测器</dt>
        <dd className="text-gray-700">{s.detector_type}</dd>
      </dl>

      <div className="space-y-1">
        <button
          type="button"
          data-testid="shot-export-btn"
          onClick={handleExport}
          disabled={exporting}
          className="w-full rounded-md bg-brand px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-brand-dark"
        >
          {exporting ? "导出中…" : "导出片段"}
        </button>
        {exp?.status === "completed" && exp.has_file ? (
          <a
            data-testid="shot-download-link"
            href={exportDownloadUrl(exp.id)}
            className="block rounded-md border border-brand px-3 py-2 text-center text-sm font-medium text-brand hover:bg-brand-light"
          >
            下载片段
          </a>
        ) : null}
        {exportFailed ? (
          <p className="text-xs text-red-600">导出失败：{exp?.error_message ?? "未知错误"}</p>
        ) : null}
      </div>

      <AiPanel
        ai={aiQ.data}
        loading={aiQ.isLoading}
        analyzing={analyzeAiMut.isPending}
        onAnalyze={() => {
          setAiPoll(true);
          analyzeAiMut.mutate(s.id);
        }}
      />
    </div>
  );
}
