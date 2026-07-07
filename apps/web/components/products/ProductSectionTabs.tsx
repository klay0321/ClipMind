import Link from "next/link";

import { cn } from "@/lib/cn";

// 「产品」主入口的两个分区互链：产品素材（/product-media）与产品目录（/products）。
// 两个页面路由保持独立（各自已有深链与测试），Tab 只做显式互跳。
export function ProductSectionTabs({ current }: { current: "media" | "catalog" }) {
  const tabs = [
    { key: "media", label: "产品素材", href: "/product-media", testId: "product-section-media" },
    { key: "catalog", label: "产品目录", href: "/products", testId: "product-section-catalog" },
  ] as const;
  return (
    <div className="mb-4 flex gap-1 border-b border-gray-200" role="tablist" aria-label="产品分区">
      {tabs.map((t) => (
        <Link
          key={t.key}
          href={t.href}
          role="tab"
          aria-selected={current === t.key}
          data-testid={t.testId}
          className={cn(
            "rounded-t px-3 py-2 text-sm",
            current === t.key
              ? "border-b-2 border-brand font-medium text-brand"
              : "text-gray-500 hover:text-gray-800",
          )}
        >
          {t.label}
        </Link>
      ))}
    </div>
  );
}
