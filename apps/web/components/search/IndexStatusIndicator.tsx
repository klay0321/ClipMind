// 检索索引健康指示器：普通用户默认只看简化态（正常/建设中/部分降级/异常），详细数字可展开。
// 无真实数据时绝不写"索引正常"。数据来自 GET /api/search/index/status。
"use client";

import { useState } from "react";

import { useSearchIndexStatus } from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";
import { INDEX_HEALTH_TONE, deriveIndexHealth } from "@/lib/search";

export function IndexStatusIndicator() {
  const [open, setOpen] = useState(false);
  const q = useSearchIndexStatus();
  const s = q.data;

  let label: string;
  let tone: string;
  let hint: string;
  if (q.isLoading) {
    label = "检测中…";
    tone = "bg-gray-100 text-gray-500";
    hint = "正在获取索引状态";
  } else if (q.isError || !s) {
    label = "状态未知";
    tone = "bg-gray-100 text-gray-500";
    hint = "无法获取索引状态";
  } else {
    const h = deriveIndexHealth(s);
    label = h.label;
    tone = INDEX_HEALTH_TONE[h.level];
    hint = h.hint;
  }

  return (
    <div className="relative" data-testid="index-status">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-xs hover:bg-gray-50"
        title={hint}
      >
        <span className="text-gray-500">索引</span>
        <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[11px] font-medium ${tone}`}>
          {label}
        </span>
        <span className="text-gray-400" aria-hidden>
          {open ? "▴" : "▾"}
        </span>
      </button>

      {open ? (
        <div
          className="absolute right-0 z-30 mt-1 w-72 rounded-lg border border-gray-200 bg-white p-3 text-xs shadow-lg"
          data-testid="index-status-detail"
        >
          {q.isLoading ? (
            <p className="text-gray-400">加载中…</p>
          ) : q.isError || !s ? (
            <p className="text-gray-500">暂时无法获取索引状态，请稍后重试。</p>
          ) : (
            <>
              <p className="mb-2 text-gray-500">{hint}</p>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
                <dt className="text-gray-400">总镜头</dt>
                <dd className="text-gray-700">{s.total_shots}</dd>
                <dt className="text-gray-400">已索引</dt>
                <dd className="text-gray-700">{s.indexed_documents}</dd>
                <dt className="text-gray-400">已排除</dt>
                <dd className="text-gray-700">{s.excluded_documents}</dd>
                <dt className="text-gray-400">嵌入完成</dt>
                <dd className="text-gray-700">{s.completed_embeddings}</dd>
                <dt className="text-gray-400">嵌入降级</dt>
                <dd className="text-gray-700">{s.degraded_embeddings}</dd>
                <dt className="text-gray-400">嵌入失败</dt>
                <dd className="text-gray-700">{s.failed_embeddings}</dd>
                <dt className="text-gray-400">待嵌入</dt>
                <dd className="text-gray-700">{s.pending_embeddings}</dd>
                <dt className="text-gray-400">版本不一致</dt>
                <dd className="text-gray-700">{s.embedding_version_mismatched}</dd>
                <dt className="text-gray-400">审核过期</dt>
                <dd className="text-gray-700">{s.stale_documents}</dd>
                <dt className="text-gray-400">向量版本</dt>
                <dd className="truncate text-gray-700" title={s.current_embedding_version}>
                  {s.current_embedding_version || "—"}
                </dd>
                <dt className="text-gray-400">最近索引</dt>
                <dd className="text-gray-700">{formatDateTime(s.last_indexed_at)}</dd>
                <dt className="text-gray-400">向量服务</dt>
                <dd className={s.provider_healthy ? "text-emerald-600" : "text-amber-600"}>
                  {s.provider_healthy ? "健康" : "不可用"}
                </dd>
              </dl>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
