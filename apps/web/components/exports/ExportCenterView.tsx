// 导出中心：统一查看 clip / script / bundle 三类导出记录。
// 列表带种类/状态/项目筛选 + 分页；逐行下载（直链 <a download>，不经 fetch blob）、
// 重试（仅 failed）、删除（仅 completed/failed，确认对话框明确「只删导出记录与派生导出文件」）。
// 任意行排队/生成中时轮询，全部结束后停止。所有数据只读后端，绝不伪造状态。
"use client";

import { useState } from "react";
import Link from "next/link";

import { ConfirmDialog, InlineError } from "@/components/projects/widgets";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { TopNav } from "@/components/TopNav";
import { Badge } from "@/components/StatusBadge";
import { formatDateTime } from "@/lib/format";
import {
  EXPORT_KIND_LABELS,
  EXPORT_KIND_TONE,
  EXPORT_STATUS_LABELS,
  EXPORT_STATUS_TONE,
} from "@/lib/exports";
import { useDeleteExport, useExportCenter, useRetryExport } from "@/lib/hooks";
import type { ExportCenterItem, ExportKind, ExportStatus } from "@/lib/types";

const KIND_OPTIONS: { value: "" | ExportKind; label: string }[] = [
  { value: "", label: "全部种类" },
  { value: "clip", label: "单镜头片段" },
  { value: "script", label: "脚本剪辑清单" },
  { value: "bundle", label: "ZIP 打包" },
];

const STATUS_OPTIONS: { value: "" | ExportStatus; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "queued", label: "排队中" },
  { value: "running", label: "生成中" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" },
];

const PAGE_SIZE = 20;
const DELETE_MESSAGE = "只删除导出记录和派生导出文件，不删除源视频和素材。确定删除该导出记录？";

export function ExportCenterView({ projectId }: { projectId?: number }) {
  const [kind, setKind] = useState<"" | ExportKind>("");
  const [status, setStatus] = useState<"" | ExportStatus>("");
  const [page, setPage] = useState(1);

  const query = useExportCenter({
    kind: kind || undefined,
    status: status || undefined,
    project_id: projectId,
    page,
    page_size: PAGE_SIZE,
  });
  const retry = useRetryExport();
  const del = useDeleteExport();
  const data = query.data;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  const reset = () => setPage(1);

  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="exports" />
      <main className="mx-auto max-w-7xl space-y-4 p-4" data-testid="export-center">
        <header>
          <h1 className="text-xl font-semibold text-gray-900">导出中心</h1>
          <p className="text-sm text-gray-500">
            统一管理单镜头片段、脚本剪辑清单与 ZIP 打包导出。可重试失败任务、下载已完成文件、删除导出记录。
          </p>
        </header>

        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="filter-kind">
            导出种类
          </label>
          <select
            id="filter-kind"
            data-testid="filter-kind"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as "" | ExportKind);
              reset();
            }}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
          >
            {KIND_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="filter-status">
            导出状态
          </label>
          <select
            id="filter-status"
            data-testid="filter-status"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as "" | ExportStatus);
              reset();
            }}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          {query.isFetching ? (
            <span className="text-xs text-gray-400" role="status">
              更新中…
            </span>
          ) : null}
        </div>

        <InlineError error={retry.error ?? del.error} />

        {query.isLoading ? (
          <Loading rows={4} />
        ) : query.isError ? (
          <ErrorState
            message={(query.error as Error).message}
            onRetry={() => void query.refetch()}
          />
        ) : !data || data.items.length === 0 ? (
          <Empty
            title="暂无导出记录"
            description="在镜头详情、剪辑清单或搜索结果中创建导出后，会出现在这里。"
          />
        ) : (
          <>
            {/* 桌面表格；窄屏改为卡片堆叠 */}
            <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">种类</th>
                    <th className="px-3 py-2 font-medium">格式</th>
                    <th className="px-3 py-2 font-medium">文件 / 行数</th>
                    <th className="px-3 py-2 font-medium">状态</th>
                    <th className="px-3 py-2 font-medium">创建 / 完成</th>
                    <th className="px-3 py-2 font-medium">下载</th>
                    <th className="px-3 py-2 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.items.map((it) => (
                    <ExportRow
                      key={`${it.kind}-${it.id}`}
                      item={it}
                      onRetry={() => retry.mutate({ kind: it.kind, id: it.id })}
                      retrying={retry.isPending}
                      onDelete={() => del.mutate({ kind: it.kind, id: it.id })}
                      deleting={del.isPending}
                    />
                  ))}
                </tbody>
              </table>
            </div>

            {data.total > PAGE_SIZE ? (
              <div className="flex items-center justify-between px-1 text-sm text-gray-600">
                <span>
                  共 {data.total} 条 · 第 {page} / {totalPages} 页
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    data-testid="export-page-prev"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="rounded-md border border-gray-300 bg-white px-3 py-1 disabled:opacity-50 hover:bg-gray-50"
                  >
                    上一页
                  </button>
                  <button
                    type="button"
                    data-testid="export-page-next"
                    onClick={() => setPage((p) => p + 1)}
                    disabled={page >= totalPages}
                    className="rounded-md border border-gray-300 bg-white px-3 py-1 disabled:opacity-50 hover:bg-gray-50"
                  >
                    下一页
                  </button>
                </div>
              </div>
            ) : null}
          </>
        )}
      </main>
    </div>
  );
}

