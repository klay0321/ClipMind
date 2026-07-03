"use client";

import { useState } from "react";

import { Button, Dialog, Field } from "@/components/ui";
import { ApiError } from "@/lib/api";
import {
  useAnalysisGenerations,
  useCreateUsage,
  useFinalVideos,
  useShotsByGeneration,
} from "@/lib/hooks";
import type { ReviewItem } from "@/lib/types";

/** 从历史弱证据补录正式血缘（“根据历史线索补录正式血缘”）。

 * 冻结流程：Asset 预填 → **人工**选成片 → **人工**从该 Asset 的
 * current/historical Shot 中选具体 Shot（绝不默认选第一个）→ 创建
 * manual proposed usage → 由用户在审核列表再次明确 confirm 才计入正式次数。
 * 证据本体保留（可继续 accept 或保持 pending）。
 */
export function ClueLineageDialog({
  clue,
  onClose,
}: {
  clue: ReviewItem;
  onClose: () => void;
}) {
  const [fvQuery, setFvQuery] = useState("");
  const [finalVideoId, setFinalVideoId] = useState<number | null>(null);
  const [generation, setGeneration] = useState<number | null>(null);
  const [shotId, setShotId] = useState<number | null>(null);
  const [created, setCreated] = useState(false);

  const finalVideos = useFinalVideos({
    page: 1,
    page_size: 20,
    q: fvQuery.trim() || undefined,
  });
  const generations = useAnalysisGenerations(clue.asset_id);
  const currentGen = generations.data?.current_generation ?? null;
  const effectiveGen = generation ?? currentGen;
  const shots = useShotsByGeneration(clue.asset_id, effectiveGen);
  const create = useCreateUsage(finalVideoId ?? 0);

  const submit = () => {
    if (finalVideoId == null || shotId == null) return;
    create.mutate(
      {
        source_shot_id: shotId,
        evidence_summary: `根据历史线索补录（证据 #${clue.item_id}）`,
      },
      { onSuccess: () => setCreated(true) },
    );
  };

  return (
    <Dialog open title="根据历史线索补录正式血缘" onClose={onClose}>
      {created ? (
        <div className="flex flex-col gap-3" data-testid="clue-created">
          <p className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            已创建<span className="font-medium">人工候选（proposed）</span>血缘。
            它<span className="font-medium">尚未计入正式使用次数</span>——
            请回到「待审核」列表再次明确确认后才会成为 confirmed。
          </p>
          <p className="text-xs text-gray-500">
            历史证据本体已保留，可继续接受或保持待审。
          </p>
          <div className="flex justify-end">
            <Button onClick={onClose} data-testid="clue-done">
              完成
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3" data-testid="clue-lineage-form">
          <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            此操作只创建<span className="font-medium">候选</span>血缘，不会自动确认、
            不会修改历史证据；成片与具体镜头都必须人工选择。
          </p>
          <Field label={`来源素材（自动预填）`}>
            <p className="truncate rounded border border-gray-200 bg-gray-50 px-2 py-1.5 text-sm text-gray-700">
              {clue.asset_filename ?? `素材 #${clue.asset_id}`}
            </p>
          </Field>

          <Field label="最终成片（人工选择）">
            <input
              value={fvQuery}
              onChange={(e) => setFvQuery(e.target.value)}
              placeholder="搜索成片标题…"
              data-testid="clue-fv-search"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none"
            />
            <div className="mt-1 max-h-32 overflow-y-auto rounded border border-gray-200">
              {finalVideos.data?.items.length ? (
                finalVideos.data.items.map((fv) => (
                  <button
                    key={fv.id}
                    type="button"
                    onClick={() => setFinalVideoId(fv.id)}
                    data-testid={`clue-fv-option-${fv.id}`}
                    className={`block w-full truncate px-2 py-1.5 text-left text-xs ${
                      finalVideoId === fv.id
                        ? "bg-brand/10 font-medium text-brand"
                        : "hover:bg-gray-50"
                    }`}
                  >
                    #{fv.id} {fv.title}
                  </button>
                ))
              ) : (
                <div className="px-2 py-2 text-xs text-gray-400">
                  没有成片记录。请先在「成片与使用记录」登记成片。
                </div>
              )}
            </div>
          </Field>

          <Field label="具体镜头（人工选择；不默认选中）">
            {generations.data && (generations.data.items?.length ?? 0) > 1 ? (
              <select
                value={effectiveGen ?? ""}
                onChange={(e) => {
                  setGeneration(Number(e.target.value));
                  setShotId(null);
                }}
                aria-label="分析代次"
                className="mb-1 w-40 rounded border border-gray-300 px-2 py-1 text-xs"
              >
                {generations.data.items.map((g: { generation: number }) => (
                  <option key={g.generation} value={g.generation}>
                    第 {g.generation} 代
                    {g.generation === currentGen ? "（当前）" : "（历史）"}
                  </option>
                ))}
              </select>
            ) : null}
            <div className="max-h-32 overflow-y-auto rounded border border-gray-200">
              {shots.data?.items.length ? (
                shots.data.items.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setShotId(s.id)}
                    data-testid={`clue-shot-${s.id}`}
                    className={`block w-full truncate px-2 py-1.5 text-left text-xs ${
                      shotId === s.id
                        ? "bg-brand/10 font-medium text-brand"
                        : "hover:bg-gray-50"
                    }`}
                  >
                    镜头 #{s.sequence_no}（{s.start_time.toFixed(1)}s –{" "}
                    {s.end_time.toFixed(1)}s）
                  </button>
                ))
              ) : (
                <div className="px-2 py-2 text-xs text-gray-400">
                  该素材当前代次没有可用镜头。
                </div>
              )}
            </div>
          </Field>

          {create.isError ? (
            <p className="text-xs text-red-600" data-testid="clue-error">
              {create.error instanceof ApiError
                ? create.error.status === 409
                  ? `该成片与该镜头已存在使用关系：${create.error.message}`
                  : create.error.message
                : "创建失败"}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              取消
            </Button>
            <Button
              onClick={submit}
              disabled={finalVideoId == null || shotId == null || create.isPending}
              data-testid="clue-submit"
            >
              {create.isPending ? "创建中…" : "创建候选血缘（proposed）"}
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
