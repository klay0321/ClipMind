"use client";

import { useState } from "react";

import { Pagination } from "@/components/Pagination";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Button } from "@/components/ui/Button";
import { assetPosterUrl, ApiError } from "@/lib/api";
import { useAssetSearch, usePmSummary } from "@/lib/hooks";
import type { AssetSearchRequest, AssetSearchResultItem } from "@/lib/types";
import { cn } from "@/lib/cn";

const PAGE_SIZE = 20;

function fmtDuration(d: number | null): string {
  if (d == null) return "";
  const m = Math.floor(d / 60);
  const s = Math.round(d % 60);
  return m > 0 ? `${m}分${s}秒` : `${s}秒`;
}

/** P2a 素材级搜索面板（整条视频 / 图片）。自含输入与分页，不影响镜头检索状态。 */
export function AssetSearchPanel({ mediaKind }: { mediaKind: "video" | "image" }) {
  const [input, setInput] = useState("");
  const [familySel, setFamilySel] = useState<string>("");
  const [committed, setCommitted] = useState<AssetSearchRequest | null>(null);
  const summary = usePmSummary();
  const families = summary.data ?? [];

  const submit = (page = 1) => {
    setCommitted({
      query: input.trim() || undefined,
      media_kind: mediaKind,
      product_family_id: familySel ? Number(familySel) : undefined,
      page,
      page_size: PAGE_SIZE,
    });
  };

  const q = useAssetSearch(
    committed ? { ...committed, media_kind: mediaKind } : null,
  );
  const data = q.data;
  const kindLabel = mediaKind === "video" ? "视频" : "图片";

  return (
    <div className="space-y-3" data-testid={`asset-search-${mediaKind}`}>
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit(1);
          }}
          placeholder={`用自然语言搜整${mediaKind === "video" ? "条" : "张"}${kindLabel}，如"车载氛围灯 特写"`}
          className="min-w-0 flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-brand focus:outline-none"
          data-testid="asset-search-input"
        />
        <select
          value={familySel}
          onChange={(e) => setFamilySel(e.target.value)}
          className="rounded-md border border-gray-300 px-2 py-2 text-sm"
          data-testid="asset-search-family"
          title="按目录产品过滤"
        >
          <option value="">全部产品</option>
          {families.map((f) => (
            <option key={f.family_id} value={f.family_id}>
              {f.name_zh}
            </option>
          ))}
        </select>
        <Button variant="primary" onClick={() => submit(1)} loading={q.isFetching} data-testid="asset-search-submit">
          搜索
        </Button>
      </div>

      {committed == null ? (
        <p className="rounded border border-gray-100 bg-gray-50 px-3 py-6 text-center text-sm text-gray-400">
          输入描述搜索{kindLabel}素材；{mediaKind === "video" ? "整条视频按其全部镜头的 AI 理解聚合检索" : "图片按其 AI 理解描述检索"}。
          留空直接搜索则浏览最新已索引{kindLabel}。
        </p>
      ) : q.isError ? (
        <ErrorState
          message={(q.error as ApiError)?.message ?? "搜索失败"}
          onRetry={() => q.refetch()}
        />
      ) : data && data.items.length === 0 ? (
        <Empty
          title={`没有匹配的${kindLabel}`}
          description="可尝试更换描述词，或确认素材已完成 AI 理解（素材库页可查看处理进度）。"
        />
      ) : (
        <>
          {data?.embedding_status === "degraded" ? (
            <p className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-700">
              语义服务暂不可用，当前仅按词法匹配（结果可能偏少）。
            </p>
          ) : null}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="asset-search-results">
            {(data?.items ?? []).map((it: AssetSearchResultItem) => (
              <div
                key={it.asset_id}
                className="overflow-hidden rounded-lg border border-gray-200 bg-white"
                data-testid={`asset-result-${it.asset_id}`}
              >
                <div className="relative h-28 bg-gray-100">
                  {it.has_poster ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={assetPosterUrl(it.asset_id)}
                      alt={it.filename}
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center text-xs text-gray-400">
                      无封面
                    </div>
                  )}
                  <span
                    className={cn(
                      "absolute left-1 top-1 rounded px-1 text-[10px] text-white",
                      mediaKind === "video" ? "bg-black/60" : "bg-emerald-600/80",
                    )}
                  >
                    {kindLabel}
                    {it.duration != null ? ` · ${fmtDuration(it.duration)}` : ""}
                  </span>
                  <span className="absolute right-1 top-1 rounded bg-brand/90 px-1 text-[10px] text-white">
                    {Math.round(it.score * 100)}%
                  </span>
                </div>
                <div className="space-y-1 p-2">
                  <p className="truncate text-xs font-medium text-gray-800" title={it.filename}>
                    {it.filename}
                  </p>
                  {it.document_excerpt ? (
                    <p className="line-clamp-2 text-[11px] leading-4 text-gray-500">
                      {it.document_excerpt}
                    </p>
                  ) : null}
                  {it.product_names.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {it.product_names.slice(0, 2).map((n) => (
                        <span key={n} className="rounded bg-emerald-50 px-1 text-[10px] text-emerald-700">
                          {n}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <div className="flex items-center justify-between pt-0.5">
                    <a
                      href={`/assets?open=${it.asset_id}`}
                      className="text-[11px] text-brand hover:underline"
                    >
                      查看素材
                    </a>
                    {mediaKind === "video" ? (
                      <a
                        href={`/shots?asset_id=${it.asset_id}`}
                        className="text-[11px] text-gray-500 hover:text-brand hover:underline"
                      >
                        查看镜头
                      </a>
                    ) : null}
                  </div>
                </div>
              </div>
            ))}
          </div>
          {data ? (
            <Pagination
              page={data.page}
              pageSize={data.page_size}
              total={data.total}
              onPageChange={(p) => submit(p)}
            />
          ) : null}
        </>
      )}
    </div>
  );
}