function ExportRow({
  item,
  onRetry,
  retrying,
  onDelete,
  deleting,
}: {
  item: ExportCenterItem;
  onRetry: () => void;
  retrying: boolean;
  onDelete: () => void;
  deleting: boolean;
}) {
  const [confirm, setConfirm] = useState(false);
  const canRetry = item.status === "failed";
  const canDelete = item.status === "completed" || item.status === "failed";
  return (
    <tr data-testid={`export-row-${item.kind}-${item.id}`} className="align-top">
      <td className="px-3 py-2">
        <Badge label={EXPORT_KIND_LABELS[item.kind]} cls={EXPORT_KIND_TONE[item.kind]} />
      </td>
      <td className="px-3 py-2 text-gray-700">{item.format || "—"}</td>
      <td className="px-3 py-2">
        <div className="max-w-[220px] truncate text-gray-700" title={item.filename ?? undefined}>
          {item.filename ?? "—"}
        </div>
        {item.row_count != null ? (
          <div className="text-[11px] text-gray-400">{item.row_count} 行</div>
        ) : null}
      </td>
      <td className="px-3 py-2">
        <Badge label={EXPORT_STATUS_LABELS[item.status]} cls={EXPORT_STATUS_TONE[item.status]} />
        {item.status === "failed" && item.error_message ? (
          <div
            className="mt-1 max-w-[220px] text-[11px] text-red-600"
            data-testid={`export-error-${item.id}`}
          >
            {item.error_message}
          </div>
        ) : null}
      </td>
      <td className="px-3 py-2 text-[11px] text-gray-500">
        <div>建 {formatDateTime(item.created_at)}</div>
        {item.finished_at ? <div>完 {formatDateTime(item.finished_at)}</div> : null}
      </td>
      <td className="px-3 py-2">
        {item.status === "completed" && item.has_file ? (
          <a
            href={item.download_url}
            download
            data-testid={`download-${item.id}`}
            className="inline-flex items-center rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-[11px] text-emerald-700 hover:bg-emerald-100"
          >
            ↓ 下载
          </a>
        ) : (
          <span className="text-[11px] text-gray-400">—</span>
        )}
        <div className="mt-1 text-[10px] text-gray-400" data-testid={`download-count-${item.id}`}>
          已下载 {item.download_count} 次
        </div>
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1">
          {canRetry ? (
            <button
              type="button"
              data-testid={`retry-${item.id}`}
              onClick={onRetry}
              disabled={retrying}
              className="rounded border border-brand px-2 py-1 text-[11px] font-medium text-brand hover:bg-brand-light disabled:opacity-50"
            >
              重试
            </button>
          ) : null}
          {canDelete ? (
            <button
              type="button"
              data-testid={`delete-${item.id}`}
              onClick={() => setConfirm(true)}
              className="rounded border border-gray-300 px-2 py-1 text-[11px] text-gray-600 hover:bg-gray-50"
            >
              删除
            </button>
          ) : null}
        </div>
        <ConfirmDialog
          open={confirm}
          title="删除导出记录"
          message={DELETE_MESSAGE}
          confirmLabel="删除记录"
          pending={deleting}
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            onDelete();
            setConfirm(false);
          }}
        />
      </td>
    </tr>
  );
}

// 导出中心内的跳转入口（其它组件可复用）。
export function ExportCenterLink({ className }: { className?: string }) {
  return (
    <Link
      href="/exports"
      data-testid="goto-export-center"
      className={className ?? "text-[11px] text-brand hover:underline"}
    >
      前往导出中心 →
    </Link>
  );
}
