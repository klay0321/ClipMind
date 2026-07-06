"use client";

import Link from "next/link";
import { useState } from "react";

import {
  usePmAssetLinks,
  usePmMutations,
  usePmShotLinks,
  usePmSuggestions,
  usePmSummary,
} from "@/lib/hooks";
import type { ProductMediaLink } from "@/lib/types";

const ORIGIN_LABELS: Record<string, string> = {
  manual: "人工",
  bulk_manual: "批量人工",
  path_or_filename_confirmed: "路径/文件名确认",
  visual_suggestion_confirmed: "视觉候选确认",
  text_suggestion_confirmed: "文本候选确认",
  migration_or_legacy: "历史迁移",
};

function LinkRow({
  link,
  onSetPrimary,
  onRemove,
  badge,
}: {
  link: ProductMediaLink;
  onSetPrimary?: () => void;
  onRemove?: () => void;
  badge?: string;
}) {
  return (
    <li
      className="flex flex-wrap items-center gap-2 rounded border border-gray-100 bg-gray-50 px-2 py-1.5 text-xs"
      data-testid={`link-row-${link.id}`}
    >
      <span className="font-medium text-gray-800">{link.family_name}</span>
      <span className="text-gray-400">{link.family_code}</span>
      {link.role === "primary" ? (
        <span className="rounded bg-brand/10 px-1.5 py-0.5 text-[10px] font-medium text-brand">
          主产品
        </span>
      ) : (
        <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] text-gray-600">关联</span>
      )}
      <span className="text-[10px] text-gray-400">
        {ORIGIN_LABELS[link.origin] ?? link.origin}
      </span>
      {badge ? (
        <span className="rounded bg-gray-100 px-1 py-0.5 text-[10px] text-gray-500">{badge}</span>
      ) : null}
      <span className="ml-auto flex gap-2">
        {onSetPrimary && link.role !== "primary" ? (
          <button
            type="button"
            onClick={onSetPrimary}
            className="text-gray-500 hover:text-brand"
            data-testid={`panel-set-primary-${link.id}`}
          >
            设主
          </button>
        ) : null}
        {onRemove ? (
          <button
            type="button"
            onClick={onRemove}
            className="text-red-500 hover:underline"
            data-testid={`panel-unlink-${link.id}`}
          >
            解除
          </button>
        ) : null}
      </span>
    </li>
  );
}

