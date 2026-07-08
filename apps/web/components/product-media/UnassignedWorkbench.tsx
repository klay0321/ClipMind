"use client";

import Link from "next/link";
import { useState } from "react";

import { GroupedReview } from "@/components/product-media/GroupedReview";
import { ProductPicker } from "@/components/product-media/ProductPicker";
import { UnassignedCard } from "@/components/product-media/ProductMediaView";
import { Pagination } from "@/components/Pagination";
import {
  useDismissVisualCandidate,
  usePmMutations,
  usePmUnassigned,
  useUnassignedCounts,
} from "@/lib/hooks";
import type { FamilyMediaSummary, ProductMediaItem } from "@/lib/types";
import { cn } from "@/lib/cn";

const PAGE_SIZE = 24;
const KINDS = [
  { key: "image", label: "图片" },
  { key: "video", label: "视频" },
  { key: "shot", label: "镜头" },
] as const;

// PM-UX：待归类工作台——翻页浏览全部未标注、多选、搜索式选产品、
// 底部固定绑定栏；「按建议分组」为同一任务的另一种视图。
export function UnassignedWorkbench({ families }: { families: FamilyMediaSummary[] }) {
  const [kind, setKind] = useState<string>("image");
  const [view, setView] = useState<"list" | "grouped">("list");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bindFamily, setBindFamily] = useState<number | null>(null);
  const [bindRole, setBindRole] = useState("related");
  const [doneMsg, setDoneMsg] = useState<string | null>(null);

  const counts = useUnassignedCounts();
  const unassigned = usePmUnassigned(kind, page);
  const { create, bulk } = usePmMutations();
  const dismissVisual = useDismissVisualCandidate();

  const keyOf = (it: ProductMediaItem) =>
    `${it.type === "shot" ? "shot" : "asset"}:${it.type === "shot" ? it.shot_id : it.asset_id}`;

  const switchKind = (k: string) => {
    setKind(k);
    setPage(1);
    setSelected(new Set());
    setDoneMsg(null);
  };
  const changePage = (p: number) => {
    setPage(p);
    setSelected(new Set()); // 页内选择语义：换页即清空，避免"看不见的已选"
  };
  const toggle = (it: ProductMediaItem) => {
    const k = keyOf(it);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  const runBind = async () => {
    if (!bindFamily || selected.size === 0) return;
    const items = [...selected].map((k) => {
      const [t, id] = k.split(":");
      return { target_type: t, target_id: Number(id) };
    });
    const res = await bulk.mutateAsync({
      items,
      family_id: bindFamily,
      role: bindRole,
      origin: "bulk_manual",
    });
    setDoneMsg(
      `绑定完成：成功 ${res.completed.length}，跳过 ${res.skipped.length}，失败 ${res.failed.length}`,
    );
    setSelected(new Set());
  };

  const total = unassigned.data?.total ?? 0;
  const items = unassigned.data?.items ?? [];
  const badge = (k: string) =>
    counts.data ? (counts.data as Record<string, number>)[k] : undefined;

  return (
    <section className="space-y-3" data-testid="pm-unassigned">
      {/* 类型 + 视图 + 操作历史 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1">
          {KINDS.map((k) => (
            <button
              key={k.key}
              type="button"
              data-testid={`unassigned-tab-${k.key}`}
              onClick={() => switchKind(k.key)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs",
                kind === k.key
                  ? "border-brand bg-brand/10 font-medium text-brand"
                  : "border-gray-300 text-gray-600 hover:bg-gray-50",
              )}
            >
              {k.label}
              {badge(k.key) != null ? (
                <span className="ml-1 rounded-full bg-gray-200/80 px-1.5 text-[10px] text-gray-700">
                  {badge(k.key)}
                </span>
              ) : null}
            </button>
          ))}
        </div>
        <div className="flex gap-1 rounded-md border border-gray-200 p-0.5 text-xs">
          {(
            [
              { key: "list", label: "逐项处理" },
              { key: "grouped", label: "按建议分组" },
            ] as const
          ).map((v) => (
            <button
              key={v.key}
              type="button"
              data-testid={`unassigned-view-${v.key}`}
              onClick={() => setView(v.key)}
              className={cn(
                "rounded px-2 py-1",
                view === v.key ? "bg-gray-800 text-white" : "text-gray-600",
              )}
            >
              {v.label}
            </button>
          ))}
        </div>
        <span className="text-xs text-gray-400" data-testid="unassigned-total">
          共 {total} 项待标注
        </span>
      </div>

      {view === "grouped" ? (
        <GroupedReview families={families} />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            {items.length > 0 ? (
              <button
                type="button"
                className="text-brand hover:underline"
                data-testid="select-all-page"
                onClick={() => setSelected(new Set(items.map((it) => keyOf(it))))}
              >
                全选本页（{items.length}）
              </button>
            ) : null}
            {selected.size > 0 ? (
              <button
                type="button"
                className="text-gray-500 hover:underline"
                data-testid="clear-selection"
                onClick={() => setSelected(new Set())}
              >
                清空已选
              </button>
            ) : null}
            <span className="text-gray-400">
              点缩略图选中/取消；点「候选建议」查看系统提名并可单个确认
            </span>
          </div>

          <div className="grid gap-2 md:grid-cols-3 lg:grid-cols-4">
            {items.map((it) => (
              <UnassignedCard
                key={keyOf(it)}
                it={it}
                selected={selected.has(keyOf(it))}
                onToggle={() => toggle(it)}
                onPickSuggestion={(fid, origin) => {
                  const targetType = it.type === "shot" ? "shot" : "asset";
                  const targetId = it.type === "shot" ? it.shot_id : it.asset_id;
                  create.mutate({
                    target_type: targetType,
                    target_id: targetId,
                    family_id: fid,
                    role: "related",
                    origin,
                  });
                }}
                onDismissVisual={(cid) => dismissVisual.mutate(cid)}
              />
            ))}
          </div>
          {unassigned.data && items.length === 0 ? (
            <p className="text-xs text-gray-400">该类型没有未标注素材 🎉</p>
          ) : null}

          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={total}
            onPageChange={changePage}
          />

          {/* 固定绑定栏：有选中即吸底，操作永远可见 */}
          <div
            className={cn(
              "sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center gap-2 rounded-t-lg border border-gray-200 bg-white/95 p-2.5 text-xs shadow-[0_-4px_12px_rgba(0,0,0,0.06)] backdrop-blur",
              selected.size === 0 && "opacity-80",
            )}
            data-testid="bulk-bar"
          >
            <span
              className={cn(
                "font-medium",
                selected.size > 0 ? "text-brand" : "text-gray-400",
              )}
              data-testid="selected-count"
            >
              已选 {selected.size} 项
            </span>
            <ProductPicker
              families={families}
              value={bindFamily}
              onChange={setBindFamily}
              testId="bulk-family"
            />
            <select
              value={bindRole}
              onChange={(e) => setBindRole(e.target.value)}
              data-testid="bulk-role"
              aria-label="关系角色"
              className="rounded border border-gray-300 px-2 py-1.5"
            >
              <option value="related">关联产品</option>
              <option value="primary">主产品</option>
            </select>
            <button
              type="button"
              disabled={selected.size === 0 || !bindFamily || bulk.isPending}
              onClick={runBind}
              data-testid="bulk-assign"
              className="rounded bg-brand px-4 py-1.5 font-medium text-white disabled:opacity-40"
            >
              {bulk.isPending ? "绑定中…" : `绑定已选 ${selected.size} 项`}
            </button>
            {kind !== "image" ? (
              <span className="text-gray-400">
                视频绑定后其全部镜头自动继承，无需逐个处理
              </span>
            ) : null}
            {doneMsg ? (
              <span className="text-emerald-700" data-testid="bulk-result">
                {doneMsg}（可在
                <button
                  type="button"
                  className="mx-0.5 underline"
                  onClick={() =>
                    document
                      .querySelector('[data-testid="toggle-operations"]')
                      ?.scrollIntoView({ behavior: "smooth" })
                  }
                >
                  操作历史
                </button>
                撤销）
              </span>
            ) : null}
            <Link
              href="/search"
              className="ml-auto text-gray-400 hover:text-brand"
              title="不确定是什么产品时，用以图搜图找相似素材参考"
            >
              不确定？试试以图搜图 →
            </Link>
          </div>
        </>
      )}
    </section>
  );
}
