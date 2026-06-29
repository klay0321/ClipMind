// 统一搜索工作台：模式切换（素材语义搜索 / 画面描述匹配）+ 索引状态 + 共享详情抽屉 / 预览弹窗。
// 复用同一套搜索表单 / 筛选 / 结果卡 / 解释面板 / 状态组件，不复制两套前端逻辑。
// 核心搜索状态（mode/q/搜索模式/排序/页/产品）同步到 URL，刷新可恢复；不写入任何敏感信息。
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { TopNav } from "@/components/TopNav";
import { PreviewModal } from "@/components/PreviewModal";
import { EMPTY_SEARCH_FORM, encodeSearchUrl } from "@/lib/search";
import type { SearchFormState, SearchUrlState } from "@/lib/search";
import type { DescriptionMatchItem, SearchResultItem } from "@/lib/types";

import { DescriptionMatchView } from "./DescriptionMatchView";
import { IndexStatusIndicator } from "./IndexStatusIndicator";
import { SearchResultDrawer } from "./SearchResultDrawer";
import { SemanticSearchView } from "./SemanticSearchView";

type Mode = "search" | "description";

interface Core {
  query: string;
  searchMode: SearchFormState["mode"];
  sort: SearchFormState["sort"];
  page: number;
  productId: number | null;
}

export function SearchWorkbench({ initial }: { initial: SearchUrlState }) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>(initial.mode);
  const [core, setCore] = useState<Core>({
    query: initial.query,
    searchMode: initial.searchMode,
    sort: initial.sort,
    page: initial.page,
    productId: initial.productId,
  });
  const [drawerItem, setDrawerItem] = useState<SearchResultItem | DescriptionMatchItem | null>(null);
  const [previewShotId, setPreviewShotId] = useState<number | null>(null);

  const writeUrl = (m: Mode, c: Core) => {
    const params = encodeSearchUrl({
      mode: m,
      query: c.query,
      searchMode: c.searchMode,
      sort: c.sort,
      page: c.page,
      productId: c.productId,
    });
    const qs = params.toString();
    router.replace(qs ? `/search?${qs}` : "/search", { scroll: false });
  };

  const switchMode = (m: Mode) => {
    setMode(m);
    setDrawerItem(null);
    writeUrl(m, core);
  };

  const onCoreChange = (form: SearchFormState, page: number) => {
    const c: Core = {
      query: form.query,
      searchMode: form.mode,
      sort: form.sort,
      page,
      productId: form.productId,
    };
    setCore(c);
    writeUrl("search", c);
  };

  const initialForm: SearchFormState = {
    ...EMPTY_SEARCH_FORM,
    query: initial.query,
    mode: initial.searchMode,
    sort: initial.sort,
    productId: initial.productId,
  };

  return (
    <div>
      <TopNav active="search" />
      <main className="mx-auto max-w-7xl space-y-4 p-4">
        {/* 顶部：标题 + 模式切换 + 索引状态 */}
        <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">智能匹配</h1>
            <p className="text-sm text-gray-500">
              用自然语言检索镜头素材，或输入一句画面需求快速找到可用镜头。
            </p>
          </div>
          <div className="flex items-center gap-3">
            <IndexStatusIndicator />
          </div>
        </header>

        <div
          className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5 text-sm"
          role="tablist"
          aria-label="搜索模式"
        >
          <button
            type="button"
            role="tab"
            id="tab-search"
            aria-selected={mode === "search"}
            aria-controls="panel-search"
            data-testid="tab-search"
            onClick={() => switchMode("search")}
            className={`rounded-md px-3 py-1.5 font-medium ${
              mode === "search" ? "bg-brand text-white" : "text-gray-600 hover:bg-gray-50"
            }`}
          >
            素材语义搜索
          </button>
          <button
            type="button"
            role="tab"
            id="tab-description"
            aria-selected={mode === "description"}
            aria-controls="panel-description"
            data-testid="tab-description"
            onClick={() => switchMode("description")}
            className={`rounded-md px-3 py-1.5 font-medium ${
              mode === "description" ? "bg-brand text-white" : "text-gray-600 hover:bg-gray-50"
            }`}
          >
            画面描述匹配
          </button>
        </div>

        {/* 两种模式共用抽屉/预览；用 hidden 切换以保留各自状态 */}
        <div
          role="tabpanel"
          id="panel-search"
          aria-labelledby="tab-search"
          className={mode === "search" ? "" : "hidden"}
          data-testid="view-search"
        >
          <SemanticSearchView
            initialForm={initialForm}
            initialPage={initial.page}
            onCoreChange={onCoreChange}
            onOpenItem={(item) => setDrawerItem(item)}
            onPreview={(id) => setPreviewShotId(id)}
            selectedShotId={drawerItem?.shot_id ?? null}
          />
        </div>
        <div
          role="tabpanel"
          id="panel-description"
          aria-labelledby="tab-description"
          className={mode === "description" ? "" : "hidden"}
          data-testid="view-description"
        >
          <DescriptionMatchView
            onOpenItem={(item) => setDrawerItem(item)}
            onPreview={(id) => setPreviewShotId(id)}
          />
        </div>
      </main>

      <SearchResultDrawer item={drawerItem} onClose={() => setDrawerItem(null)} />
      <PreviewModal shotId={previewShotId} onClose={() => setPreviewShotId(null)} />
    </div>
  );
}