/** Asset / Shot 详情页的产品关系面板（人工事实 + 确定性候选 + 手动添加）。 */
export function ProductLinkPanel({
  targetType,
  targetId,
}: {
  targetType: "asset" | "shot";
  targetId: number;
}) {
  const summary = usePmSummary();
  const assetLinks = usePmAssetLinks(targetType === "asset" ? targetId : null);
  const shotView = usePmShotLinks(targetType === "shot" ? targetId : null);
  const suggestions = usePmSuggestions(targetType, targetId);
  const { create, update, remove } = usePmMutations();
  const [familySel, setFamilySel] = useState("");
  const [roleSel, setRoleSel] = useState("related");

  const addLink = (familyId: number, origin: string, role = roleSel) =>
    create.mutate({
      target_type: targetType,
      target_id: targetId,
      family_id: familyId,
      role,
      origin,
    });

  return (
    <section
      className="space-y-2 rounded-lg border border-gray-200 bg-white p-3"
      data-testid={`product-panel-${targetType}`}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700">产品归属</h3>
        <Link href="/product-media" className="text-xs text-brand hover:underline">
          产品素材库 →
        </Link>
      </div>

      {targetType === "asset" ? (
        <>
          <ul className="space-y-1" data-testid="asset-links">
            {(assetLinks.data ?? []).map((l) => (
              <LinkRow
                key={l.id}
                link={l}
                onSetPrimary={() => update.mutate({ linkId: l.id, body: { role: "primary" } })}
                onRemove={() => remove.mutate(l.id)}
              />
            ))}
            {assetLinks.data && assetLinks.data.length === 0 ? (
              <p className="text-xs text-gray-400">尚未绑定产品</p>
            ) : null}
          </ul>
          <p className="text-[11px] text-gray-400">
            视频级产品默认被该视频全部镜头继承；单个镜头可在镜头页独立覆盖。
          </p>
        </>
      ) : shotView.data ? (
        <div className="space-y-2">
          <p className="text-xs text-gray-500">
            当前有效：
            <span
              className="ml-1 rounded bg-gray-100 px-1.5 py-0.5 text-[10px]"
              data-testid="effective-source"
            >
              {shotView.data.effective_source === "shot_override"
                ? "本镜头独立设置（覆盖视频级）"
                : "继承自视频"}
            </span>
            {shotView.data.is_historical ? (
              <span className="ml-1 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
                历史代次 g{shotView.data.generation}
              </span>
            ) : null}
          </p>
          <ul className="space-y-1" data-testid="shot-effective-links">
            {shotView.data.effective.map((l) => (
              <LinkRow
                key={l.id}
                link={l}
                badge={
                  shotView.data!.effective_source === "shot_override" ? "镜头级" : "视频级"
                }
                onSetPrimary={
                  l.shot_id != null
                    ? () => update.mutate({ linkId: l.id, body: { role: "primary" } })
                    : undefined
                }
                onRemove={l.shot_id != null ? () => remove.mutate(l.id) : undefined}
              />
            ))}
            {shotView.data.effective.length === 0 ? (
              <p className="text-xs text-gray-400">尚未绑定产品（视频级也为空）</p>
            ) : null}
          </ul>
          {shotView.data.effective_source === "shot_override" &&
          shotView.data.inherited.length > 0 ? (
            <details className="text-xs text-gray-500">
              <summary>查看视频级关系（被本镜头覆盖）</summary>
              <ul className="mt-1 space-y-1">
                {shotView.data.inherited.map((l) => (
                  <LinkRow key={l.id} link={l} badge="视频级" />
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-gray-400">加载中…</p>
      )}

      {/* 手动添加 */}
      <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="add-link-bar">
        <select
          value={familySel}
          onChange={(e) => setFamilySel(e.target.value)}
          className="rounded border border-gray-300 px-2 py-1"
          data-testid="panel-family-select"
        >
          <option value="">选择产品…</option>
          {(summary.data ?? []).map((f) => (
            <option key={f.family_id} value={f.family_id}>
              {f.name_zh}（{f.code}）
            </option>
          ))}
        </select>
        <select
          value={roleSel}
          onChange={(e) => setRoleSel(e.target.value)}
          className="rounded border border-gray-300 px-2 py-1"
          data-testid="panel-role-select"
        >
          <option value="related">关联产品</option>
          <option value="primary">主产品</option>
        </select>
        <button
          type="button"
          disabled={!familySel || create.isPending}
          onClick={() => addLink(Number(familySel), "manual")}
          className="rounded bg-brand px-2.5 py-1 font-medium text-white disabled:opacity-50"
          data-testid="panel-add-link"
        >
          {targetType === "shot" ? "为本镜头绑定" : "绑定产品"}
        </button>
        {create.error ? (
          <span className="text-red-500">{String((create.error as Error).message)}</span>
        ) : null}
      </div>

      {/* 确定性候选 */}
      {(suggestions.data ?? []).length > 0 ? (
        <div className="space-y-1" data-testid="panel-suggestions">
          <p className="text-[11px] text-gray-400">候选建议（人工确认后才会写入正式关系）：</p>
          {suggestions.data!.map((s) => (
            <button
              key={`${s.family_id}-${s.suggestion_type}`}
              type="button"
              onClick={() => addLink(s.family_id, s.origin_on_confirm, "related")}
              className="mr-1 rounded border border-dashed border-gray-300 px-2 py-0.5 text-[11px] text-gray-600 hover:border-brand hover:text-brand"
              data-testid={`panel-suggestion-${s.family_id}-${s.suggestion_type}`}
            >
              {s.family_name} · {s.matched_in}命中「{s.matched_text}」→ 确认关联
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}
