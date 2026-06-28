"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

export interface PickerItem {
  id: number;
  label: string;
  sub?: string;
  thumbUrl?: string;
}

export interface PickerPage {
  items: PickerItem[];
  total: number;
}

// 通用成员选择器：父级提供 fetchPage（映射分页/搜索 API 到 PickerItem），不一次加载全部对象。
export function MemberPicker({
  open,
  title,
  queryKey,
  fetchPage,
  searchable = true,
  pageSize = 24,
  pending,
  onAdd,
  onClose,
}: {
  open: boolean;
  title: string;
  queryKey: string;
  fetchPage: (page: number, q: string) => Promise<PickerPage>;
  searchable?: boolean;
  pageSize?: number;
  pending?: boolean;
  onAdd: (ids: number[]) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 300);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => setPage(1), [debouncedQ]);

  useEffect(() => {
    if (!open) {
      setSelected(new Set());
      setQ("");
      setDebouncedQ("");
      setPage(1);
      return;
    }
    restoreRef.current = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      restoreRef.current?.focus?.();
    };
  }, [open, onClose]);

  const query = useQuery({
    queryKey: ["member-picker", queryKey, debouncedQ, page, pageSize],
    queryFn: () => fetchPage(page, debouncedQ),
    enabled: open,
    placeholderData: keepPreviousData,
  });

  if (!open) return null;
  const data = query.data;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
    >
      <div
        className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-lg bg-white shadow-lg"
        onClick={(e) => e.stopPropagation()}
        data-testid="member-picker"
      >
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
          <h2 className="text-base font-semibold text-gray-800">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
          >
            ✕
          </button>
        </div>
        {searchable ? (
          <div className="border-b border-gray-100 px-4 py-2">
            <label className="sr-only" htmlFor="picker-search">
              搜索
            </label>
            <input
              id="picker-search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="按名称搜索…"
              className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-brand focus:outline-none"
            />
          </div>
        ) : null}
        <div className="min-h-[200px] flex-1 overflow-y-auto px-2 py-2" data-testid="picker-list">
          {query.isLoading ? (
            <div className="p-4 text-sm text-gray-400">加载中…</div>
          ) : query.isError ? (
            <div role="alert" className="p-4 text-sm text-red-600">
              加载失败
            </div>
          ) : !data || data.items.length === 0 ? (
            <div data-testid="picker-empty" className="p-4 text-sm text-gray-400">
              无可选项
            </div>
          ) : (
            <ul className="space-y-1">
              {data.items.map((it) => (
                <li key={it.id}>
                  <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-gray-50">
                    <input
                      type="checkbox"
                      checked={selected.has(it.id)}
                      onChange={() => toggle(it.id)}
                      data-testid={`picker-item-${it.id}`}
                    />
                    {it.thumbUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={it.thumbUrl}
                        alt=""
                        className="h-8 w-12 rounded object-cover"
                        loading="lazy"
                      />
                    ) : null}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-gray-800">{it.label}</span>
                      {it.sub ? (
                        <span className="block truncate text-xs text-gray-400">{it.sub}</span>
                      ) : null}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex items-center justify-between border-t border-gray-100 px-4 py-2 text-sm">
          <div className="flex items-center gap-2 text-gray-500">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded border border-gray-300 px-2 py-0.5 disabled:opacity-50"
            >
              上一页
            </button>
            <span>
              {page}/{totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="rounded border border-gray-300 px-2 py-0.5 disabled:opacity-50"
            >
              下一页
            </button>
          </div>
          <button
            type="button"
            onClick={() => onAdd(Array.from(selected))}
            disabled={selected.size === 0 || pending}
            data-testid="picker-add"
            className="rounded bg-brand px-3 py-1.5 font-medium text-white disabled:opacity-50 hover:bg-brand-dark"
          >
            {pending ? "添加中…" : `添加 ${selected.size} 项`}
          </button>
        </div>
      </div>
    </div>
  );
}
