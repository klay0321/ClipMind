"use client";

import { useState } from "react";

import { Pagination } from "@/components/Pagination";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { Button, Dialog, SelectInput } from "@/components/ui";
import { ApiError } from "@/lib/api";
import {
  useCancelLegacyImport,
  useCreateLegacyImport,
  useLegacyImports,
  useLegacyRules,
  usePreviewLegacyImport,
  useSourceDirectories,
} from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";
import type { LegacyPreview } from "@/lib/types";

import { IMPORT_WARNING, RunStatusChip, locationStatusLabel } from "./legacyShared";

const PAGE_SIZE = 20;

export function ImportsPanel() {
  const [page, setPage] = useState(1);
  const [showPreview, setShowPreview] = useState(false);
  const runs = useLegacyImports(page, PAGE_SIZE);
  const cancel = useCancelLegacyImport();

  return (
    <section aria-label="导入任务">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs text-gray-500">
          导入把已索引路径中命中规则的记录转换为<span className="font-medium text-gray-700">待审核的历史证据</span>。
          重复运行是幂等的：已存在的证据只累计观察次数，绝不覆盖人工审核结论。
        </p>
        <Button data-testid="open-preview-button" onClick={() => setShowPreview(true)}>
          只读预览 / 发起导入
        </Button>
      </div>

      {runs.isLoading ? (
        <Loading rows={4} />
      ) : runs.isError ? (
        <ErrorState message={(runs.error as Error).message} onRetry={() => void runs.refetch()} />
      ) : !runs.data || runs.data.items.length === 0 ? (
        <Empty title="还没有导入任务" description="先运行只读预览，确认命中范围后再正式导入。" />
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="w-full min-w-[860px] text-sm" data-testid="import-runs-table">
              <thead>
                <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                  <th className="px-3 py-2 font-medium">#</th>
                  <th className="px-3 py-2 font-medium">状态</th>
                  <th className="px-3 py-2 font-medium">模式</th>
                  <th className="px-3 py-2 font-medium">扫描位置</th>
                  <th className="px-3 py-2 font-medium">命中位置</th>
                  <th className="px-3 py-2 font-medium">新建证据</th>
                  <th className="px-3 py-2 font-medium">已存在</th>
                  <th className="px-3 py-2 font-medium">错误</th>
                  <th className="px-3 py-2 font-medium">创建时间</th>
                  <th className="px-3 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.items.map((run) => (
                  <tr
                    key={run.id}
                    data-testid={`import-run-${run.id}`}
                    className="border-b border-gray-50 last:border-0 hover:bg-gray-50"
                  >
                    <td className="px-3 py-2 text-gray-500">{run.id}</td>
                    <td className="px-3 py-2">
                      <RunStatusChip status={run.status} />
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">
                      {run.dry_run ? "试运行（不写入）" : "正式导入"}
                    </td>
                    <td className="px-3 py-2 text-gray-600">{run.scanned_location_count}</td>
                    <td className="px-3 py-2 text-gray-600">{run.matched_location_count}</td>
                    <td className="px-3 py-2 font-medium text-emerald-700">
                      {run.created_evidence_count}
                    </td>
                    <td className="px-3 py-2 text-gray-600">{run.existing_evidence_count}</td>
                    <td className="px-3 py-2">
                      {run.error_count > 0 ? (
                        <span className="text-red-600" title={run.error_summary ?? undefined}>
                          {run.error_count}
                        </span>
                      ) : (
                        <span className="text-gray-400">0</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-gray-500">{formatDateTime(run.created_at)}</td>
                    <td className="px-3 py-2">
                      {run.status === "pending" || run.status === "running" ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={cancel.isPending}
                          onClick={() => cancel.mutate(run.id)}
                        >
                          取消
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={runs.data.total} onPageChange={setPage} />
        </>
      )}

      {showPreview ? <PreviewImportDialog onClose={() => setShowPreview(false)} /> : null}
    </section>
  );
}

function PreviewImportDialog({ onClose }: { onClose: () => void }) {
  const [sourceDirId, setSourceDirId] = useState<string>("");
  const [ruleIds, setRuleIds] = useState<number[]>([]);
  const [preview, setPreview] = useState<LegacyPreview | null>(null);
  const dirs = useSourceDirectories();
  const rules = useLegacyRules(false);
  const previewMutation = usePreviewLegacyImport();
  const importMutation = useCreateLegacyImport();

  const enabledRules = (rules.data?.items ?? []).filter((r) => r.enabled);
  const scope = {
    source_directory_id: sourceDirId ? Number(sourceDirId) : undefined,
    rule_ids: ruleIds.length > 0 ? ruleIds : undefined,
  };

  const toggleRule = (id: number) => {
    setPreview(null);
    setRuleIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const runPreview = () => {
    previewMutation.mutate(scope, { onSuccess: setPreview });
  };

  const runImport = () => {
    importMutation.mutate(scope, { onSuccess: onClose });
  };

  return (
    <Dialog open title="历史证据导入（先预览后导入）" onClose={onClose}>
      <div className="flex flex-col gap-3" data-testid="preview-import-dialog">
        <div className="grid grid-cols-2 gap-3">
          <SelectInput
            label="范围：源目录"
            value={sourceDirId}
            onChange={(e) => {
              setSourceDirId(e.target.value);
              setPreview(null);
            }}
            data-testid="preview-source-dir"
          >
            <option value="">全部源目录</option>
            {dirs.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </SelectInput>
          <div>
            <div className="mb-1 text-xs font-medium text-gray-600">
              规则（不勾选 = 全部启用规则）
            </div>
            <div className="max-h-24 overflow-y-auto rounded border border-gray-200 px-2 py-1">
              {enabledRules.length === 0 ? (
                <p className="py-1 text-xs text-gray-400">没有启用中的规则，请先到「规则管理」创建。</p>
              ) : (
                enabledRules.map((r) => (
                  <label key={r.id} className="flex items-center gap-1.5 py-0.5 text-xs text-gray-700">
                    <input
                      type="checkbox"
                      checked={ruleIds.includes(r.id)}
                      onChange={() => toggleRule(r.id)}
                      data-testid={`preview-rule-${r.id}`}
                    />
                    <span className="truncate">{r.name}</span>
                  </label>
                ))
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            onClick={runPreview}
            disabled={previewMutation.isPending || enabledRules.length === 0}
            data-testid="run-preview-button"
          >
            {previewMutation.isPending ? "预览中…" : "运行只读预览"}
          </Button>
          <span className="text-xs text-gray-400">预览零写入：不创建任务，也不创建任何证据。</span>
        </div>

        {previewMutation.isError ? (
          <p className="text-xs text-red-600">
            {previewMutation.error instanceof ApiError ? previewMutation.error.message : "预览失败"}
          </p>
        ) : null}

        {preview ? (
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3" data-testid="preview-result">
            <div className="grid grid-cols-3 gap-2 text-center text-xs">
              <PreviewStat label="扫描位置" value={preview.scanned_location_count} />
              <PreviewStat label="命中位置" value={preview.matched_location_count} />
              <PreviewStat label="涉及素材" value={preview.matched_asset_count} />
              <PreviewStat label="将新建证据" value={preview.would_create_count} highlight />
              <PreviewStat label="已存在证据" value={preview.existing_evidence_count} />
              <PreviewStat label="解析错误" value={preview.error_count} />
            </div>
            {Object.keys(preview.by_location_status).length > 0 ? (
              <p className="mt-2 text-xs text-gray-500">
                按位置状态：
                {Object.entries(preview.by_location_status)
                  .map(([k, v]) => `${locationStatusLabel(k)} ${v}`)
                  .join("，")}
              </p>
            ) : null}
            {preview.samples.length > 0 ? (
              <div className="mt-2 max-h-36 overflow-y-auto rounded border border-gray-200 bg-white">
                {preview.samples.map((s, i) => (
                  <div
                    key={`${s.asset_id}-${i}`}
                    className="flex items-center justify-between gap-2 border-b border-gray-50 px-2 py-1 text-xs last:border-0"
                  >
                    <span className="truncate text-gray-600" title={s.relative_path}>
                      {s.relative_path}
                    </span>
                    <span className="shrink-0 text-gray-400">
                      {s.rule_name}
                      {s.already_exists ? "（已存在）" : ""}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-xs text-gray-400">没有命中任何位置。</p>
            )}

            <div className="mt-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800" data-testid="import-warning">
              {IMPORT_WARNING}
            </div>
            {importMutation.isError ? (
              <p className="mt-2 text-xs text-red-600">
                {importMutation.error instanceof ApiError
                  ? importMutation.error.message
                  : "发起导入失败"}
              </p>
            ) : null}
            <div className="mt-2 flex justify-end gap-2">
              <Button variant="secondary" onClick={onClose}>
                取消
              </Button>
              <Button
                onClick={runImport}
                disabled={importMutation.isPending || preview.matched_location_count === 0}
                data-testid="confirm-import-button"
              >
                {importMutation.isPending ? "发起中…" : "确认正式导入"}
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}

function PreviewStat({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: number;
  highlight?: boolean;
}) {
  return (
    <div className="rounded bg-white px-2 py-1.5">
      <div className={highlight ? "text-base font-semibold text-brand" : "text-base font-semibold text-gray-800"}>
        {value}
      </div>
      <div className="text-[10px] text-gray-400">{label}</div>
    </div>
  );
}
