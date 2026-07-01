"use client";

import { useMemo, useState } from "react";

import { ProductsView } from "@/components/ProductsView";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { TopNav } from "@/components/TopNav";
import { Button } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useCatalogResolve, useCatalogSearch, useCatalogTree } from "@/lib/hooks";
import { CATALOG_STATUSES, type CatalogStatus, type CatalogTreeNode } from "@/lib/types";

import { CatalogTree, type SelectedNode } from "./CatalogTree";
import { CreateWizard } from "./CreateWizard";
import { EntityDetail } from "./EntityDetail";
import { CatalogFutureNotice, levelLabel, statusLabel } from "./widgets";

type Tab = "catalog" | "flat";

// 递归统计各状态节点数（真实计数，来自树；不硬编码数量）
function countStatuses(nodes: CatalogTreeNode[]): Record<CatalogStatus, number> {
  const acc: Record<CatalogStatus, number> = {
    draft: 0,
    active: 0,
    paused: 0,
    archived: 0,
    merged: 0,
  };
  const walk = (list: CatalogTreeNode[]) => {
    for (const n of list) {
      if (n.id != null) acc[n.status] = (acc[n.status] ?? 0) + 1;
      if (n.children.length) walk(n.children);
    }
  };
  walk(nodes);
  return acc;
}

// 按状态筛选树（保留命中节点的祖先路径，便于在树中定位）
function filterTree(nodes: CatalogTreeNode[], status: CatalogStatus | "all"): CatalogTreeNode[] {
  if (status === "all") return nodes;
  const out: CatalogTreeNode[] = [];
  for (const n of nodes) {
    const kids = filterTree(n.children, status);
    const selfMatch = n.id != null && n.status === status;
    if (selfMatch || kids.length) {
      out.push({ ...n, children: kids });
    }
  }
  return out;
}

