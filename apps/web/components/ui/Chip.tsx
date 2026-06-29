import { cn } from "@/lib/cn";

// 统一状态/标签 chip。状态不只靠颜色，还有文字；色板集中在此处。
export type Tone =
  | "neutral"
  | "brand"
  | "info"
  | "success"
  | "warning"
  | "danger"
  | "muted";

export const TONES: Record<Tone, string> = {
  neutral: "bg-gray-100 text-gray-700",
  brand: "bg-brand-light text-brand-dark",
  info: "bg-blue-50 text-blue-700",
  success: "bg-emerald-50 text-emerald-700",
  warning: "bg-amber-50 text-amber-800",
  danger: "bg-red-50 text-red-700",
  muted: "bg-gray-50 text-gray-400",
};

export function Chip({
  tone = "neutral",
  className,
  children,
  title,
  dot = false,
}: {
  tone?: Tone;
  className?: string;
  children: React.ReactNode;
  title?: string;
  dot?: boolean;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
    >
      {dot ? <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-current opacity-70" /> : null}
      <span className="truncate">{children}</span>
    </span>
  );
}
