"use client";

import { useEffect, useId, useRef } from "react";

import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/Button";

// 共享浮层底座：Esc 关闭、点击遮罩关闭、焦点陷阱(Tab 循环)、关闭后焦点还原、body 滚动锁、aria-modal。
// Dialog(居中) / Drawer(右侧抽屉) 复用同一套语义，避免四处复制浮层逻辑。

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

function trapTab(e: KeyboardEvent, panel: HTMLElement | null) {
  if (!panel) return;
  const nodes = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement,
  );
  if (nodes.length === 0) {
    e.preventDefault();
    panel.focus();
    return;
  }
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  const active = document.activeElement as HTMLElement | null;
  if (e.shiftKey) {
    if (active === first || !panel.contains(active)) {
      e.preventDefault();
      last.focus();
    }
  } else if (active === last || !panel.contains(active)) {
    e.preventDefault();
    first.focus();
  }
}

function Overlay({
  open,
  onClose,
  children,
  labelledBy,
  panelClassName,
  position = "center",
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  labelledBy?: string;
  panelClassName?: string;
  position?: "center" | "right";
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  // onClose 以 ref 持有：避免其每次渲染的新身份让焦点/滚动锁 effect 重跑、反复抢焦点。
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    restoreRef.current = (document.activeElement as HTMLElement) ?? null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current();
      } else if (e.key === "Tab") {
        trapTab(e, panelRef.current);
      }
    };
    document.addEventListener("keydown", onKey, true);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const t = window.setTimeout(() => {
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = panel.querySelector<HTMLElement>(FOCUSABLE);
      (focusable ?? panel).focus();
    }, 0);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = prevOverflow;
      window.clearTimeout(t);
      restoreRef.current?.focus?.();
    };
    // 仅在 open 切换时运行；onClose 变化通过 ref 透传，不重跑本 effect。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  return (
    <div
      className={cn(
        "fixed inset-0 z-50 flex bg-black/40",
        position === "center" ? "items-center justify-center p-4" : "items-stretch justify-end",
      )}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
        className={cn("bg-white shadow-xl focus:outline-none", panelClassName)}
      >
        {children}
      </div>
    </div>
  );
}

export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  widthClass = "max-w-lg",
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  widthClass?: string;
}) {
  const titleId = useId();
  return (
    <Overlay
      open={open}
      onClose={onClose}
      labelledBy={titleId}
      position="center"
      panelClassName={cn("flex max-h-[90vh] w-full flex-col rounded-lg", widthClass)}
    >
      <div className="flex items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
        <h2 id={titleId} className="text-base font-semibold text-gray-900">
          {title}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭"
          className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        >
          <span aria-hidden>✕</span>
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
      {footer ? (
        <div className="flex items-center justify-end gap-2 border-t border-gray-100 px-4 py-3">
          {footer}
        </div>
      ) : null}
    </Overlay>
  );
}

export function Drawer({
  open,
  onClose,
  title,
  children,
  footer,
  widthClass = "max-w-md",
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  widthClass?: string;
}) {
  const titleId = useId();
  return (
    <Overlay
      open={open}
      onClose={onClose}
      labelledBy={titleId}
      position="right"
      panelClassName={cn("flex h-full w-full flex-col", widthClass)}
    >
      <div className="flex items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
        <h2 id={titleId} className="text-base font-semibold text-gray-900">
          {title}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭"
          className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        >
          <span aria-hidden>✕</span>
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
      {footer ? (
        <div className="flex items-center justify-end gap-2 border-t border-gray-100 px-4 py-3">
          {footer}
        </div>
      ) : null}
    </Overlay>
  );
}

// 危险操作确认（删除等）。confirmVariant 默认 danger。
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "确认",
  cancelLabel = "取消",
  loading = false,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  message: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  loading?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      widthClass="max-w-sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button variant="danger" onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-sm text-gray-600">{message}</div>
    </Dialog>
  );
}
