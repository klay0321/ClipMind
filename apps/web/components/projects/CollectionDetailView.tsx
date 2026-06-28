"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { MemberPicker, type PickerPage } from "@/components/projects/MemberPicker";
import {
  BatchResultNotice,
  ConfirmDialog,
  InlineError,
} from "@/components/projects/widgets";
import { PreviewModal } from "@/components/PreviewModal";
import { ShotCard } from "@/components/ShotCard";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { TopNav } from "@/components/TopNav";
import { api, shotThumbnailUrl } from "@/lib/api";
import {
  useAddCollectionShots,
  useCollection,
  useCollectionShots,
  useDeleteCollection,
  useProject,
  useRemoveCollectionShot,
  useReorderCollectionShots,
  useUpdateCollection,
} from "@/lib/hooks";
import type { BatchMembershipResult } from "@/lib/types";

export function CollectionDetailView({ collectionId }: { collectionId: number }) {
  const collQuery = useCollection(collectionId);
  const collection = collQuery.data;
  const projectQuery = useProject(collection?.project_id ?? null);
  const archived = projectQuery.data?.status === "archived";

  const [page, setPage] = useState(1);
  const pageSize = 24;
  const shotsQuery = useCollectionShots(collectionId, page, pageSize);
  const add = useAddCollectionShots(collectionId, collection?.project_id ?? 0);
  const remove = useRemoveCollectionShot(collectionId, collection?.project_id ?? 0);
  const reorder = useReorderCollectionShots(collectionId);
  const del = useDeleteCollection(collectionId, collection?.project_id ?? 0);
  const update = useUpdateCollection(collectionId, collection?.project_id ?? 0);
  const router = useRouter();

  const [pickerOpen, setPickerOpen] = useState(false);
  const [batch, setBatch] = useState<BatchMembershipResult | null>(null);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [confirmDel, setConfirmDel] = useState(false);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const data = shotsQuery.data;
  const canReorder = !archived && data != null && data.total <= pageSize && data.items.length > 1;

  const fetchVisibleShots = (p: number): Promise<PickerPage> => {
    const pid = collection?.project_id;
    if (pid == null) return Promise.resolve({ items: [], total: 0 });
    return api.projectShots(pid, { source: "all", page: p, page_size: 24 }).then((r) => ({
      total: r.total,
      items: r.items.map((s) => ({
        id: s.id,
        label: `#${s.sequence_no} ${s.asset_filename ?? ""}`,
        sub: `${s.duration.toFixed(1)}s`,
        thumbUrl: s.has_thumbnail ? shotThumbnailUrl(s.id) : undefined,
      })),
    }));
  };

  const move = (index: number, dir: -1 | 1) => {
    if (!data || !collection) return;
    const ids = data.items.map((s) => s.id);
    const j = index + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[index], ids[j]] = [ids[j], ids[index]];
    reorder.mutate({ ids, lockVersion: collection.lock_version });
  };

  const submitEdit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!collection) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    update.mutate(
      { lock_version: collection.lock_version, name: trimmed, description: description.trim() },
      { onSuccess: () => setEditing(false) },
    );
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="projects" />
      <main className="mx-auto max-w-7xl px-4 py-6">
        {collQuery.isLoading ? (
          <Loading rows={3} />
        ) : collQuery.isError ? (
          <ErrorState message={(collQuery.error as Error).message} onRetry={() => collQuery.refetch()} />
        ) : !collection ? null : (
          <>
            <Link href={`/projects/${collection.project_id}`} className="text-sm text-gray-500 hover:text-brand">
              ← 返回项目
            </Link>
            {archived ? (
              <div role="status" className="mt-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                🔒 所属项目已归档，集合当前为只读状态。
              </div>
            ) : null}

            <div className="mt-2 flex items-start justify-between gap-3">
              {editing && !archived ? (
                <form onSubmit={submitEdit} data-testid="edit-collection-form" className="flex-1 space-y-2">
                  <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} aria-label="集合名称" className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
                  <input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} placeholder="描述" aria-label="集合描述" className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
                  <InlineError error={update.error} />
                  <div className="flex gap-2">
                    <button type="submit" disabled={!name.trim() || update.isPending} data-testid="submit-edit-collection" className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">{update.isPending ? "保存中…" : "保存"}</button>
                    <button type="button" onClick={() => setEditing(false)} className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700">取消</button>
                  </div>
                </form>
              ) : (
                <div className="min-w-0">
                  <h1 className="truncate text-xl font-semibold text-gray-800" data-testid="collection-name">{collection.name}</h1>
                  {collection.description ? (<p className="mt-1 text-sm text-gray-500">{collection.description}</p>) : null}
                  <p className="mt-1 text-xs text-gray-400">{collection.shot_count} 个镜头</p>
                </div>
              )}
              {!archived && !editing ? (
                <div className="flex shrink-0 gap-2">
                  <button type="button" onClick={() => { setEditing(true); setName(collection.name); setDescription(collection.description ?? ""); }} data-testid="edit-collection" className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">编辑</button>
                  <button type="button" onClick={() => setConfirmDel(true)} data-testid="delete-collection" className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50">删除集合</button>
                </div>
              ) : null}
            </div>

            <div className="mt-4 flex items-center justify-between">
              <span className="text-sm text-gray-500">集合镜头（同一镜头可属于多个集合）</span>
              <button type="button" onClick={() => setPickerOpen(true)} disabled={archived} data-testid="add-collection-shots" className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-dark">+ 从项目可见镜头添加</button>
            </div>
            <BatchResultNotice result={batch} nounMap={{ completed: "镜头" }} />
            <InlineError error={add.error ?? remove.error ?? reorder.error} />

            {shotsQuery.isLoading ? (
              <Loading rows={3} />
            ) : shotsQuery.isError ? (
              <ErrorState message={(shotsQuery.error as Error).message} onRetry={() => shotsQuery.refetch()} />
            ) : !data || data.items.length === 0 ? (
              <Empty title="集合暂无镜头" description="从项目可见镜头中批量添加。" />
            ) : (
              <>
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                  {data.items.map((s, i) => (
                    <div key={s.id} className="space-y-1" data-testid={`collection-shot-${s.id}`}>
                      <ShotCard shot={s} selected={false} onSelect={(id) => setPreviewId(id)} />
                      <div className="flex items-center gap-1">
                        {canReorder ? (
                          <>
                            <button type="button" aria-label="前移" onClick={() => move(i, -1)} disabled={i === 0 || reorder.isPending} className="rounded border border-gray-300 px-1.5 py-0.5 text-[11px] text-gray-500 disabled:opacity-30">◀</button>
                            <button type="button" aria-label="后移" onClick={() => move(i, 1)} disabled={i === data.items.length - 1 || reorder.isPending} className="rounded border border-gray-300 px-1.5 py-0.5 text-[11px] text-gray-500 disabled:opacity-30">▶</button>
                          </>
                        ) : null}
                        {!archived ? (
                          <button type="button" onClick={() => remove.mutate(s.id)} data-testid={`remove-collection-shot-${s.id}`} className="flex-1 rounded border border-gray-300 px-2 py-0.5 text-[11px] text-gray-600 hover:bg-gray-50">移除</button>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
                {data.total > pageSize ? (
                  <div className="mt-2 flex items-center justify-between text-sm text-gray-500">
                    <span>共 {data.total} 个镜头</span>
                    <div className="flex gap-2">
                      <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="rounded border border-gray-300 px-2 py-0.5 disabled:opacity-50">上一页</button>
                      <button type="button" onClick={() => setPage((p) => p + 1)} disabled={page >= Math.ceil(data.total / pageSize)} className="rounded border border-gray-300 px-2 py-0.5 disabled:opacity-50">下一页</button>
                    </div>
                  </div>
                ) : null}
              </>
            )}

            <PreviewModal shotId={previewId} onClose={() => setPreviewId(null)} />
            <MemberPicker open={pickerOpen} title="从项目可见镜头添加到集合" queryKey={`coll-${collectionId}-visible`} searchable={false} fetchPage={fetchVisibleShots} pending={add.isPending} onClose={() => setPickerOpen(false)} onAdd={(ids) => add.mutate(ids, { onSuccess: (r) => { setBatch(r); setPickerOpen(false); } })} />
            <ConfirmDialog open={confirmDel} title="删除集合" message="只删除集合和关联，不删除镜头。确定删除该集合？" confirmLabel="删除集合" pending={del.isPending} onCancel={() => setConfirmDel(false)} onConfirm={() => del.mutate(undefined, { onSuccess: () => router.push(`/projects/${collection.project_id}`) })} />
          </>
        )}
      </main>
    </div>
  );
}
