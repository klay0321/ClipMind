// 动态集合区块（项目集合 Tab 内）：与静态集合明确区分。
// 动态集合按当前素材与搜索索引实时更新，不保存固定镜头成员；可创建/打开实时镜头网格/编辑/删除。
// 归档项目 → 只读。所有镜头来自真实 /dynamic-collections/{id}/shots（搜索响应结构），用 SearchResultCard 渲染。
"use client";

import { useState } from "react";

import {
  ConfirmDialog,
  InlineError,
} from "@/components/projects/widgets";
import { PreviewModal } from "@/components/PreviewModal";
import { SearchResultCard } from "@/components/search/SearchResultCard";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { SAVED_SEARCH_KIND_LABELS } from "@/lib/exports";
import { formatDateTime } from "@/lib/format";
import {
  useCreateDynamicCollection,
  useDeleteDynamicCollection,
  useDynamicCollections,
  useDynamicCollectionShots,
  useUpdateDynamicCollection,
} from "@/lib/hooks";
import type {
  DynamicCollection,
  SavedSearchKind,
  SearchResultItem,
  ShotSearchResponse,
} from "@/lib/types";

const DYNAMIC_HINT = "动态集合会根据当前素材和搜索索引实时更新，不保存固定镜头成员。";
const ARCHIVED_HINT = "项目已归档（只读），恢复后可编辑。";

