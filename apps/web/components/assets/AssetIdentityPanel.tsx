"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { ApiError } from "@/lib/api";
import {
  useAnalysisGenerations,
  useAssetIdentity,
  useFingerprintJob,
  useRequestFingerprint,
  useShotsByGeneration,
} from "@/lib/hooks";
import { formatBytes, formatDateTime, formatDuration } from "@/lib/format";
import type { AssetLocationEntry, FingerprintState, LocationStatus } from "@/lib/types";

const FP_STATE: Record<FingerprintState, { label: string; tone: "neutral" | "brand" | "success" | "warning" | "danger" }> = {
  pending: { label: "未计算", tone: "neutral" },
  quick_ready: { label: "快速指纹就绪（候选层）", tone: "brand" },
  full_ready: { label: "完整指纹就绪（权威）", tone: "success" },
  failed: { label: "计算失败", tone: "danger" },
  stale: { label: "内容已变化，指纹失效", tone: "warning" },
};

const LOC_STATE: Record<LocationStatus, { label: string; cls: string }> = {
  present: { label: "在此路径", cls: "bg-emerald-100 text-emerald-700" },
  missing: { label: "缺失", cls: "bg-amber-100 text-amber-800" },
  historical: { label: "历史位置", cls: "bg-gray-100 text-gray-500" },
  conflict: { label: "内容冲突", cls: "bg-red-100 text-red-700" },
};

