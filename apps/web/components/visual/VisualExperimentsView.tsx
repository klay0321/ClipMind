"use client";

import { useRef, useState } from "react";

import {
  useVisualCoverage,
  useVisualImageCandidates,
  useVisualShotCandidates,
  useVisualStatus,
} from "@/lib/hooks";
import type { VisualCandidateResponse } from "@/lib/types";

const DECISION_LABELS: Record<string, string> = {
  candidate: "候选",
  ambiguous: "存在歧义（需人工重点核对）",
  unknown: "未识别（拒识）",
  insufficient_reference: "参考图不足",
  model_unavailable: "模型不可用",
};

/** 固定实验提示（冻结文案）。 */
function ExperimentalNotice() {
  return (
    <div
      className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
      data-testid="visual-experimental-notice"
    >
      这是实验性视觉候选，不会自动修改产品归属。候选结果必须由人工核对。
    </div>
  );
}

function CandidateResultBlock({ result }: { result: VisualCandidateResponse }) {
  return (
    <div className="space-y-2" data-testid="visual-candidate-result">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span
          className="rounded bg-gray-800 px-2 py-0.5 text-xs font-medium text-white"
          data-testid="visual-decision"
        >
          {DECISION_LABELS[result.decision] ?? result.decision}
        </span>
        <span className="text-xs text-gray-500">
          provider={result.provider} · model={result.model} · 聚合={result.aggregation}
        </span>
        {result.top1_score != null ? (
          <span className="font-mono text-xs text-gray-600">
            top1={result.top1_score.toFixed(4)}
            {result.top2_score != null ? ` top2=${result.top2_score.toFixed(4)}` : ""}
            {result.margin != null ? ` margin=${result.margin.toFixed(4)}` : ""}
          </span>
        ) : null}
      </div>
      {result.unavailable_reason ? (
        <p className="text-xs text-red-600" data-testid="visual-unavailable-reason">
          {result.unavailable_reason}
        </p>
      ) : null}
      {result.confusion_warning ? (
        <div
          className="rounded border border-orange-200 bg-orange-50 p-2 text-xs text-orange-800"
          data-testid="visual-confusion-warning"
        >
          <p className="font-medium">
            ⚠ 易混淆产品（severity={result.confusion_warning.severity}）——请重点核对以下区分特征：
          </p>
          <ul className="ml-4 mt-1 list-disc">
            {result.confusion_warning.distinguishing_features.map((f, i) => (
              <li key={i}>{JSON.stringify(f)}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <ul className="divide-y divide-gray-100 rounded border border-gray-200 bg-white">
        {result.candidates.map((c, idx) => (
          <li
            key={c.target_id}
            className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm"
            data-testid={`visual-candidate-${c.target_id}`}
          >
            <span className="w-6 text-center text-xs text-gray-400">#{idx + 1}</span>
            <span className="font-medium text-gray-800">{c.family_name}</span>
            <span className="text-xs text-gray-400">{c.family_code}</span>
            <span className="font-mono text-xs">score={c.score.toFixed(4)}</span>
            <span className="text-xs text-gray-500">
              参考图 {c.embedded_reference_count}/{c.reference_count}
              {c.matched_angles.length ? ` · 匹配角度 ${c.matched_angles.join("/")}` : ""}
            </span>
            {c.best_reference_id != null ? (
              <span className="text-xs text-gray-400">最佳参考 #{c.best_reference_id}</span>
            ) : null}
          </li>
        ))}
        {result.candidates.length === 0 ? (
          <li className="px-3 py-2 text-xs text-gray-400">无候选</li>
        ) : null}
      </ul>
    </div>
  );
}

export function VisualExperimentsView() {
  const status = useVisualStatus();
  const enabled = status.data?.enabled ?? false;
  const coverage = useVisualCoverage(enabled);
  const shotMutation = useVisualShotCandidates();
  const imageMutation = useVisualImageCandidates();
  const [shotId, setShotId] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-xl font-semibold text-gray-900">产品视觉识别实验</h1>
        <ExperimentalNotice />
      </div>

      {/* 模型状态 */}
      <section
        className="rounded-lg border border-gray-200 bg-white p-4"
        data-testid="visual-status-card"
      >
        <h2 className="mb-2 text-sm font-medium text-gray-700">模型状态</h2>
        {status.isLoading ? <p className="text-xs text-gray-400">加载中…</p> : null}
        {status.data ? (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-gray-600 md:grid-cols-4">
            <div>
              <dt className="text-gray-400">实验开关</dt>
              <dd data-testid="visual-enabled">{status.data.enabled ? "已开启" : "未开启"}</dd>
            </div>
            <div>
              <dt className="text-gray-400">Provider / 模型</dt>
              <dd data-testid="visual-provider">
                {status.data.provider} · {status.data.model_id}
              </dd>
            </div>
            <div>
              <dt className="text-gray-400">设备 / 就绪</dt>
              <dd>
                {status.data.device} · {status.data.ready ? "就绪" : "未就绪"}
              </dd>
            </div>
            <div>
              <dt className="text-gray-400">可实验产品 / 合格参考图</dt>
              <dd data-testid="visual-eligible-counts">
                {status.data.eligible_family_count} / {status.data.eligible_reference_count}
              </dd>
            </div>
            {status.data.unavailable_reason ? (
              <div className="col-span-full text-red-600">
                不可用原因：{status.data.unavailable_reason}
              </div>
            ) : null}
            <div className="col-span-full text-gray-400">
              阈值（实验性，未经真实 Benchmark 校准）：
              {JSON.stringify(status.data.thresholds)}
            </div>
          </dl>
        ) : null}
      </section>

      {/* Reference Coverage */}
      <section
        className="rounded-lg border border-gray-200 bg-white p-4"
        data-testid="visual-coverage-card"
      >
        <h2 className="mb-2 text-sm font-medium text-gray-700">
          参考图覆盖（按 Family）
          {coverage.data
            ? ` · 可实验 ${coverage.data.eligible_count}/${coverage.data.total_count}`
            : ""}
        </h2>
        {!enabled ? (
          <p className="text-xs text-gray-400">实验未开启（VISUAL_RECOGNITION_ENABLED=false）</p>
        ) : coverage.data && coverage.data.items.length ? (
          <table className="w-full text-left text-xs">
            <thead className="text-gray-400">
              <tr>
                <th className="py-1 pr-3">产品族</th>
                <th className="py-1 pr-3">入驻状态</th>
                <th className="py-1 pr-3">合格图数</th>
                <th className="py-1 pr-3">角度覆盖</th>
                <th className="py-1 pr-3">可实验</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 text-gray-700">
              {coverage.data.items.map((it) => (
                <tr key={it.family_id} data-testid={`coverage-row-${it.family_id}`}>
                  <td className="py-1 pr-3">
                    {it.family_name} <span className="text-gray-400">{it.family_code}</span>
                  </td>
                  <td className="py-1 pr-3">{it.onboarding_status}</td>
                  <td className="py-1 pr-3">{it.reference_count}</td>
                  <td className="py-1 pr-3">{it.angle_coverage.join("/") || "—"}</td>
                  <td className="py-1 pr-3">
                    {it.eligible ? (
                      <span className="text-emerald-700">是</span>
                    ) : (
                      <span className="text-gray-400">否（{it.ineligible_reason}）</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-xs text-gray-400">暂无产品目录数据</p>
        )}
      </section>

      {/* Shot 候选实验 */}
      <section
        className="space-y-3 rounded-lg border border-gray-200 bg-white p-4"
        data-testid="visual-shot-experiment"
      >
        <h2 className="text-sm font-medium text-gray-700">Shot 关键帧候选实验</h2>
        <div className="flex items-center gap-2">
          <input
            value={shotId}
            onChange={(e) => setShotId(e.target.value)}
            placeholder="Shot ID"
            inputMode="numeric"
            data-testid="visual-shot-id"
            className="w-32 rounded border border-gray-300 px-2 py-1.5 text-sm"
          />
          <button
            type="button"
            data-testid="visual-run-shot"
            disabled={!enabled || !shotId.trim() || shotMutation.isPending}
            onClick={() => shotMutation.mutate({ shotId: Number(shotId) })}
            className="rounded bg-brand px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          >
            {shotMutation.isPending ? "识别中…" : "运行候选"}
          </button>
          {shotId.trim() ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`/api/shots/${shotId.trim()}/keyframe`}
              alt="Shot 关键帧"
              className="h-14 rounded border border-gray-200 object-cover"
              data-testid="visual-shot-keyframe"
            />
          ) : null}
        </div>
        {shotMutation.error ? (
          <p className="text-xs text-red-600">{String(shotMutation.error)}</p>
        ) : null}
        {shotMutation.data ? <CandidateResultBlock result={shotMutation.data} /> : null}
      </section>

      {/* 临时上传实验 */}
      <section
        className="space-y-3 rounded-lg border border-gray-200 bg-white p-4"
        data-testid="visual-upload-experiment"
      >
        <h2 className="text-sm font-medium text-gray-700">临时图片候选实验</h2>
        <p className="text-xs text-gray-400">
          图片仅在本次请求中于内存处理，完成后即弃；不会保存为产品参考图，也不会写入素材目录。
        </p>
        <div className="flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            data-testid="visual-upload-input"
            className="text-xs"
          />
          <button
            type="button"
            data-testid="visual-run-upload"
            disabled={!enabled || imageMutation.isPending}
            onClick={() => {
              const f = fileRef.current?.files?.[0];
              if (f) imageMutation.mutate(f);
            }}
            className="rounded bg-brand px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          >
            {imageMutation.isPending ? "识别中…" : "上传并识别"}
          </button>
        </div>
        {imageMutation.error ? (
          <p className="text-xs text-red-600">{String(imageMutation.error)}</p>
        ) : null}
        {imageMutation.data ? <CandidateResultBlock result={imageMutation.data} /> : null}
      </section>
    </div>
  );
}