export function DynamicCollectionsSection({
  projectId,
  archived,
}: {
  projectId: number;
  archived: boolean;
}) {
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const query = useDynamicCollections(projectId, page, pageSize);
  const create = useCreateDynamicCollection(projectId);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [queryText, setQueryText] = useState("");
  const [kind, setKind] = useState<SavedSearchKind>("shot_search");
  const [openId, setOpenId] = useState<number | null>(null);
  const data = query.data;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    const q = queryText.trim();
    if (!trimmed || !q) return;
    // 简单 query：以查询词构造（shot_search → {query}; description_match → {target_description}）。
    const queryPayload: Record<string, unknown> =
      kind === "description_match" ? { target_description: q } : { query: q };
    create.mutate(
      { name: trimmed, description: description.trim() || undefined, search_kind: kind, query: queryPayload },
      {
        onSuccess: () => {
          setName("");
          setDescription("");
          setQueryText("");
          setShowCreate(false);
        },
      },
    );
  };

  return (
    <section className="space-y-3" data-testid="dynamic-collections">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">动态集合</h3>
          <p className="text-xs text-gray-500">{DYNAMIC_HINT}</p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate((v) => !v)}
          disabled={archived}
          title={archived ? ARCHIVED_HINT : undefined}
          data-testid="create-dynamic-collection"
          className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-dark"
        >
          + 新建动态集合
        </button>
      </div>

      {showCreate && !archived ? (
        <form
          onSubmit={submit}
          data-testid="create-dynamic-form"
          className="space-y-2 rounded-lg border border-gray-200 bg-white p-3"
        >
          <label className="sr-only" htmlFor="dyn-name">
            动态集合名称
          </label>
          <input
            id="dyn-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            placeholder="如：竖屏产品特写（实时）"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
          />
          <label className="sr-only" htmlFor="dyn-kind">
            搜索类型
          </label>
          <select
            id="dyn-kind"
            data-testid="dynamic-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as SavedSearchKind)}
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
          >
            {(["shot_search", "description_match"] as SavedSearchKind[]).map((k) => (
              <option key={k} value={k}>
                {SAVED_SEARCH_KIND_LABELS[k]}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="dyn-query">
            查询条件
          </label>
          <input
            id="dyn-query"
            data-testid="dynamic-query"
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            maxLength={500}
            placeholder="输入查询词或画面需求"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
          />
          <label className="sr-only" htmlFor="dyn-desc">
            描述
          </label>
          <input
            id="dyn-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={2000}
            placeholder="描述（可选）"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
          />
          <InlineError error={create.error} />
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={!name.trim() || !queryText.trim() || create.isPending}
              data-testid="submit-dynamic-collection"
              className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-dark"
            >
              {create.isPending ? "创建中…" : "创建"}
            </button>
          </div>
        </form>
      ) : null}

      {query.isLoading ? (
        <Loading rows={2} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : !data || data.items.length === 0 ? (
        <Empty title="暂无动态集合" description="新建动态集合，按实时搜索条件持续展示匹配镜头。" />
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {data.items.map((c) => (
            <DynamicCollectionRow
              key={c.id}
              collection={c}
              projectId={projectId}
              archived={archived}
              onOpen={() => setOpenId(c.id === openId ? null : c.id)}
              opened={c.id === openId}
            />
          ))}
        </ul>
      )}

      {data && data.total > pageSize ? (
        <div className="flex items-center justify-between px-1 text-sm text-gray-500">
          <span>共 {data.total} 个动态集合</span>
          <div className="flex gap-2">
            <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="rounded border border-gray-300 px-2 py-0.5 disabled:opacity-50">上一页</button>
            <button type="button" onClick={() => setPage((p) => p + 1)} disabled={page >= Math.ceil(data.total / pageSize)} className="rounded border border-gray-300 px-2 py-0.5 disabled:opacity-50">下一页</button>
          </div>
        </div>
      ) : null}

      {openId != null ? <DynamicCollectionShots collectionId={openId} /> : null}
    </section>
  );
}

function DynamicCollectionRow({
  collection,
  projectId,
  archived,
  onOpen,
  opened,
}: {
  collection: DynamicCollection;
  projectId: number;
  archived: boolean;
  onOpen: () => void;
  opened: boolean;
}) {
  const del = useDeleteDynamicCollection(projectId);
  const update = useUpdateDynamicCollection(collection.id, projectId);
  const [confirm, setConfirm] = useState(false);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(collection.name);

  const submitEdit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    update.mutate(
      { lock_version: collection.lock_version, name: trimmed },
      { onSuccess: () => setEditing(false) },
    );
  };

  return (
    <li
      className="flex flex-col rounded-lg border border-gray-200 bg-white p-3"
      data-testid={`dynamic-collection-${collection.id}`}
    >
      {editing && !archived ? (
        <form onSubmit={submitEdit} className="space-y-2" data-testid={`edit-dynamic-form-${collection.id}`}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="动态集合名称"
            maxLength={200}
            className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
          />
          <InlineError error={update.error} />
          <div className="flex gap-2">
            <button type="submit" disabled={!name.trim() || update.isPending} data-testid={`submit-edit-dynamic-${collection.id}`} className="rounded bg-brand px-2 py-1 text-[11px] text-white disabled:opacity-50">保存</button>
            <button type="button" onClick={() => { setEditing(false); setName(collection.name); }} className="rounded border border-gray-300 px-2 py-1 text-[11px] text-gray-600">取消</button>
          </div>
        </form>
      ) : (
        <>
          <div className="flex items-start justify-between gap-2">
            <button
              type="button"
              data-testid={`open-dynamic-${collection.id}`}
              onClick={onOpen}
              className="min-w-0 flex-1 text-left text-sm font-medium text-gray-800 hover:text-brand"
            >
              <span className="block truncate">{collection.name}</span>
            </button>
            <span className="shrink-0 rounded bg-violet-100 px-1.5 py-0.5 text-[10px] text-violet-700">
              {SAVED_SEARCH_KIND_LABELS[collection.search_kind]}
            </span>
          </div>
          {collection.description ? (
            <p className="mt-1 line-clamp-2 text-xs text-gray-500">{collection.description}</p>
          ) : null}
          <p className="mt-1 text-[11px] text-gray-400">{DYNAMIC_HINT}</p>
          <div className="mt-2 flex items-center justify-between border-t border-gray-100 pt-2 text-[11px] text-gray-400">
            <span>更新于 {formatDateTime(collection.updated_at)}</span>
            {!archived ? (
              <div className="flex gap-1">
                <button type="button" onClick={() => { setEditing(true); setName(collection.name); }} data-testid={`edit-dynamic-${collection.id}`} className="rounded border border-gray-300 px-2 py-0.5 text-gray-600 hover:bg-gray-50">编辑</button>
                <button type="button" onClick={() => setConfirm(true)} data-testid={`delete-dynamic-${collection.id}`} className="rounded border border-gray-300 px-2 py-0.5 text-gray-600 hover:bg-gray-50">删除</button>
              </div>
            ) : null}
          </div>
        </>
      )}
      {opened ? (
        <span className="mt-2 text-[11px] font-medium text-brand">实时镜头展示于下方 ↓</span>
      ) : null}
      <InlineError error={del.error} />
      <ConfirmDialog
        open={confirm}
        title="删除动态集合"
        message="只删除动态集合定义，不删除任何镜头或素材。确定删除？"
        confirmLabel="删除"
        pending={del.isPending}
        onCancel={() => setConfirm(false)}
        onConfirm={() => del.mutate(collection.id, { onSuccess: () => setConfirm(false) })}
      />
    </li>
  );
}

function DynamicCollectionShots({ collectionId }: { collectionId: number }) {
  const [page, setPage] = useState(1);
  const pageSize = 24;
  const q = useDynamicCollectionShots(collectionId, page, pageSize);
  const [previewId, setPreviewId] = useState<number | null>(null);
  // 响应结构与搜索一致：items 为 SearchResultItem[]
  const data = q.data as ShotSearchResponse | undefined;
  const items: SearchResultItem[] = data?.items ?? [];
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="rounded-lg border border-violet-200 bg-violet-50/40 p-3" data-testid="dynamic-collection-shots">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-violet-800">动态集合实时镜头</span>
        {data ? <span className="text-[11px] text-gray-500">匹配 {data.total} 个</span> : null}
      </div>
      {q.isLoading ? (
        <Loading rows={2} />
      ) : q.isError ? (
        <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />
      ) : items.length === 0 ? (
        <Empty title="当前无匹配镜头" description="动态集合随素材与索引实时更新，稍后可能出现新匹配。" />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((item) => (
              <SearchResultCard
                key={item.shot_id}
                item={item}
                selected={false}
                onSelect={() => undefined}
                onPreview={setPreviewId}
              />
            ))}
          </div>
          {data && data.total > pageSize ? (
            <div className="mt-2 flex items-center justify-between text-sm text-gray-500">
              <span>第 {page} / {totalPages} 页</span>
              <div className="flex gap-2">
                <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="rounded border border-gray-300 px-2 py-0.5 disabled:opacity-50">上一页</button>
                <button type="button" onClick={() => setPage((p) => p + 1)} disabled={page >= totalPages} className="rounded border border-gray-300 px-2 py-0.5 disabled:opacity-50">下一页</button>
              </div>
            </div>
          ) : null}
        </>
      )}
      <PreviewModal shotId={previewId} onClose={() => setPreviewId(null)} />
    </div>
  );
}
