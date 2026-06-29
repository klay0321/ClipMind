import { cn } from "@/lib/cn";

// 统一卡片容器：白底、统一圆角与边框。interactive 时给 hover/焦点反馈。
export function Card({
  className,
  interactive = false,
  children,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      className={cn(
        "rounded-lg border border-gray-200 bg-white shadow-sm",
        interactive && "transition hover:border-gray-300 hover:shadow",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  actions,
  className,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3",
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="truncate text-base font-semibold text-gray-900">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-xs text-gray-500">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