/** PR-C 素材身份 / 文件位置历史 / 分析代次（全部只读派生；哈希仅缩短形式）。 */
export function AssetIdentityPanel({
  assetId,
  onOpenShot,
}: {
  assetId: number;
  onOpenShot?: (shotId: number) => void;
}) {
  const identity = useAssetIdentity(assetId);
  const generations = useAnalysisGenerations(assetId);
  const fingerprint = useRequestFingerprint(assetId);
  const [jobId, setJobId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedGen, setExpandedGen] = useState<number | null>(null);
  const job = useFingerprintJob(jobId);
  const genShots = useShotsByGeneration(assetId, expandedGen);

  const data = identity.data;
  if (identity.isLoading || !data) {
    return <p className="text-xs text-gray-400">身份信息加载中…</p>;
  }
  const fp = FP_STATE[data.fingerprint_state] ?? FP_STATE.pending;
  const jobActive = job.data?.status === "queued" || job.data?.status === "running";

  const request = (kind: "quick" | "full") => {
    setError(null);
    fingerprint.mutate(kind, {
      onSuccess: (j) => setJobId(j.id),
      onError: (err) => setError(err instanceof ApiError ? err.message : "指纹任务入队失败"),
    });
  };

  return (
    <div className="space-y-4" data-testid="asset-identity-panel">
      {/* ===== 素材身份 ===== */}
      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
          素材身份
        </h3>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span data-testid="fingerprint-state">
            <Chip tone={fp.tone}>{fp.label}</Chip>
          </span>
          {data.conflict_location_count > 0 ? (
            <Chip tone="danger">内容冲突 {data.conflict_location_count}</Chip>
          ) : null}
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          <div className="flex justify-between gap-2">
            <dt className="text-gray-400">快速指纹</dt>
            <dd className="font-mono text-gray-700" data-testid="quick-fp">
              {data.quick_fingerprint_short ?? "未计算"}
              {data.quick_fingerprint_version ? ` (${data.quick_fingerprint_version})` : ""}
            </dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-400">完整 SHA256</dt>
            <dd className="font-mono text-gray-700" data-testid="full-hash">
              {data.full_hash_short ? `${data.full_hash_short}…` : "未计算"}
            </dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-400">内容大小</dt>
            <dd className="text-gray-700">
              {data.content_size != null ? formatBytes(data.content_size) : "—"}
            </dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-400">位置数</dt>
            <dd className="text-gray-700">
              {data.location_count}（在位 {data.present_location_count}）
            </dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-400">最近计算</dt>
            <dd className="text-gray-700">
              {data.fingerprinted_at ? formatDateTime(data.fingerprinted_at) : "—"}
            </dd>
          </div>
        </dl>
        {data.fingerprint_error ? (
          <p className="mt-1 text-xs text-red-600">{data.fingerprint_error}</p>
        ) : null}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={fingerprint.isPending || jobActive}
            onClick={() => request("quick")}
            data-testid="fp-quick-btn"
          >
            计算快速指纹
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={fingerprint.isPending || jobActive}
            onClick={() => request("full")}
            data-testid="fp-full-btn"
          >
            计算完整 SHA256
          </Button>
          {job.data ? (
            <span className="text-xs text-gray-500" data-testid="fp-job-status">
              任务 #{job.data.id}：{job.data.status}
              {jobActive ? `（${job.data.progress}%）` : ""}
              {job.data.failed_count > 0 ? ` · 失败 ${job.data.failed_count}` : ""}
            </span>
          ) : null}
        </div>
        {error ? <p className="mt-1 text-xs text-red-600">{error}</p> : null}
        <p className="mt-2 text-[11px] leading-relaxed text-gray-400">
          文件路径变化不会改变素材身份；只有完整内容指纹一致时才会自动认定为移动。
          快速指纹命中仅为候选（“疑似同一素材，等待完整校验”），不会自动合并。
        </p>
      </section>

      {/* ===== 文件位置历史 ===== */}
      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
          文件位置历史
        </h3>
        {data.locations.length ? (
          <ul className="space-y-1" data-testid="location-list">
            {data.locations.map((loc) => (
              <LocationRow key={loc.id} loc={loc} />
            ))}
          </ul>
        ) : (
          <p className="text-xs text-gray-400">暂无位置记录</p>
        )}
      </section>

      {/* ===== 分析代次 ===== */}
      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
          分析代次
        </h3>
        {generations.data?.items.length ? (
          <ul className="space-y-1" data-testid="generation-list">
            {generations.data.items.map((g) => (
              <li key={g.generation} className="rounded border border-gray-100 px-2 py-1.5 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-gray-700">第 {g.generation} 代</span>
                  {g.is_current ? (
                    <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
                      current
                    </span>
                  ) : (
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
                      retired
                    </span>
                  )}
                  <span className="text-gray-500">{g.shot_count} 镜头</span>
                  {g.usage_referenced_count > 0 ? (
                    <span className="text-amber-700">
                      被成片血缘引用 {g.usage_referenced_count}
                    </span>
                  ) : null}
                  <span className="ml-auto text-gray-400">
                    {g.finished_at ? formatDateTime(g.finished_at) : ""}
                  </span>
                  <button
                    type="button"
                    className="text-brand hover:underline"
                    onClick={() =>
                      setExpandedGen((cur) => (cur === g.generation ? null : g.generation))
                    }
                    data-testid={`gen-toggle-${g.generation}`}
                  >
                    {expandedGen === g.generation ? "收起" : "查看镜头"}
                  </button>
                </div>
                {expandedGen === g.generation ? (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {genShots.isLoading ? (
                      <span className="text-gray-400">加载中…</span>
                    ) : (
                      (genShots.data?.items ?? []).map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() => onOpenShot?.(s.id)}
                          className="rounded border border-gray-200 px-1.5 py-0.5 text-[11px] text-gray-600 hover:border-brand"
                          title={`${formatDuration(s.start_time)} – ${formatDuration(s.end_time)}${s.retired ? "（历史代次）" : ""}`}
                          data-testid={`gen-shot-${s.id}`}
                        >
                          #{s.sequence_no}
                          {s.retired ? " ⏳" : ""}
                        </button>
                      ))
                    )}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-gray-400">尚未进行镜头分析</p>
        )}
      </section>
    </div>
  );
}

function LocationRow({ loc }: { loc: AssetLocationEntry }) {
  const meta = LOC_STATE[loc.location_status] ?? LOC_STATE.present;
  return (
    <li
      className="flex flex-wrap items-center gap-2 rounded border border-gray-100 px-2 py-1.5 text-xs"
      data-testid={`location-row-${loc.id}`}
    >
      <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${meta.cls}`}>
        {meta.label}
      </span>
      {loc.is_primary ? (
        <span className="rounded bg-brand/10 px-1.5 py-0.5 text-[10px] font-medium text-brand">
          primary
        </span>
      ) : null}
      <span className="min-w-0 flex-1 truncate text-gray-600" title={loc.relative_path}>
        {loc.source_root_name ? `${loc.source_root_name} / ` : ""}
        {loc.relative_path}
      </span>
      <span className="text-gray-400" title={`首次发现 ${formatDateTime(loc.first_seen_at)}`}>
        {loc.missing_at
          ? `缺失于 ${formatDateTime(loc.missing_at)}`
          : `最近 ${formatDateTime(loc.last_seen_at)}`}
      </span>
    </li>
  );
}
