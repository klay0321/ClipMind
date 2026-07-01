"use client";

import { ApiError } from "@/lib/api";
import { Chip, type Tone } from "@/components/ui";
import type { CatalogLevel, CatalogStatus } from "@/lib/types";

// 层级中文标签（受控枚举，非产品值）
export const LEVEL_LABELS: Record<CatalogLevel, string> = {
  category: "分类",
  family: "产品",
  variant: "型号",
  sku: "SKU",
};

// 生命周期状态标签 + 色调（状态不只靠颜色，含文字）
const STATUS_META: Record<CatalogStatus, { label: string; tone: Tone }> = {
  draft: { label: "草稿", tone: "neutral" },
  active: { label: "已启用", tone: "success" },
  paused: { label: "已暂停", tone: "warning" },
  archived: { label: "已归档", tone: "muted" },
  merged: { label: "已合并", tone: "info" },
};

export function statusLabel(status: CatalogStatus): string {
  return STATUS_META[status]?.label ?? status;
}

export function levelLabel(level: CatalogLevel): string {
  return LEVEL_LABELS[level] ?? level;
}

export function CatalogStatusBadge({ status }: { status: CatalogStatus }) {
  const meta = STATUS_META[status] ?? { label: status, tone: "neutral" as Tone };
  return (
    <span data-testid={`catalog-status-${status}`} className="inline-flex">
      <Chip tone={meta.tone} dot>
        {meta.label}
      </Chip>
    </span>
  );
}

export function LevelBadge({ level }: { level: CatalogLevel }) {
  return (
    <span data-testid={`catalog-level-${level}`} className="inline-flex">
      <Chip tone="brand">{levelLabel(level)}</Chip>
    </span>
  );
}

// 内联错误：区分 409 冲突 / 422 校验 / 404 不存在 / 其他，给可读中文，不泄漏内部细节
export function CatalogError({ error }: { error: unknown }) {
  if (!error) return null;
  let msg: string;
  if (error instanceof ApiError) {
    if (error.status === 409) {
      msg = error.message || "冲突：名称/编码已存在或会形成环，请调整后重试";
    } else if (error.status === 422) {
      msg = error.message || "校验失败：请检查必填项与格式";
    } else if (error.status === 404) {
      msg = error.message || "对象不存在或已被移除";
    } else {
      msg = error.message || "操作失败";
    }
  } else if (error instanceof Error) {
    msg = error.message;
  } else {
    msg = "操作失败";
  }
  return (
    <div
      role="alert"
      data-testid="catalog-error"
      className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
    >
      {msg}
    </div>
  );
}

// 自动识别的诚实说明横幅：明确「后续版本提供」，绝不伪造 AI 已识别。
// 参考图与产品属性已在详情页支持维护；此处仅声明「自动产品识别」尚未启用。
export function CatalogFutureNotice() {
  return (
    <div
      role="note"
      data-testid="catalog-future-notice"
      className="rounded border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-700"
    >
      产品属性与参考图可在详情页维护；自动产品识别将在后续版本提供，当前不进行任何 AI 识别、不显示识别结果。
    </div>
  );
}
