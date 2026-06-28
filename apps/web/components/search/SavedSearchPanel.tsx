// 保存搜索面板：保存当前搜索条件 → 列表加载（还原表单并重跑）/ 重命名 / 删除。
// query 为序列化的 ShotSearchRequest（后端剥离分页）；加载时由父组件用 requestToForm 还原真实条件。
// 所有持久化走真实 /saved-searches API，前端不在本地伪造保存状态。
"use client";

import { useState } from "react";

import { ConfirmDialog, InlineError } from "@/components/projects/widgets";
import { formatDateTime } from "@/lib/format";
import {
  useCreateSavedSearch,
  useDeleteSavedSearch,
  useSavedSearches,
  useUpdateSavedSearch,
} from "@/lib/hooks";
import type { SavedSearch, SavedSearchKind } from "@/lib/types";

export function SavedSearchPanel({
  searchKind,
  currentQuery,
  canSave,
  onLoad,
}: {
  searchKind: SavedSearchKind;
  // 当前已提交的搜索请求（序列化 query；null 表示尚无可保存条件）
  currentQuery: Record<string, unknown> | null;
  canSave: boolean;
  onLoad: (saved: SavedSearch) => void;
}) {
  const listQ = useSavedSearches(undefined, searchKind, 1, 50);
  const create = useCreateSavedSearch();
  const [name, setName] = useState("");
  const [showSave, setShowSave] = useState(false);

  const items = listQ.data?.items ?? [];

  const onSave = () => {
    const trimmed = name.trim();
    if (!trimmed || !currentQuery) return;
    create.mutate(
      { name: trimmed, search_kind: searchKind, query: currentQuery },
      {
        onSuccess: () => {
          setName("");
          setShowSave(false);
        },
      },
    );
  };

  return (
    <div className="space-y-2 rounded-lg border border-gray-200 bg-white p-3" data-testid="saved-search-panel">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-gray-700">保存的搜索</span>
        <button
          type="button"
          data-testid="save-search"
          onClick={() => setShowSave((v) => !v)}
          disabled={!canSave}
          title={!canSave ? "请先输入搜索条件并搜索后再保存" : undefined}
          className="rounded border border-brand px-2 py-1 text-[11px] font-medium text-brand hover:bg-brand-light disabled:opacity-50"
        >
          保存当前搜索
        </button>
      </div>

      {showSave && canSave ? (
        <div className="space-y-2 rounded border border-gray-100 bg-gray-50 p-2" data-testid="save-search-form">
          <label className="sr-only" htmlFor="saved-search-name">
            搜索名称
          </label>
          <input
            id="saved-search-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            placeholder="如：竖屏产品特写 · 已确认"
            className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
          />
          <InlineError error={create.error} />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowSave(false)}
              className="rounded border border-gray-300 px-2 py-1 text-[11px] text-gray-600 hover:bg-gray-50"
            >
              取消
            </button>
            <button
              type="button"
              data-testid="confirm-save-search"
              onClick={onSave}
              disabled={!name.trim() || create.isPending}
              className="rounded bg-brand px-2 py-1 text-[11px] font-medium text-white hover:bg-brand-dark disabled:opacity-50"
            >
              {create.isPending ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      ) : null}

      {items.length === 0 ? (
        <p className="text-[11px] text-gray-400">还没有保存的搜索。搜索后点「保存当前搜索」可复用条件。</p>
      ) : (
        <ul className="space-y-1" data-testid="saved-search-list">
          {items.map((s) => (
            <SavedSearchRow key={s.id} saved={s} onLoad={onLoad} />
          ))}
        </ul>
      )}
    </div>
  );
}

function SavedSearchRow({
  saved,
  onLoad,
}: {
  saved: SavedSearch;
  onLoad: (saved: SavedSearch) => void;
}) {
  const update = useUpdateSavedSearch(saved.id);
  const del = useDeleteSavedSearch();
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(saved.name);
  const [confirm, setConfirm] = useState(false);

  const submitRename = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    update.mutate(
      { lock_version: saved.lock_version, name: trimmed },
      { onSuccess: () => setRenaming(false) },
    );
  };

  return (
    <li
      data-testid={`saved-search-${saved.id}`}
      className="flex items-center gap-2 rounded border border-gray-100 px-2 py-1.5"
    >
      {renaming ? (
        <form
          className="flex flex-1 items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            submitRename();
          }}
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="重命名搜索"
            maxLength={200}
            className="min-w-0 flex-1 rounded border border-gray-300 px-2 py-1 text-xs"
          />
          <button
            type="submit"
            disabled={!name.trim() || update.isPending}
            className="rounded bg-brand px-2 py-1 text-[11px] text-white disabled:opacity-50"
          >
            保存
          </button>
          <button
            type="button"
            onClick={() => {
              setRenaming(false);
              setName(saved.name);
            }}
            className="rounded border border-gray-300 px-2 py-1 text-[11px] text-gray-600"
          >
            取消
          </button>
        </form>
      ) : (
        <>
          <button
            type="button"
            data-testid={`load-saved-${saved.id}`}
            onClick={() => onLoad(saved)}
            className="min-w-0 flex-1 truncate text-left text-xs font-medium text-gray-800 hover:text-brand"
            title={`加载并运行：${saved.name}`}
          >
            {saved.name}
          </button>
          <span className="shrink-0 text-[10px] text-gray-400">{formatDateTime(saved.updated_at)}</span>
          <button
            type="button"
            data-testid={`run-saved-${saved.id}`}
            onClick={() => onLoad(saved)}
            className="shrink-0 rounded border border-gray-300 px-2 py-0.5 text-[11px] text-gray-600 hover:bg-gray-50"
          >
            运行
          </button>
          <button
            type="button"
            data-testid={`rename-saved-${saved.id}`}
            onClick={() => {
              setRenaming(true);
              setName(saved.name);
            }}
            className="shrink-0 rounded border border-gray-300 px-2 py-0.5 text-[11px] text-gray-600 hover:bg-gray-50"
          >
            重命名
          </button>
          <button
            type="button"
            data-testid={`delete-saved-${saved.id}`}
            onClick={() => setConfirm(true)}
            className="shrink-0 rounded border border-gray-300 px-2 py-0.5 text-[11px] text-gray-600 hover:bg-gray-50"
          >
            删除
          </button>
        </>
      )}
      <InlineError error={update.error ?? del.error} />
      <ConfirmDialog
        open={confirm}
        title="删除保存的搜索"
        message="只删除这条保存的搜索条件，不影响任何镜头或素材。确定删除？"
        confirmLabel="删除"
        pending={del.isPending}
        onCancel={() => setConfirm(false)}
        onConfirm={() => del.mutate(saved.id, { onSuccess: () => setConfirm(false) })}
      />
    </li>
  );
}
