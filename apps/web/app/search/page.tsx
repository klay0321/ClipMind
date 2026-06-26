import { SearchWorkbench } from "@/components/search/SearchWorkbench";
import { decodeSearchUrl } from "@/lib/search";

// 读取 URL 核心搜索状态需在请求时进行（动态渲染），避免静态预渲染告警。
export const dynamic = "force-dynamic";

export default function SearchPage({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const flat: Record<string, string | undefined> = {};
  for (const [k, v] of Object.entries(searchParams ?? {})) {
    flat[k] = Array.isArray(v) ? v[0] : v;
  }
  const initial = decodeSearchUrl(flat);
  return <SearchWorkbench initial={initial} />;
}