export function CatalogView() {
  const [tab, setTab] = useState<Tab>("catalog");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [statusFilter, setStatusFilter] = useState<CatalogStatus | "all">("all");
  const [searchTerm, setSearchTerm] = useState("");
  const [selected, setSelected] = useState<SelectedNode | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const treeQ = useCatalogTree(includeArchived);
  const searchQ = useCatalogSearch(searchTerm, searchTerm.trim().length > 0);
  const resolveQ = useCatalogResolve(searchTerm, searchTerm.trim().length > 0);

  const tree = useMemo(() => treeQ.data ?? [], [treeQ.data]);
  const counts = useMemo(() => countStatuses(tree), [tree]);
  const visibleTree = useMemo(() => filterTree(tree, statusFilter), [tree, statusFilter]);

  const searchResults = searchQ.data ?? [];
  // §四：精确输入命中多个不同实体时提示人工选择，绝不自动绑定第一条
  const isAmbiguous = resolveQ.data?.status === "ambiguous";

  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="products" />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-gray-800">产品目录</h1>
            <p className="mt-0.5 text-sm text-gray-500">
              维护分类 / 产品 / 型号 / SKU 的层级结构与别名，用于镜头产品归属、检索与匹配。新增产品无需改动系统。
            </p>
          </div>
          {tab === "catalog" ? (
            <Button variant="primary" onClick={() => setShowCreate(true)} data-testid="open-create-wizard">
              + 新建产品
            </Button>
          ) : null}
        </div>

        {/* Tab：产品目录（层级）与 扁平产品（既有）共存，不删除任一入口 */}
        <div className="mb-4 flex gap-2 border-b border-gray-200 text-sm" role="tablist">
          {([
            { key: "catalog", label: "产品目录" },
            { key: "flat", label: "产品列表" },
          ] as { key: Tab; label: string }[]).map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              data-testid={`tab-${t.key}`}
              className={cn(
                "-mb-px border-b-2 px-3 py-1.5 font-medium",
                tab === t.key
                  ? "border-brand text-brand"
                  : "border-transparent text-gray-500 hover:text-gray-800",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "flat" ? (
          <div data-testid="flat-products">
            {/* 既有扁平产品视图（保留其 API 与功能），以 embedded 模式嵌入，复用其检索与计数。 */}
            <ProductsView embedded />
          </div>
        ) : (
          <div className="space-y-3">
            {/* 工具条：搜索 + 状态筛选 + 计数 + 含归档 */}
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <input
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  placeholder="搜索名称 / 编码 / 别名"
                  aria-label="搜索产品目录"
                  data-testid="catalog-search-input"
                  className="w-64 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-brand focus:outline-none"
                />
                {searchTerm.trim() && searchResults.length > 0 ? (
                  <ul
                    data-testid="catalog-search-results"
                    className="absolute z-10 mt-1 max-h-72 w-72 overflow-auto rounded-md border border-gray-200 bg-white py-1 shadow-lg"
                  >
                    {isAmbiguous ? (
                      <li
                        data-testid="catalog-ambiguous-hint"
                        className="border-b border-amber-100 bg-amber-50 px-3 py-1.5 text-[11px] text-amber-800"
                      >
                        找到多个可能产品，请选择
                      </li>
                    ) : null}
                    {searchResults.map((r) => (
                      <li key={`${r.level}-${r.id}`}>
                        <button
                          type="button"
                          onClick={() => {
                            if (r.id != null) {
                              setSelected({ level: r.level, id: r.id });
                              setSearchTerm("");
                            }
                          }}
                          data-testid={`search-result-${r.level}-${r.id}`}
                          className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-sm hover:bg-gray-50"
                        >
                          <span className="shrink-0 rounded bg-gray-100 px-1 text-[10px] text-gray-500">
                            {levelLabel(r.level)}
                          </span>
                          <span className="truncate text-gray-700">{r.name_zh}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>

              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as CatalogStatus | "all")}
                aria-label="状态筛选"
                data-testid="catalog-status-filter"
                className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none"
              >
                <option value="all">全部状态</option>
                {CATALOG_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {statusLabel(s)}
                  </option>
                ))}
              </select>

              <label className="flex items-center gap-1.5 text-xs text-gray-600">
                <input
                  type="checkbox"
                  checked={includeArchived}
                  onChange={(e) => setIncludeArchived(e.target.checked)}
                  data-testid="include-archived"
                />
                含归档
              </label>

              <div className="ml-auto flex flex-wrap items-center gap-1.5" data-testid="status-counts">
                {CATALOG_STATUSES.filter((s) => counts[s] > 0).map((s) => (
                  <span
                    key={s}
                    data-testid={`count-${s}`}
                    className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600"
                  >
                    {statusLabel(s)} {counts[s]}
                  </span>
                ))}
              </div>
            </div>

            <CatalogFutureNotice />

            {/* 主体：左树 + 右详情，响应式（窄屏堆叠） */}
            {treeQ.isLoading ? (
              <Loading rows={6} />
            ) : treeQ.isError ? (
              <ErrorState
                message={(treeQ.error as Error)?.message ?? "加载产品目录失败"}
                onRetry={() => void treeQ.refetch()}
              />
            ) : tree.length === 0 ? (
              <Empty
                title="产品目录为空"
                description="点击右上角「新建产品」录入第一个产品；层级与别名全部动态维护，无需改代码。"
                action={
                  <Button variant="primary" onClick={() => setShowCreate(true)} data-testid="empty-create">
                    + 新建产品
                  </Button>
                }
              />
            ) : (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,20rem)_1fr]">
                <div
                  className="max-h-[70vh] overflow-auto rounded-lg border border-gray-200 bg-white p-2"
                  data-testid="tree-panel"
                >
                  {visibleTree.length === 0 ? (
                    <p className="px-2 py-6 text-center text-xs text-gray-400" data-testid="tree-filter-empty">
                      当前筛选无匹配节点
                    </p>
                  ) : (
                    <CatalogTree nodes={visibleTree} selected={selected} onSelect={setSelected} />
                  )}
                </div>
                <div className="min-w-0 rounded-lg border border-gray-200 bg-white" data-testid="detail-panel">
                  {selected ? (
                    <EntityDetail selected={selected} onSelect={setSelected} />
                  ) : (
                    <div
                      className="flex h-full min-h-[16rem] items-center justify-center px-6 text-center text-sm text-gray-400"
                      data-testid="detail-placeholder"
                    >
                      从左侧选择一个分类 / 产品 / 型号 / SKU 查看与管理详情。
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        <CreateWizard
          open={showCreate}
          onClose={() => setShowCreate(false)}
          onCreated={(familyId) => setSelected({ level: "family", id: familyId })}
        />
      </main>
    </div>
  );
}
