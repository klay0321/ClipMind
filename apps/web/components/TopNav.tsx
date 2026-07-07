import Link from "next/link";

import { Menu } from "@/components/ui/Menu";
import { cn } from "@/lib/cn";

type NavKey =
  | "dashboard"
  | "projects"
  | "assets"
  | "shots"
  | "products"
  | "search"
  | "script"
  | "final-videos"
  | "usage-review"
  | "usage-evidence"
  | "visual-experiments"
  | "product-media"
  | "exports"
  | "favorites";

// 主导航收敛为 6 个运营主入口；工作流类页面（脚本剪辑/导出/收藏）进「更多」。
const PRIMARY: { key: NavKey; href: string; label: string; testId?: string }[] = [
  { key: "assets", href: "/assets", label: "素材库", testId: "nav-assets" },
  { key: "search", href: "/search", label: "搜索", testId: "nav-search" },
  { key: "shots", href: "/shots", label: "镜头库", testId: "nav-shots" },
  { key: "product-media", href: "/product-media", label: "产品", testId: "nav-products-hub" },
  { key: "projects", href: "/projects", label: "项目", testId: "nav-projects" },
  { key: "usage-review", href: "/usage-review", label: "使用记录", testId: "nav-usage-review" },
];

// 子页/旧路由高亮到所属主入口：成片登记与历史证据并入「使用记录」，
// 产品目录与产品素材共用「产品」。调用方无需改 active 取值。
const ALIAS: Partial<Record<NavKey, NavKey>> = {
  "final-videos": "usage-review",
  "usage-evidence": "usage-review",
  products: "product-media",
};

export function TopNav({ active }: { active?: NavKey }) {
  const effective = active ? (ALIAS[active] ?? active) : undefined;
  const linkCls = (key: NavKey) =>
    effective === key ? "text-brand font-medium" : "text-gray-500 hover:text-gray-800";
  const moreActive =
    effective === "script" || effective === "exports" || effective === "favorites" ||
    effective === "visual-experiments";

  return (
    <header className="border-b border-gray-100 bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
        <Link href="/" className="flex shrink-0 flex-col leading-none" data-testid="nav-home">
          <span className="text-lg font-semibold text-brand">ClipMind</span>
          <span className="hidden text-[10px] text-gray-400 sm:inline">AI 视频素材管理与镜头匹配</span>
        </Link>
        {/* 「更多」菜单必须在 overflow-x-auto 容器之外，否则下拉面板被裁剪不可见 */}
        <nav
          className="flex min-w-0 flex-1 items-center gap-4 overflow-x-auto text-sm"
          aria-label="主导航"
        >
          {PRIMARY.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              data-testid={item.testId}
              aria-current={effective === item.key ? "page" : undefined}
              className={cn("shrink-0 whitespace-nowrap", linkCls(item.key))}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <Menu
          align="right"
          triggerAriaLabel="更多"
          triggerTestId="nav-more"
          triggerClassName={cn(
            "shrink-0 whitespace-nowrap text-sm",
            moreActive ? "text-brand font-medium" : "text-gray-500 hover:text-gray-800",
          )}
          trigger={<span>更多 ▾</span>}
          items={[
            // 旧主导航项降权保留；/products、/final-videos、/usage-evidence、
            // /product-visual-experiments 路由不删，可直达 URL
            { key: "script", label: "脚本剪辑", href: "/script", testId: "nav-script" },
            { key: "exports", label: "导出", href: "/exports", testId: "nav-exports" },
            { key: "favorites", label: "收藏", href: "/favorites", testId: "nav-favorites" },
          ]}
        />
      </div>
    </header>
  );
}
