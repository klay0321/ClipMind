"use client";

import Link from "next/link";
import { useState } from "react";

import { TopNav } from "@/components/TopNav";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { useProducts, useProductStats } from "@/lib/hooks";

// 产品库：真实读取 /products + /products/stats（绑定计数）；可查看产品对应镜头。
export function ProductsView() {
  const [q, setQ] = useState("");
  const productsQ = useProducts(q || undefined);
  const statsQ = useProductStats();
  const stats = statsQ.data ?? {};
  const items = productsQ.data ?? [];

  let body: React.ReactNode;
  if (productsQ.isLoading) {
    body = <Loading />;
  } else if (productsQ.isError) {
    body = (
      <ErrorState
        message={(productsQ.error as Error)?.message ?? "加载产品库失败"}
        onRetry={() => void productsQ.refetch()}
      />
    );
  } else if (items.length === 0) {
    body = (
      <Empty
        title={q ? "没有匹配的产品" : "产品库为空"}
        description={
          q ? "换个关键词试试" : "通过后端 API 录入产品后在此展示，并用于镜头产品归属与匹配"
        }
      />
    );
  } else {
    body = (
      <div className="overflow-x-auto rounded-lg border border-gray-100 bg-white shadow-sm">
        <table className="w-full text-sm" data-testid="product-table">
          <thead className="border-b border-gray-100 bg-gray-50 text-left text-xs text-gray-500">
            <tr>
              <th className="px-3 py-2 font-medium">名称</th>
              <th className="px-3 py-2 font-medium">SKU</th>
              <th className="px-3 py-2 font-medium">卖点</th>
              <th className="px-3 py-2 font-medium">绑定素材</th>
              <th className="px-3 py-2 font-medium">镜头数</th>
              <th className="px-3 py-2 font-medium">已确认</th>
              <th className="px-3 py-2 font-medium">状态</th>
              <th className="px-3 py-2 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => {
              const st = stats[p.id];
              return (
                <tr key={p.id} className="border-b border-gray-50 last:border-0" data-testid="product-row">
                  <td className="px-3 py-2">
                    <div className="font-medium text-gray-800">{p.name}</div>
                    <div className="text-[11px] text-gray-400">
                      {[p.brand, p.model].filter(Boolean).join(" · ") || "—"}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-gray-500">{p.sku ?? "—"}</td>
                  <td className="px-3 py-2 text-gray-500">
                    <div className="flex flex-wrap gap-1">
                      {(p.selling_points ?? []).slice(0, 4).map((s) => (
                        <span key={s} className="rounded bg-indigo-50 px-1.5 py-0.5 text-[11px] text-indigo-700">
                          {s}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-2 tabular-nums text-gray-700">{st?.asset_count ?? 0}</td>
                  <td className="px-3 py-2 tabular-nums text-gray-700">{st?.shot_count ?? 0}</td>
                  <td className="px-3 py-2 tabular-nums text-emerald-700">{st?.confirmed_shot_count ?? 0}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[11px] ${
                        p.status === "active"
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-gray-100 text-gray-500"
                      }`}
                    >
                      {p.status === "active" ? "启用" : "已归档"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Link
                      href={`/shots?product_id=${p.id}`}
                      className="inline-flex items-center whitespace-nowrap rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    >
                      查看镜头
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div>
      <TopNav active="products" />
      <main className="mx-auto max-w-7xl space-y-4 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <h1 className="text-base font-semibold">产品库</h1>
            {productsQ.data ? (
              <span className="text-xs text-gray-400">共 {items.length} 个产品</span>
            ) : null}
          </div>
          <input
            data-testid="product-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索品牌 / 名称 / 型号 / SKU"
            className="w-64 rounded-md border border-gray-200 px-3 py-1.5 text-sm"
          />
        </div>
        {body}
      </main>
    </div>
  );
}
