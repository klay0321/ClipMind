"use client";

import { useEffect, useRef } from "react";

import { ApiError } from "@/lib/api";
import type { BatchMembershipResult, ProjectStatus } from "@/lib/types";

export function ProjectStatusBadge({ status }: { status: ProjectStatus }) {
  const map: Record<ProjectStatus, { label: string; cls: string }> = {
    active: { label: "进行中", cls: "bg-green-50 text-green-700 border-green-200" },
    archived: { label: "已归档", cls: "bg-gray-100 text-gray-600 border-gray-300" },
  };
  const { label, cls } = map[status];
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium ${cls}`}
      data-testid={`project-status-${status}`}
    >
      {label}
    </span>
  );
}

// 归档只读横幅（不只靠颜色：含文字说明 + 锁图标 + 恢复按钮）
export function ArchivedBanner({
  onUnarchive,
  pending,
}: {
  onUnarchive?: () => void;
  pending?: boolean;
}) {
  return (
    <div
      role="status"
      data-testid="archived-banner"
      className="flex items-center gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800"
    >
      <span aria-hidden>🔒</span>
      <span>项目已归档，当前为只读状态。恢复项目后可继续编辑。</span>
      {onUnarchive ? (
        <button
          type="button"
          onClick={onUnarchive}
          disabled={pending}
          className="ml-auto rounded border border-amber-300 bg-white px-3 py-1 text-xs font-medium text-amber-800 disabled:opacity-50 hover:bg-amber-100"
        >
          {pending ? "恢复中…" : "恢复项目"}
        </button>
      ) : null}
    </div>
  );
}

// 内联错误提示（409/422 等）：role=alert 供读屏播报；可读文案，不泄漏内部细节
export function InlineError({ error }: { error: unknown }) {
  if (!error) return null;
  const msg =
    error instanceof ApiError
      ? error.status === 409
        ? error.message || "操作冲突：内容已被更新或项目已归档，请刷新后重试"
        : error.message
      : error instanceof Error
        ? error.message
        : "操作失败";
  return (
    <div
      role="alert"
      data-testid="inline-error"
      className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
    >
      {msg}
    </div>
  );
}

// 批量成员结果：真实展示 completed/skipped/failed（skipped≠失败）；role=status 供播报
export function BatchResultNotice({
  result,
  nounMap,
}: {
  result: BatchMembershipResult | null;
  nounMap?: { completed?: string; skipped?: string; failed?: string };
}) {
  if (!result) return null;
  const c = result.completed.length;
  const s = result.skipped.length;
  const f = result.failed.length;
  if (c === 0 && s === 0 && f === 0) return null;
  return (
    <div
      role="status"
      data-testid="batch-result"
      className="space-y-1 rounded border border-gray-200 bg-gray-50 px-3 py-2 text-sm"
    >
      {c > 0 ? (
        <div className="text-green-700" data-testid="batch-completed">
          ✅ 成功添加 {c} 项{nounMap?.completed ? `（${nounMap.completed}）` : ""}
        </div>
      ) : null}
      {s > 0 ? (
        <div className="text-amber-700" data-testid="batch-skipped">
          ⏭️ 已存在并跳过 {s} 项
        </div>
      ) : null}
      {f > 0 ? (
        <div className="text-red-700" data-testid="batch-failed">
          ⚠️ 不存在或不可用 {f} 项（编号：{result.failed.map((x) => x.id).join("、")}）
        </div>
      ) : null}
    </div>
  );
}

// 确认对话框（删除集合等危险操作）：Esc 关闭、focus 管理、焦点恢复
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "确认",
  pending,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      restoreRef.current?.focus?.();
    };
  }, [open, onCancel]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onCancel}
    >
      <div
        className="w-full max-w-sm rounded-lg bg-white p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-gray-800">{title}</h2>
        <p className="mt-2 text-sm text-gray-600">{message}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
          >
            取消
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={pending}
            data-testid="confirm-ok"
            className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-red-700"
          >
            {pending ? "处理中…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
