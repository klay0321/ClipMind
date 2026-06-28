"use client";

import { cn } from "@/lib/cn";

// 生成带省略号的页码窗口：1 … (p-1) p (p+1) … N
function pageWindow(page: number, totalPages: number): (number | "…")[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  const pages: (number | "…")[] = [1];
  const start = Math.max(2, page - 1);
  const end = Math.min(totalPages - 1, page + 1);
  if (start > 2) pages.push("…");
  for (let i = start; i <= end; i += 1) pages.push(i);
  if (end < totalPages - 1) pages.push("…");
  pages.push(totalPages);
  return pages;
}

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  noun = "素材",
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  noun?: string;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const window = pageWindow(page, totalPages);
  const navBtn =
    "min-w-[2rem] rounded-md border px-2 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-50";

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 px-4 py-3 text-sm text-gray-600">
      <span>
        共 {total} 个{noun} · 第 {page} / {totalPages} 页
      </span>
      <nav className="flex items-center gap-1" aria-label="分页">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className={cn(navBtn, "border-gray-300 bg-white hover:bg-gray-50")}
        >
          上一页
        </button>
        {window.map((p, i) =>
          p === "…" ? (
            <span key={`gap-${i}`} className="px-1 text-gray-400">
              …
            </span>
          ) : (
            <button
              key={p}
              type="button"
              onClick={() => onPageChange(p)}
              aria-current={p === page ? "page" : undefined}
              className={cn(
                navBtn,
                p === page
                  ? "border-brand bg-brand text-white"
                  : "border-gray-300 bg-white hover:bg-gray-50",
              )}
            >
              {p}
            </button>
          ),
        )}
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          className={cn(navBtn, "border-gray-300 bg-white hover:bg-gray-50")}
        >
          下一页
        </button>
      </nav>
    </div>
  );
}
