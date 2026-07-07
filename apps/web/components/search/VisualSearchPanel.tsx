"use client";

import { useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { useVisualSearch } from "@/lib/hooks";
import type { VisualSearchHit } from "@/lib/types";
import { cn } from "@/lib/cn";

// IMG-SEARCH：以图搜图面板。上传一张图 → 对全库素材/镜头的视觉向量做
// 相似检索（VIS-AUTO 持久化向量，SigLIP/HNSW）。上传图内存处理不保存。
export function VisualSearchPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [kind, setKind] = useState<"all" | "asset" | "shot">("all");
  const inputRef = useRef<HTMLInputElement>(null);
  const search = useVisualSearch();

  const pick = (f: File | null) => {
    setFile(f);
    if (preview) URL.revokeObjectURL(preview);
    setPreview(f ? URL.createObjectURL(f) : null);
  };

  const submit = () => {
    if (!file) return;
    search.mutate({ file, kind });
  };

  const data = search.data;
  const errMsg =
    search.error instanceof ApiError
      ? search.error.message
      : (search.error as Error | null)?.message;

  return (
    <div className="space-y-3" data-testid="visual-search-panel">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-200 bg-white p-3">
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="hidden"
          data-testid="visual-search-file"
          onChange={(e) => pick(e.target.files?.[0] ?? null)}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:border-brand hover:text-brand"
          data-testid="visual-search-pick"
        >
          {file ? "换一张图" : "选择图片"}
        </button>
        {preview ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={preview} alt="查询图预览" className="h-12 w-12 rounded object-cover" />
        ) : null}
        <span className="max-w-[200px] truncate text-xs text-gray-500">
          {file ? file.name : "上传一张产品/画面图，找视觉相似的素材与镜头"}
        </span>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as typeof kind)}
          aria-label="相似目标类型"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          data-testid="visual-search-kind"
        >
          <option value="all">素材 + 镜头</option>
          <option value="asset">仅素材（图片/视频封面）</option>
          <option value="shot">仅镜头</option>
        </select>
        <button
          type="button"
          onClick={submit}
          disabled={!file || search.isPending}
          className="rounded bg-brand px-4 py-1.5 text-sm font-medium text-white disabled:opacity-40"
          data-testid="visual-search-submit"
        >
          {search.isPending ? "搜索中…" : "以图搜图"}
        </button>
      </div>

      {search.isError ? (
        <p className="text-sm text-red-600" data-testid="visual-search-error">
          {errMsg ?? "搜索失败"}
        </p>
      ) : null}

      {data ? (
        <div data-testid="visual-search-results">
          <p className="mb-2 text-xs text-gray-500">
            与库内 {data.total_indexed} 条视觉向量比对（模型 {data.model}）；
            相似度仅为视觉提示，不构成产品归属事实。
          </p>
          {data.hits.length === 0 ? (
            <p className="text-sm text-gray-400">没有相似结果（库内可能还没有视觉向量）</p>
          ) : (
            <div className="grid gap-2 md:grid-cols-3 lg:grid-cols-4">
              {data.hits.map((h) => (
                <VisualHitCard key={`${h.kind}-${h.shot_id ?? h.asset_id}`} hit={h} />
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function VisualHitCard({ hit }: { hit: VisualSearchHit }) {
  const thumb =
    hit.kind === "shot" && hit.shot_id != null
      ? `/api/shots/${hit.shot_id}/keyframe`
      : hit.asset_id != null
        ? `/api/assets/${hit.asset_id}/poster`
        : null;
  const href =
    hit.kind === "shot" && hit.shot_id != null
      ? `/shots/${hit.shot_id}`
      : hit.asset_id != null
        ? `/assets/${hit.asset_id}`
        : "#";
  return (
    <a
      href={href}
      className="block rounded border border-gray-200 bg-white text-xs hover:border-brand"
      data-testid={`visual-hit-${hit.kind}-${hit.shot_id ?? hit.asset_id}`}
    >
      {thumb ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={thumb}
          alt=""
          className="h-24 w-full rounded-t object-cover"
          onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
        />
      ) : null}
      <div className="space-y-0.5 p-2">
        <div className="flex items-center justify-between">
          <span
            className={cn(
              "rounded px-1 py-0.5 text-[10px] font-medium",
              hit.kind === "shot" ? "bg-blue-50 text-blue-700" : "bg-gray-100 text-gray-600",
            )}
          >
            {hit.kind === "shot" ? `镜头 #${hit.shot_id}` : "素材"}
          </span>
          <span className="font-medium text-purple-700">{hit.score.toFixed(3)}</span>
        </div>
        <p className="truncate text-gray-600">{hit.filename ?? `素材 #${hit.asset_id}`}</p>
        {hit.kind === "shot" && hit.start_time != null && hit.end_time != null ? (
          <p className="text-gray-400">
            {hit.start_time.toFixed(1)}s – {hit.end_time.toFixed(1)}s
            {hit.is_historical ? "（历史代次）" : ""}
          </p>
        ) : null}
      </div>
    </a>
  );
}
