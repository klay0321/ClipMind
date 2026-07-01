"use client";

import { useState } from "react";

import { cn } from "@/lib/cn";
import type { CatalogLevel, CatalogStatus, CatalogTreeNode } from "@/lib/types";

import { levelLabel, statusLabel } from "./widgets";

export interface SelectedNode {
  level: CatalogLevel;
  id: number;
}

// 层级左边距，形成缩进感（分类→产品→型号→SKU）
const INDENT: Record<CatalogLevel, string> = {
  category: "pl-2",
  family: "pl-5",
  variant: "pl-8",
  sku: "pl-11",
};

// 非 active 状态在树上以浅色 + 状态词提示（不只靠颜色）
function nodeMuted(status: CatalogStatus): boolean {
  return status !== "active";
}

function TreeRow({
  node,
  selected,
  onSelect,
}: {
  node: CatalogTreeNode;
  selected: SelectedNode | null;
  onSelect: (n: SelectedNode) => void;
}) {
  const [open, setOpen] = useState(true);
  const hasChildren = node.children.length > 0;
  // 未分类占位分组（id 为 null）：仅作分组标题，不可选中
  const selectable = node.id != null;
  const isSelected =
    selectable && selected?.level === node.level && selected?.id === node.id;

  return (
    <div>
      <div
        className={cn(
          "group flex items-center gap-1 rounded py-1 pr-2 text-sm",
          INDENT[node.level],
          isSelected ? "bg-brand/10 text-brand-dark" : "hover:bg-gray-50",
        )}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-label={open ? "折叠" : "展开"}
            aria-expanded={open}
            className="flex h-4 w-4 shrink-0 items-center justify-center text-xs text-gray-400 hover:text-gray-600"
          >
            <span aria-hidden>{open ? "▾" : "▸"}</span>
          </button>
        ) : (
          <span className="h-4 w-4 shrink-0" aria-hidden />
        )}
        {selectable ? (
          <button
            type="button"
            onClick={() => onSelect({ level: node.level, id: node.id as number })}
            data-testid={`tree-node-${node.level}-${node.id}`}
            aria-current={isSelected ? "true" : undefined}
            className={cn(
              "flex min-w-0 flex-1 items-center gap-1.5 text-left",
              nodeMuted(node.status) && !isSelected ? "text-gray-400" : "text-gray-700",
            )}
          >
            <span className="shrink-0 rounded bg-gray-100 px-1 text-[10px] text-gray-500">
              {levelLabel(node.level)}
            </span>
            <span className="truncate">{node.name_zh}</span>
            {nodeMuted(node.status) ? (
              <span className="shrink-0 text-[10px] text-gray-400">（{statusLabel(node.status)}）</span>
            ) : null}
          </button>
        ) : (
          <span
            className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-xs font-medium text-gray-400"
            data-testid={`tree-group-${node.code}`}
          >
            {node.name_zh}
          </span>
        )}
      </div>
      {hasChildren && open ? (
        <div>
          {node.children.map((c) => (
            <TreeRow
              key={`${c.level}-${c.id ?? c.code}`}
              node={c}
              selected={selected}
              onSelect={onSelect}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function CatalogTree({
  nodes,
  selected,
  onSelect,
}: {
  nodes: CatalogTreeNode[];
  selected: SelectedNode | null;
  onSelect: (n: SelectedNode) => void;
}) {
  return (
    <div data-testid="catalog-tree" role="tree" aria-label="产品目录层级">
      {nodes.map((n) => (
        <TreeRow
          key={`${n.level}-${n.id ?? n.code}`}
          node={n}
          selected={selected}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
