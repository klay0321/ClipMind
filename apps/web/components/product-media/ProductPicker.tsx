"use client";

import { useMemo, useRef, useState } from "react";

import type { FamilyMediaSummary } from "@/lib/types";
import { cn } from "@/lib/cn";

// PM-UX：搜索式产品选择器（替代上百项的原生 select）。
// 输入过滤名称/编码，点击选择；已选显示为可清除的 chip。
export function ProductPicker({
  families,
  value,
  onChange,
  placeholder = "搜索产品名称/编码…",
  testId = "product-picker",
}: {
  families: FamilyMediaSummary[];
  value: number | null;
  onChange: (familyId: number | null) => void;
  placeholder?: string;
  testId?: string;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const picked = families.find((f) => f.family_id === value) ?? null;
  const matches = useMemo(() => {
    const t = q.trim().toLowerCase();
    const list = t
      ? families.filter(
          (f) =>
            f.name_zh.toLowerCase().includes(t) || f.code.toLowerCase().includes(t),
        )
      : families;
    return list.slice(0, 20);
  }, [families, q]);

  if (picked) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full border border-brand bg-brand/10 px-2.5 py-1 text-xs font-medium text-brand"
        data-testid={`${testId}-picked`}
      >
        {picked.name_zh}
        <button
          type="button"
          aria-label="清除已选产品"
          onClick={() => {
            onChange(null);
            setQ("");
          }}
          className="text-brand/70 hover:text-brand"
          data-testid={`${testId}-clear`}
        >
          ✕
        </button>
      </span>
    );
  }

  return (
    <div ref={rootRef} className="relative">
      <input
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={placeholder}
        aria-label="选择产品"
        data-testid={testId}
        className="w-56 rounded border border-gray-300 px-2 py-1.5 text-xs focus:border-brand focus:outline-none"
      />
      {open ? (
        <div
          className="absolute z-20 mt-1 max-h-56 w-72 overflow-y-auto rounded-md border border-gray-200 bg-white py-1 shadow-lg"
          data-testid={`${testId}-list`}
        >
          {matches.map((f) => (
            <button
              key={f.family_id}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onChange(f.family_id);
                setOpen(false);
              }}
              className="block w-full px-2.5 py-1.5 text-left text-xs hover:bg-gray-50"
              data-testid={`${testId}-option-${f.family_id}`}
            >
              <span className={cn("font-medium text-gray-800")}>{f.name_zh}</span>
              <span className="ml-1 text-gray-400">{f.code}</span>
            </button>
          ))}
          {matches.length === 0 ? (
            <p className="px-2.5 py-1.5 text-xs text-gray-400">没有匹配的产品</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
