"use client";

import { useMemo, useState } from "react";

import { Button, Dialog } from "@/components/ui";
import { useFamilies, useMergeCatalogNode, useSkus, useVariants } from "@/lib/hooks";
import type { CatalogLevel } from "@/lib/types";

import { CatalogError, levelLabel } from "./widgets";

// 合并对话框：选择同层级、同约束（variant/sku 须同 family）的目标 + 确认。
// 仅 family / variant / sku 支持合并（category 无 merge 接口）。
export function MergeDialog({
  open,
  onClose,
  level,
  sourceId,
  sourceName,
  familyId,
}: {
  open: boolean;
  onClose: () => void;
  level: Exclude<CatalogLevel, "category">;
  sourceId: number;
  sourceName: string;
  // variant/sku 合并须同 family：传入源实体所属 family 以约束候选目标
  familyId: number | null;
}) {
  const [targetId, setTargetId] = useState<number | null>(null);
  const merge = useMergeCatalogNode();

  // 按层级取同层候选（含归档），前端再排除源自身与已合并项。
  const famQ = useFamilies({ include_archived: true, limit: 500 }, open && level === "family");
  const varQ = useVariants(
    { family_id: familyId ?? undefined, include_archived: true, limit: 500 },
    open && level === "variant" && familyId != null,
  );
  const skuQ = useSkus(
    { family_id: familyId ?? undefined, include_archived: true, limit: 500 },
    open && level === "sku" && familyId != null,
  );

  const candidates = useMemo(() => {
    const rows =
      level === "family"
        ? (famQ.data?.items ?? [])
        : level === "variant"
          ? (varQ.data?.items ?? [])
          : (skuQ.data?.items ?? []);
    return rows.filter((r) => r.id !== sourceId && r.status !== "merged");
  }, [level, famQ.data, varQ.data, skuQ.data, sourceId]);

  const submit = () => {
    if (targetId == null) return;
    merge.mutate(
      { level, id: sourceId, req: { target_id: targetId } },
      {
        onSuccess: () => {
          setTargetId(null);
          onClose();
        },
      },
    );
  };

  const close = () => {
    setTargetId(null);
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title={`合并${levelLabel(level)}`}
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={merge.isPending}>
            取消
          </Button>
          <Button
            variant="danger"
            onClick={submit}
            disabled={targetId == null || merge.isPending}
            loading={merge.isPending}
            data-testid="submit-merge"
          >
            确认合并
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-gray-600">
          将「<span className="font-medium">{sourceName}</span>」合并到下方所选目标。合并后源节点保留为
          「已合并」终态并重定向到目标，历史关系不丢失，此操作不可撤销。
        </p>
        {level !== "family" && familyId == null ? (
          <p className="text-xs text-amber-700" data-testid="merge-need-family">
            该{levelLabel(level)}缺少所属产品信息，无法确定合并候选。
          </p>
        ) : candidates.length === 0 ? (
          <p className="text-xs text-gray-400" data-testid="merge-no-candidate">
            没有可合并的同层级目标。
          </p>
        ) : (
          <label className="block space-y-1">
            <span className="text-xs font-medium text-gray-600">合并目标</span>
            <select
              value={targetId ?? ""}
              onChange={(e) => setTargetId(e.target.value ? Number(e.target.value) : null)}
              data-testid="merge-target"
              aria-label="合并目标"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none"
            >
              <option value="">请选择目标…</option>
              {candidates.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name_zh}（{c.code}）
                </option>
              ))}
            </select>
          </label>
        )}
        <CatalogError error={merge.error} />
      </div>
    </Dialog>
  );
}
