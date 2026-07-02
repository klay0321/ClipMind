"use client";

import Link from "next/link";
import { useState } from "react";

import { Pagination } from "@/components/Pagination";
import { FinalVideoStatusBadge } from "@/components/StatusBadge";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { TopNav } from "@/components/TopNav";
import { Button, Dialog, Field, SelectInput, TextInput } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAssets, useCreateFinalVideo, useFinalVideos, useProjects } from "@/lib/hooks";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { FinalVideoStatus } from "@/lib/types";

const PAGE_SIZE = 20;

type StatusFilter = "all" | FinalVideoStatus;

export function FinalVideosView() {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [showCreate, setShowCreate] = useState(false);

  const query = useFinalVideos({
    page,
    page_size: PAGE_SIZE,
    q: q.trim() || undefined,
    status: statusFilter === "all" ? undefined : statusFilter,
    include_archived: statusFilter === "all" || statusFilter === "archived",
  });
  const data = query.data;

  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="final-videos" />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-800">成片与使用记录</h1>
          <Button data-testid="toggle-create-final-video" onClick={() => setShowCreate(true)}>
            + 登记成片
          </Button>
        </div>
        <p className="mb-4 text-xs text-gray-500">
          记录最终成片使用了哪些原始镜头。项目中已选择或锁定的镜头只会生成候选引用，
          <span className="font-medium text-gray-700">人工确认后才计入正式使用次数</span>。
        </p>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <input
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            placeholder="按标题搜索…"
            aria-label="按标题搜索成片"
            data-testid="final-video-search"
            className="w-56 rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none"
          />
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value as StatusFilter);
              setPage(1);
            }}
            aria-label="状态筛选"
            className="w-36 rounded border border-gray-300 px-2 py-1.5 text-sm"
          >
            <option value="all">全部状态</option>
            <option value="draft">草稿</option>
            <option value="ready">就绪</option>
            <option value="completed">已完成</option>
            <option value="archived">已归档</option>
          </select>
        </div>

        {query.isLoading ? (
          <Loading rows={6} />
        ) : query.isError ? (
          <ErrorState
            message={(query.error as Error).message}
            onRetry={() => void query.refetch()}
          />
        ) : !data || data.items.length === 0 ? (
          <Empty
            title="还没有成片记录"
            description="登记一条最终成片，然后为它建立与原始镜头的使用血缘。"
          />
        ) : (
          <>
            <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
              <table className="w-full min-w-[880px] text-sm" data-testid="final-video-table">
                <thead>
                  <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                    <th className="px-3 py-2 font-medium">标题</th>
                    <th className="px-3 py-2 font-medium">状态</th>
                    <th className="px-3 py-2 font-medium">成片文件</th>
                    <th className="px-3 py-2 font-medium">时长</th>
                    <th className="px-3 py-2 font-medium">项目 / 脚本</th>
                    <th className="px-3 py-2 font-medium">来源镜头</th>
                    <th className="px-3 py-2 font-medium">已确认</th>
                    <th className="px-3 py-2 font-medium">候选</th>
                    <th className="px-3 py-2 font-medium">完成时间</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((fv) => (
                    <tr
                      key={fv.id}
                      data-testid="final-video-row"
                      className="border-b border-gray-50 last:border-0 hover:bg-gray-50"
                    >
                      <td className="px-3 py-2">
                        <Link
                          href={`/final-videos/${fv.id}`}
                          className="font-medium text-brand hover:underline"
                        >
                          {fv.title}
                        </Link>
                        {fv.version_label ? (
                          <span className="ml-1 text-xs text-gray-400">{fv.version_label}</span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2">
                        <FinalVideoStatusBadge status={fv.status} />
                      </td>
                      <td className="max-w-[180px] truncate px-3 py-2 text-gray-600" title={fv.asset_filename ?? undefined}>
                        {fv.asset_filename ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-gray-600">
                        {fv.asset_duration != null ? formatDuration(fv.asset_duration) : "—"}
                      </td>
                      <td className="max-w-[160px] truncate px-3 py-2 text-gray-600">
                        {[fv.project_name, fv.script_project_name].filter(Boolean).join(" / ") || "—"}
                      </td>
                      <td className="px-3 py-2 text-gray-600">{fv.usage_stats.source_shot_count}</td>
                      <td className="px-3 py-2">
                        <span className="font-medium text-emerald-700">
                          {fv.usage_stats.confirmed_count}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-amber-700">{fv.usage_stats.proposed_count}</td>
                      <td className="px-3 py-2 text-gray-500">
                        {fv.completed_at ? formatDateTime(fv.completed_at) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={data.total}
              onPageChange={setPage}
            />
          </>
        )}
      </main>
      {showCreate ? <CreateFinalVideoDialog onClose={() => setShowCreate(false)} /> : null}
    </div>
  );
}

function CreateFinalVideoDialog({ onClose }: { onClose: () => void }) {
  const [assetQ, setAssetQ] = useState("");
  const [assetId, setAssetId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [versionLabel, setVersionLabel] = useState("");
  const [projectId, setProjectId] = useState<string>("");
  const create = useCreateFinalVideo();

  const assets = useAssets({ page: 1, page_size: 20, q: assetQ.trim() || undefined });
  const projects = useProjects(1, 100, "active");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (assetId == null || !title.trim()) return;
    create.mutate(
      {
        asset_id: assetId,
        title: title.trim(),
        version_label: versionLabel.trim() || undefined,
        project_id: projectId ? Number(projectId) : undefined,
      },
      { onSuccess: onClose },
    );
  };

  return (
    <Dialog open title="登记最终成片" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-3" data-testid="create-final-video-form">
        <Field label="成片媒体文件（已索引 Asset）">
          <input
            value={assetQ}
            onChange={(e) => setAssetQ(e.target.value)}
            placeholder="搜索文件名…"
            data-testid="create-fv-asset-search"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none"
          />
          <div className="mt-1 max-h-40 overflow-y-auto rounded border border-gray-200">
            {assets.data?.items.length ? (
              assets.data.items.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => setAssetId(a.id)}
                  data-testid={`create-fv-asset-${a.id}`}
                  className={`block w-full truncate px-2 py-1.5 text-left text-xs ${
                    assetId === a.id ? "bg-brand/10 font-medium text-brand" : "hover:bg-gray-50"
                  }`}
                >
                  #{a.id} {a.filename}
                </button>
              ))
            ) : (
              <div className="px-2 py-2 text-xs text-gray-400">
                没有匹配素材。成片文件请先通过「素材管理 → 上传」导入索引。
              </div>
            )}
          </div>
        </Field>
        <TextInput
          label="成片标题"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={255}
          placeholder="例如：产品宣传片 6 月投放版"
          data-testid="create-fv-title"
        />
        <div className="grid grid-cols-2 gap-3">
          <TextInput
            label="版本标签"
            value={versionLabel}
            onChange={(e) => setVersionLabel(e.target.value)}
            maxLength={64}
            placeholder="如 v1 / 定稿"
          />
          <SelectInput
            label="绑定项目（可选）"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
          >
            <option value="">不绑定</option>
            {projects.data?.items.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </SelectInput>
        </div>
        {create.isError ? (
          <p className="text-xs text-red-600" data-testid="create-fv-error">
            {create.error instanceof ApiError ? create.error.message : "创建失败"}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            取消
          </Button>
          <Button
            type="submit"
            disabled={assetId == null || !title.trim() || create.isPending}
            data-testid="create-fv-submit"
          >
            {create.isPending ? "创建中…" : "创建成片记录"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
