"use client";

import { useState } from "react";

import { usePmMutations, usePmOperations, usePmUndo, usePmUnassignedGroups } from "@/lib/hooks";
import type { FamilyMediaSummary, UnassignedGroup } from "@/lib/types";
import { cn } from "@/lib/cn";

/** 组卡片：预览 + 排除异常 + 显式整组确认（绝不默认全库）。 */
function GroupCard({
  group,
  families,
  onConfirmed,
}: {
  group: UnassignedGroup;
  families: FamilyMediaSummary[];
  onConfirmed: (msg: string) => void;
}) {
  const { bulk } = usePmMutations();
  const suggested = group.suggested[0];
  const [familySel, setFamilySel] = useState<string>(
    suggested ? String(suggested.family_id) : "",
  );
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState(false);
  const keyOf = (t: { target_type: string; target_id: number }) =>
    `${t.target_type}:${t.target_id}`;
  const effective = group.targets.filter((t) => !excluded.has(keyOf(t)));

  const confirm = async () => {
    if (!familySel || effective.length === 0) return;
    const res = await bulk.mutateAsync({
      items: effective,
      family_id: Number(familySel),
      role: "related",
      origin: suggested && String(suggested.family_id) === familySel
        ? "path_or_filename_confirmed"
        : "bulk_manual",
    });
    onConfirmed(
      `「${group.label}」绑定完成：成功 ${res.completed.length}，跳过 ${res.skipped.length}，` +
        `失败 ${res.failed.length}（可在操作历史撤销）`,
    );
  };

  return (
    <div className="rounded border border-gray-200 bg-white p-3 text-xs" data-testid={`group-${group.key}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-gray-800">{group.label}</span>
        <span className="rounded bg-gray-100 px-1.5 py-0.5 text-gray-600">{group.count} 项</span>
        {suggested ? (
          <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700">
            建议：{suggested.family_name}（{suggested.matched_in}命中）
          </span>
        ) : (
          <span className="rounded bg-gray-50 px-1.5 py-0.5 text-gray-400">无候选</span>
        )}
        <button
          type="button"
          className="ml-auto text-brand hover:underline"
          onClick={() => setOpen((v) => !v)}
          data-testid={`group-toggle-${group.key}`}
        >
          {open ? "收起" : "预览与确认"}
        </button>
      </div>
      {open ? (
        <div className="mt-2 space-y-2">
          <div className="grid grid-cols-3 gap-1.5 md:grid-cols-6">
            {group.preview.map((p) => {
              const k = `${p.target_type}:${p.target_id}`;
              const ex = excluded.has(k);
              return (
                <button
                  key={k}
                  type="button"
                  onClick={() =>
                    setExcluded((prev) => {
                      const next = new Set(prev);
                      if (next.has(k)) next.delete(k);
                      else next.add(k);
                      return next;
                    })
                  }
                  className={cn(
                    "relative rounded border text-left",
                    ex ? "border-red-300 opacity-40" : "border-gray-200",
                  )}
                  title={ex ? "已排除（点击恢复）" : "点击排除此项"}
                  data-testid={`group-item-${k.replace(":", "-")}`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={
                      p.target_type === "shot"
                        ? `/api/shots/${p.target_id}/keyframe`
                        : `/api/assets/${p.target_id}/poster`
                    }
                    alt=""
                    className="h-16 w-full rounded-t object-cover"
                    onError={(e) => ((e.target as HTMLImageElement).style.opacity = "0.2")}
                  />
                  <span className="block truncate px-1 py-0.5 text-[10px] text-gray-500">
                    {p.filename ?? `镜头#${p.shot_id}`}
                  </span>
                  {ex ? (
                    <span className="absolute right-1 top-1 rounded bg-red-500 px-1 text-[9px] text-white">
                      已排除
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
          {group.count > group.preview.length ? (
            <p className="text-[10px] text-gray-400">
              预览前 {group.preview.length} 项；确认将作用于整组 {effective.length} 项
              （排除仅对预览项生效）
            </p>
          ) : null}
          {suggested ? (
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={familySel}
                onChange={(e) => setFamilySel(e.target.value)}
                className="rounded border border-gray-300 px-2 py-1"
                data-testid={`group-family-${group.key}`}
              >
                <option value="">选择产品…</option>
                {families.map((f) => (
                  <option key={f.family_id} value={f.family_id}>
                    {f.name_zh}（{f.code}）
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={!familySel || effective.length === 0 || bulk.isPending}
                onClick={confirm}
                className="rounded bg-brand px-3 py-1 font-medium text-white disabled:opacity-50"
                data-testid={`group-confirm-${group.key}`}
              >
                {bulk.isPending ? "绑定中…" : `绑定 ${effective.length} 项`}
              </button>
            </div>
          ) : (
            /* PM-UX 守卫：无候选=系统没有任何证据，整组绑定到同一产品几乎必然
               混入错绑（真实事故：200 项误绑）。改走逐项处理或以图搜图。 */
            <p
              className="rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] text-amber-800"
              data-testid={`group-no-suggestion-${group.key}`}
            >
              该组没有任何候选证据，不提供整组绑定（避免批量绑错）。请切换到
              「逐项处理」视图翻页多选绑定，或先用以图搜图确认产品。
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}

/** 分组审核队列 + 操作历史（撤销）。 */
export function GroupedReview({ families }: { families: FamilyMediaSummary[] }) {
  const [kind, setKind] = useState("image");
  const [groupBy, setGroupBy] = useState("suggested_family");
  const groups = usePmUnassignedGroups(kind, groupBy);
  const ops = usePmOperations(1);
  const undo = usePmUndo();
  const [msg, setMsg] = useState<string | null>(null);
  const [showOps, setShowOps] = useState(false);

  return (
    <section className="space-y-3 rounded-lg border border-gray-200 bg-white p-4" data-testid="grouped-review">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-medium text-gray-700">候选批量审核</h2>
        <div className="flex gap-1">
          {["image", "video", "shot"].map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setKind(k)}
              data-testid={`review-kind-${k}`}
              className={cn(
                "rounded-full border px-2.5 py-1 text-xs",
                kind === k ? "border-brand bg-brand/10 text-brand" : "border-gray-300 text-gray-600",
              )}
            >
              {k === "image" ? "图片" : k === "video" ? "视频" : "Shot"}
            </button>
          ))}
        </div>
        <div className="flex gap-1 text-xs">
          {[
            { key: "suggested_family", label: "按建议产品" },
            { key: "directory", label: "按来源目录" },
          ].map((g) => (
            <button
              key={g.key}
              type="button"
              onClick={() => setGroupBy(g.key)}
              data-testid={`group-by-${g.key}`}
              className={cn(
                "rounded border px-2 py-1",
                groupBy === g.key ? "border-brand text-brand" : "border-gray-300 text-gray-500",
              )}
            >
              {g.label}
            </button>
          ))}
        </div>
        {groups.data ? (
          <span className="text-xs text-gray-400" data-testid="review-total">
            待标注 {groups.data.total_items} 项 / {groups.data.groups.length} 组
            {groups.data.truncated ? "（超上限已截断，处理后刷新）" : ""}
          </span>
        ) : null}
        <button
          type="button"
          className="ml-auto text-xs text-gray-500 hover:text-brand"
          onClick={() => setShowOps((v) => !v)}
          data-testid="toggle-operations"
        >
          操作历史{showOps ? " ▲" : " ▼"}
        </button>
      </div>

      {msg ? (
        <p className="rounded bg-emerald-50 px-2 py-1 text-xs text-emerald-700" data-testid="review-msg">
          {msg}
        </p>
      ) : null}

      {showOps ? (
        <div className="space-y-1 rounded border border-gray-100 bg-gray-50 p-2" data-testid="operations-panel">
          {(ops.data?.items ?? []).map((o) => (
            <div key={o.id} className="flex flex-wrap items-center gap-2 text-[11px] text-gray-600">
              <span className="text-gray-400">{new Date(o.created_at).toLocaleString()}</span>
              <span className="rounded bg-gray-200 px-1">{o.kind}</span>
              <span>
                成功 {o.completed_count} / 跳过 {o.skipped_count} / 失败 {o.failed_count}
              </span>
              <span className="text-gray-400">{o.actor_label}</span>
              {o.undone_at ? (
                <span className="text-amber-600">已撤销</span>
              ) : o.undoable ? (
                <button
                  type="button"
                  className="text-red-500 hover:underline"
                  onClick={async () => {
                    const r = await undo.mutateAsync(o.id);
                    setMsg(
                      `撤销完成：移除 ${(r as { removed_count: number }).removed_count} 条` +
                        `，保留 ${(r as { kept_count: number }).kept_count} 条（已被后续修改或删除）`,
                    );
                  }}
                  data-testid={`undo-${o.id}`}
                >
                  撤销
                </button>
              ) : null}
            </div>
          ))}
          {ops.data && ops.data.items.length === 0 ? (
            <p className="text-[11px] text-gray-400">暂无操作记录</p>
          ) : null}
        </div>
      ) : null}

      <div className="space-y-2">
        {(groups.data?.groups ?? []).map((g) => (
          <GroupCard key={g.key} group={g} families={families} onConfirmed={setMsg} />
        ))}
        {groups.data && groups.data.groups.length === 0 ? (
          <p className="text-xs text-gray-400">该类型没有待标注素材 🎉</p>
        ) : null}
      </div>
    </section>
  );
}
