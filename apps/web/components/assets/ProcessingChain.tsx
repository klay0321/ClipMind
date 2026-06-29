import { cn } from "@/lib/cn";
import type { Asset } from "@/lib/types";

// 素材处理链：把 Asset 上已有的真实字段诚实映射成可视的阶段进度。
// 不伪造任何后端没有的状态；无法判断的阶段标记为「未开始」，绝不假装完成。

export type StepState = "done" | "active" | "failed" | "todo";

export interface PipelineStep {
  key: string;
  label: string;
  state: StepState;
}

// 纯函数，便于单测。
export function assetPipeline(asset: Asset): PipelineStep[] {
  const sourceMissing = asset.status === "source_missing";
  const probed = asset.width != null || asset.duration != null;
  const indexedLike =
    probed ||
    asset.shot_count > 0 ||
    ["indexed", "shot_split", "ai_analyzing", "pending_review", "searchable", "archived", "paused"].includes(
      asset.status,
    );

  const hasShots = asset.shot_count > 0;
  const splitActive =
    asset.status === "processing" ||
    asset.analysis_status === "queued" ||
    asset.analysis_status === "running";
  const splitFailed = asset.analysis_status === "failed";
  const derivativesReady = asset.cover_shot_id != null || asset.has_poster;

  const ai = asset.ai_analysis_status ?? null;
  const aiAnalyzed = (asset.ai_analyzed_total ?? 0) > 0;
  const aiDone = ai === "completed" || (ai === "partial" && aiAnalyzed);
  const aiActive = ai === "queued" || ai === "running";
  const aiFailed = ai === "failed";

  const searchable = asset.status === "searchable";

  const indexStep: StepState = sourceMissing
    ? "failed"
    : asset.status === "error" && !hasShots
      ? "failed"
      : indexedLike
        ? "done"
        : "active";

  const splitStep: StepState = splitFailed
    ? "failed"
    : hasShots
      ? "done"
      : splitActive
        ? "active"
        : "todo";

  const derivStep: StepState = hasShots
    ? derivativesReady || !splitActive
      ? "done"
      : "active"
    : "todo";

  const aiStep: StepState = aiFailed ? "failed" : aiDone ? "done" : aiActive ? "active" : "todo";

  const searchStep: StepState = searchable ? "done" : aiDone ? "active" : "todo";

  return [
    { key: "index", label: "已入库", state: indexStep },
    { key: "split", label: "已拆镜头", state: splitStep },
    { key: "deriv", label: "派生就绪", state: derivStep },
    { key: "ai", label: "AI 已识别", state: aiStep },
    { key: "search", label: "可搜索", state: searchStep },
  ];
}

const DOT: Record<StepState, string> = {
  done: "bg-emerald-500",
  active: "bg-blue-500 animate-pulse",
  failed: "bg-red-500",
  todo: "bg-gray-300",
};

const TEXT: Record<StepState, string> = {
  done: "text-emerald-700",
  active: "text-blue-700",
  failed: "text-red-600",
  todo: "text-gray-400",
};

const STATE_WORD: Record<StepState, string> = {
  done: "已完成",
  active: "处理中",
  failed: "失败",
  todo: "未开始",
};

export function ProcessingChain({
  asset,
  variant = "compact",
}: {
  asset: Asset;
  variant?: "compact" | "full";
}) {
  const steps = assetPipeline(asset);
  const summary = steps.map((s) => `${s.label}${STATE_WORD[s.state]}`).join("，");

  if (variant === "full") {
    return (
      <ol className="space-y-1.5" aria-label={`处理进度：${summary}`}>
        {steps.map((s) => (
          <li key={s.key} className="flex items-center gap-2 text-xs">
            <span className={cn("h-2 w-2 shrink-0 rounded-full", DOT[s.state])} aria-hidden />
            <span className={cn("font-medium", TEXT[s.state])}>{s.label}</span>
            <span className="text-gray-400">· {STATE_WORD[s.state]}</span>
          </li>
        ))}
      </ol>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1" aria-label={`处理进度：${summary}`}>
      {steps.map((s, i) => (
        <span key={s.key} className="flex items-center gap-1">
          <span
            className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT[s.state])}
            title={`${s.label}：${STATE_WORD[s.state]}`}
            aria-hidden
          />
          <span className={cn("text-[11px]", TEXT[s.state])}>{s.label}</span>
          {i < steps.length - 1 ? <span className="text-gray-200" aria-hidden>›</span> : null}
        </span>
      ))}
    </div>
  );
}
