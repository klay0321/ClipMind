import Link from "next/link";

type NavKey = "assets" | "shots" | "products" | "search";

export function TopNav({ active }: { active?: NavKey }) {
  const linkCls = (key: NavKey) =>
    active === key
      ? "text-brand font-medium"
      : "text-gray-500 hover:text-gray-800";
  return (
    <header className="border-b border-gray-100 bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
        <Link href="/assets" className="text-lg font-semibold text-brand">
          ClipMind
        </Link>
        <nav className="flex items-center gap-4 text-sm">
          <Link href="/assets" className={linkCls("assets")} aria-current={active === "assets" ? "page" : undefined}>
            素材库
          </Link>
          <Link href="/shots" className={linkCls("shots")} aria-current={active === "shots" ? "page" : undefined}>
            镜头库
          </Link>
          <Link href="/products" className={linkCls("products")} aria-current={active === "products" ? "page" : undefined}>
            产品库
          </Link>
          <Link
            href="/search"
            className={linkCls("search")}
            data-testid="nav-search"
            aria-current={active === "search" ? "page" : undefined}
          >
            智能搜索
          </Link>
        </nav>
        <span className="ml-auto hidden text-xs text-gray-400 sm:inline">
          AI 视频素材管理与智能匹配
        </span>
      </div>
    </header>
  );
}
