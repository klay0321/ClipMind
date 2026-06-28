"use client";

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
  return (
    <div className="flex items-center justify-between border-t border-gray-100 px-4 py-3 text-sm text-gray-600">
      <span>
        共 {total} 个{noun} · 第 {page} / {totalPages} 页
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="rounded-md border border-gray-300 bg-white px-3 py-1 disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-50"
        >
          上一页
        </button>
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          className="rounded-md border border-gray-300 bg-white px-3 py-1 disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-50"
        >
          下一页
        </button>
      </div>
    </div>
  );
}
