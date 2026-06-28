// 段落字段编辑器（乐观锁）。保存带 lock_version；409 冲突由上层提示「数据已被更新，请刷新」。
"use client";

import { useState } from "react";

import type { Product, ScriptSegment, SegmentUpdateRequest, StructuredRequirements } from "@/lib/types";

function toList(s: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const part of s.split(/[,，、]/)) {
    const v = part.trim();
    const k = v.toLowerCase();
    if (v && !seen.has(k)) {
      seen.add(k);
      out.push(v);
    }
  }
  return out;
}
const fromList = (a: string[] | null | undefined): string => (a ?? []).join("，");
const numOrNull = (s: string): number | null => {
  const v = s.trim();
  if (!v) return null;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : null;
};

const field =
  "w-full rounded border border-gray-300 px-2 py-1 text-xs focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand";

export function SegmentEditor({
  segment,
  products,
  onSave,
  saving,
  onCancel,
}: {
  segment: ScriptSegment;
  products: Product[];
  onSave: (req: SegmentUpdateRequest) => void;
  saving: boolean;
  onCancel: () => void;
}) {
  const sr = segment.structured_requirements ?? {};
  const [text, setText] = useState(segment.segment_text);
  const [visual, setVisual] = useState(segment.visual_requirement ?? "");
  const [dmin, setDmin] = useState(segment.target_duration_min?.toString() ?? "");
  const [dmax, setDmax] = useState(segment.target_duration_max?.toString() ?? "");
  const [productId, setProductId] = useState<number | null>(segment.product_id);
  const [scenes, setScenes] = useState(fromList(sr.scenes));
  const [actions, setActions] = useState(fromList(sr.actions));
  const [shotTypes, setShotTypes] = useState(fromList(sr.shot_types));
  const [marketing, setMarketing] = useState(fromList(sr.marketing_uses));
  const [negatives, setNegatives] = useState(fromList(segment.negative_terms));
  const [excludedRisks, setExcludedRisks] = useState(fromList(segment.excluded_risks));
  const [allowScene, setAllowScene] = useState(segment.allow_similar_scene);
  const [allowAction, setAllowAction] = useState(segment.allow_similar_action);

  const save = () => {
    if (!text.trim() || saving) return;
    const structured: StructuredRequirements = {
      scenes: toList(scenes),
      actions: toList(actions),
      shot_types: toList(shotTypes),
      marketing_uses: toList(marketing),
    };
    onSave({
      lock_version: segment.lock_version,
      segment_text: text.trim(),
      visual_requirement: visual.trim() || null,
      target_duration_min: numOrNull(dmin),
      target_duration_max: numOrNull(dmax),
      product_id: productId,
      structured_requirements: structured,
      negative_terms: toList(negatives),
      excluded_risks: toList(excludedRisks),
      allow_similar_scene: allowScene,
      allow_similar_action: allowAction,
    });
  };

  return (
    <div className="space-y-2 rounded border border-brand/30 bg-brand-light/30 p-2" data-testid="segment-editor">
      <label className="block text-[11px]">
        <span className="text-gray-500">段落文案</span>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} className={`mt-0.5 resize-y ${field}`} />
      </label>
      <label className="block text-[11px]">
        <span className="text-gray-500">画面需求</span>
        <input value={visual} onChange={(e) => setVisual(e.target.value)} className={`mt-0.5 ${field}`} />
      </label>
      <div className="grid grid-cols-3 gap-2">
        <label className="block text-[11px]">
          <span className="text-gray-500">时长下限(s)</span>
          <input type="number" min={0} value={dmin} onChange={(e) => setDmin(e.target.value)} className={`mt-0.5 ${field}`} />
        </label>
        <label className="block text-[11px]">
          <span className="text-gray-500">时长上限(s)</span>
          <input type="number" min={0} value={dmax} onChange={(e) => setDmax(e.target.value)} className={`mt-0.5 ${field}`} />
        </label>
        <label className="block text-[11px]">
          <span className="text-gray-500">产品</span>
          <select
            data-testid="seg-product"
            value={productId ?? ""}
            onChange={(e) => setProductId(e.target.value ? Number(e.target.value) : null)}
            className={`mt-0.5 ${field}`}
          >
            <option value="">不限定</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.sku ? ` · ${p.sku}` : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="block text-[11px]">
          <span className="text-gray-500">场景（逗号分隔）</span>
          <input value={scenes} onChange={(e) => setScenes(e.target.value)} className={`mt-0.5 ${field}`} />
        </label>
        <label className="block text-[11px]">
          <span className="text-gray-500">动作</span>
          <input value={actions} onChange={(e) => setActions(e.target.value)} className={`mt-0.5 ${field}`} />
        </label>
        <label className="block text-[11px]">
          <span className="text-gray-500">镜头类型</span>
          <input value={shotTypes} onChange={(e) => setShotTypes(e.target.value)} className={`mt-0.5 ${field}`} />
        </label>
        <label className="block text-[11px]">
          <span className="text-gray-500">营销用途</span>
          <input value={marketing} onChange={(e) => setMarketing(e.target.value)} className={`mt-0.5 ${field}`} />
        </label>
        <label className="block text-[11px]">
          <span className="text-gray-500">否定词</span>
          <input value={negatives} onChange={(e) => setNegatives(e.target.value)} className={`mt-0.5 ${field}`} />
        </label>
        <label className="block text-[11px]">
          <span className="text-gray-500">排除风险</span>
          <input value={excludedRisks} onChange={(e) => setExcludedRisks(e.target.value)} className={`mt-0.5 ${field}`} />
        </label>
      </div>
      <div className="flex flex-wrap gap-3">
        <label className="flex items-center gap-1 text-[11px] text-gray-600">
          <input type="checkbox" checked={allowScene} onChange={(e) => setAllowScene(e.target.checked)} />
          允许相似场景
        </label>
        <label className="flex items-center gap-1 text-[11px] text-gray-600">
          <input type="checkbox" checked={allowAction} onChange={(e) => setAllowAction(e.target.checked)} />
          允许相似动作
        </label>
      </div>
      <div className="flex gap-2 pt-1">
        <button type="button" onClick={onCancel} className="flex-1 rounded border border-gray-300 px-2 py-1 text-[11px] text-gray-600 hover:bg-gray-50">
          取消
        </button>
        <button
          type="button"
          data-testid="seg-save"
          onClick={save}
          disabled={!text.trim() || saving}
          className="flex-1 rounded bg-brand px-2 py-1 text-[11px] font-medium text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {saving ? "保存中…" : "保存"}
        </button>
      </div>
    </div>
  );
}
