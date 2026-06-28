// 可复用收藏按钮：加到镜头卡 / 搜索结果卡 / 候选卡 / 详情抽屉，不复制卡片。
// 后端「重复幂等」：再次提交返回已存在记录，因此点击即收藏（无需先查是否已收藏）。
// 成功后展示「已收藏」反馈；失败展示可读错误（不泄漏内部细节）。
"use client";

import { useState } from "react";

import { ApiError } from "@/lib/api";
import { useCreateFavorite } from "@/lib/hooks";
import type { FavoriteCreateRequest, FavoriteTargetType } from "@/lib/types";

export function FavoriteButton({
  targetType,
  shotId,
  assetId,
  context,
  size = "sm",
  className,
}: {
  targetType: FavoriteTargetType;
  shotId?: number;
  assetId?: number;
  context?: Record<string, unknown>;
  size?: "sm" | "icon";
  className?: string;
}) {
  const create = useCreateFavorite();
  const [done, setDone] = useState(false);

  const onClick = (e: React.MouseEvent) => {
    // 卡片本体常带点击事件（打开详情）；收藏按钮阻止冒泡，避免误触发选中。
    e.stopPropagation();
    if (create.isPending || done) return;
    const req: FavoriteCreateRequest = { target_type: targetType };
    if (assetId != null) req.asset_id = assetId;
    if (shotId != null) req.shot_id = shotId;
    if (context) req.context = context;
    create.mutate(req, { onSuccess: () => setDone(true) });
  };

  const failed = create.error != null && !done;
  const label = done ? "已收藏" : create.isPending ? "收藏中…" : "收藏";
  const errMsg =
    create.error instanceof ApiError
      ? create.error.message
      : create.error instanceof Error
        ? create.error.message
        : "收藏失败";

  if (size === "icon") {
    return (
      <button
        type="button"
        data-testid="favorite-btn"
        onClick={onClick}
        disabled={create.isPending || done}
        aria-label={done ? "已收藏" : "收藏"}
        aria-pressed={done}
        title={failed ? errMsg : done ? "已收藏" : "收藏"}
        className={`flex h-6 w-6 items-center justify-center rounded-full text-[12px] ${
          done ? "bg-amber-400 text-white" : "bg-black/55 text-white hover:bg-black/75"
        } disabled:opacity-70 ${className ?? ""}`}
      >
        {done ? "★" : "☆"}
      </button>
    );
  }

  return (
    <button
      type="button"
      data-testid="favorite-btn"
      onClick={onClick}
      disabled={create.isPending || done}
      aria-pressed={done}
      title={failed ? errMsg : undefined}
      className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[11px] font-medium transition disabled:opacity-70 ${
        done
          ? "border-amber-300 bg-amber-50 text-amber-700"
          : "border-gray-300 text-gray-600 hover:bg-gray-50"
      } ${className ?? ""}`}
    >
      <span aria-hidden>{done ? "★" : "☆"}</span>
      {label}
    </button>
  );
}
