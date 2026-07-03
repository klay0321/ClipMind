import Link from "next/link";

import { Menu } from "@/components/ui/Menu";
import { cn } from "@/lib/cn";

type NavKey =
  | "projects"
  | "assets"
  | "shots"
  | "products"
  | "search"
  | "script"
  | "final-videos"
  | "usage-review"
  | "usage-evidence"
  | "exports"
  | "favorites";

// 主导航：按运营主流程排列；产品库 / 收藏 降权收进「更多」。命名统一为面向用户的功能名。
const PRIMARY: { key: NavKey; href: string; label: string; testId?: string }[] = [
  { key: "assets", href: "/assets", label: "素材管理" },
  { key: "shots", href: "/shots", label: "AI 镜头拆解" },
  { key: "search", href: "/search", label: "智能匹配", testId: "nav-search" },
  { key: "script", href: "/script", label: "脚本剪辑", testId: "nav-script" },
  { key: "projects", href: "/projects", label: "项目", testId: "nav-projects" },
  { key: "final-videos", href: "/final-videos", label: "成片与使用记录", testId: "nav-final-videos" },
  { key: "usage-review", href: "/usage-review", label: "使用记录中心", testId: "nav-usage-review" },
  { key: "exports", href: "/exports", label: "导出", testId: "nav-exports" },
];

export function TopNav({ active }: { active?: NavKey }) {
  const linkCls = (key: NavKey) =>
    active === key ? "text-brand font-medium" : "text-gray-500 hover:text-gray-800";
  const moreActive =
    active === "products" || active === "favorites" || active === "usage-evidence";

  return (
    <header className="border-b border-gray-100 bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
        <Link href="/assets" className="flex shrink-0 flex-col leading-none">
          <span className="text-lg font-semibold text-brand">ClipMind</span>
          <span className="hidden text-[10px] text-gray-400 sm:inline">AI 视频素材管理与镜头匹配</span>
        </Link>
        <nav className="flex min-w-0 items-center gap-4 overflow-x-auto text-sm" aria-label="主导航">
          {PRIMARY.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              data-testid={item.testId}
              aria-current={active === item.key ? "page" : undefined}
              className={cn("shrink-0 whitespace-nowrap", linkCls(item.key))}
            >
              {item.label}
            </Link>
          ))}
          <Menu
            align="right"
            triggerAriaLabel="更多"
            triggerClassName={cn(
              "shrink-0 whitespace-nowrap text-sm",
              moreActive ? "text-brand font-medium" : "text-gray-500 hover:text-gray-800",
            )}
            trigger={<span>更多 ▾</span>}
            items={[
              { key: "products", label: "产品库", href: "/products" },
              { key: "usage-evidence", label: "历史使用证据", href: "/usage-evidence" },
              { key: "favorites", label: "收藏", href: "/favorites" },
            ]}
          />
        </nav>
      </div>
    </header>
  );
}
