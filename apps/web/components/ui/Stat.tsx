import { cn } from "@/lib/cn";
import type { Tone } from "@/components/ui/Chip";

// 统计数字卡：素材总览、镜头拆解完成度等汇总区复用。
const VALUE_TONE: Record<Tone, string> = {
  neutral: "text-gray-900",
  brand: "text-brand-dark",
  info: "text-blue-700",
  success: "text-emerald-700",
  warning: "text-amber-700",
  danger: "text-red-600",
  muted: "text-gray-400",
};

export interface StatItem {
  label: string;
  value: React.ReactNode;
  tone?: Tone;
  hint?: string;
}

export function StatGrid({
  items,
  className,
}: {
  items: StatItem[];
  className?: string;
}) {
  return (
    <div className={cn("grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6", className)}>
      {items.map((it) => (
        <div
          key={it.label}
          title={it.hint}
          className="rounded-md border border-gray-100 bg-gray-50/60 px-3 py-2"
        >
          <div className={cn("text-lg font-semibold tabular-nums", VALUE_TONE[it.tone ?? "neutral"])}>
            {it.value}
          </div>
          <div className="text-[11px] text-gray-500">{it.label}</div>
        </div>
      ))}
    </div>
  );
}
