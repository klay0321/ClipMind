"use client";

import { useEffect, useId, useRef, useState } from "react";

import { cn } from "@/lib/cn";

// 下拉/溢出菜单：用于行内 ⋮ 次要操作、导航「更多」、导出格式选择。
// 处理点击外部关闭、Esc 关闭、aria-haspopup/expanded。避免一个区域堆多个同权重按钮。
export interface MenuItem {
  key: string;
  label: React.ReactNode;
  onSelect?: () => void;
  href?: string;
  danger?: boolean;
  disabled?: boolean;
  testId?: string;
}

export function Menu({
  items,
  trigger,
  triggerClassName,
  triggerAriaLabel = "更多操作",
  triggerTestId,
  align = "right",
}: {
  items: MenuItem[];
  trigger?: React.ReactNode;
  triggerClassName?: string;
  triggerAriaLabel?: string;
  triggerTestId?: string;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative inline-block">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={triggerAriaLabel}
        data-testid={triggerTestId}
        onClick={() => setOpen((v) => !v)}
        className={
          triggerClassName ??
          "inline-flex h-7 w-7 items-center justify-center rounded-md border border-gray-300 bg-white text-gray-500 hover:bg-gray-50"
        }
      >
        {trigger ?? <span aria-hidden>⋮</span>}
      </button>
      {open ? (
        <div
          id={menuId}
          role="menu"
          className={cn(
            "absolute z-30 mt-1 min-w-[10rem] overflow-hidden rounded-md border border-gray-200 bg-white py-1 shadow-lg",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {items.map((it) => {
            const cls = cn(
              "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm disabled:cursor-not-allowed disabled:opacity-40",
              it.danger ? "text-red-600 hover:bg-red-50" : "text-gray-700 hover:bg-gray-50",
            );
            if (it.href && !it.disabled) {
              return (
                <a
                  key={it.key}
                  role="menuitem"
                  href={it.href}
                  data-testid={it.testId}
                  className={cls}
                  onClick={() => setOpen(false)}
                >
                  {it.label}
                </a>
              );
            }
            return (
              <button
                key={it.key}
                role="menuitem"
                type="button"
                disabled={it.disabled}
                data-testid={it.testId}
                className={cls}
                onClick={() => {
                  setOpen(false);
                  it.onSelect?.();
                }}
              >
                {it.label}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
