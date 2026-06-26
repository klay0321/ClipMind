// 诚实降级提示：可见但不过度打扰，区别于"全部失败"，不清空本可返回的词法结果。
// 正常模式（parser_status=ok 且 embedding_status=ok 且非建设中）不渲染任何内容。
"use client";

import { degradationReasonLabel } from "@/lib/search";

export function DegradedNotice({
  parserStatus,
  embeddingStatus,
  degradationReasons = [],
  indexBuilding = false,
}: {
  parserStatus?: string;
  embeddingStatus?: string;
  degradationReasons?: string[];
  indexBuilding?: boolean;
}) {
  const parserDegraded = parserStatus === "degraded";
  const embeddingDegraded = embeddingStatus === "degraded" || embeddingStatus === "unavailable";
  if (!parserDegraded && !embeddingDegraded && !indexBuilding) return null;

  return (
    <div
      data-testid="degraded-notice"
      role="status"
      className="space-y-1 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800"
    >
      <div className="flex items-center gap-1.5 font-medium">
        <span aria-hidden>ⓘ</span>
        <span>检索能力部分降级（结果仍然有效）</span>
      </div>
      <ul className="ml-5 list-disc space-y-0.5">
        {parserDegraded ? (
          <li data-testid="degraded-parser">
            AI 查询理解暂时不可用，已使用关键词和筛选条件搜索。
          </li>
        ) : null}
        {embeddingDegraded ? (
          <li data-testid="degraded-embedding">
            语义相似检索暂时不可用，当前结果来自关键词、标签、产品和筛选条件。
          </li>
        ) : null}
        {indexBuilding ? (
          <li data-testid="degraded-index">部分新素材仍在建立索引，当前结果可能不完整。</li>
        ) : null}
      </ul>
      {degradationReasons.length > 0 ? (
        <details className="ml-5 text-[11px] text-amber-700">
          <summary className="cursor-pointer">技术详情</summary>
          <ul className="mt-0.5 list-disc pl-4">
            {degradationReasons.map((r, i) => (
              <li key={`${r}-${i}`}>{degradationReasonLabel(r)}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
