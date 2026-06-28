import { cn } from "@/lib/cn";

// 与真实布局对应的骨架，避免「24 个卡片只显示 5 根灰条」的破碎感。
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-gray-200", className)} />;
}

export function CardGridSkeleton({ count = 8, className }: { count?: number; className?: string }) {
  return (
    <div
      data-testid="loading"
      className={cn("grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4", className)}
    >
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="overflow-hidden rounded-lg border border-gray-200">
          <Skeleton className="aspect-video rounded-none" />
          <div className="space-y-2 p-2">
            <Skeleton className="h-3 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function TableRowSkeleton({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div data-testid="loading" className="divide-y divide-gray-50">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-4 px-4 py-3">
          <Skeleton className="h-10 w-16 shrink-0" />
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} className="h-3 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

export function PanelSkeleton() {
  return (
    <div data-testid="loading" className="space-y-3 p-4">
      <Skeleton className="aspect-video w-full" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-5/6" />
    </div>
  );
}
