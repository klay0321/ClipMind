"use client";

import { useRef, useState } from "react";

import { referenceFileUrl, referenceThumbnailUrl } from "@/lib/api";
import { Button, Chip, Dialog } from "@/components/ui";
import { usePromoteReference, usePromotionSuggestions, useReferenceMutations, useReferences, useUploadReferences } from "@/lib/hooks";
import {
  QUALITY_STATUSES,
  REFERENCE_ANGLES,
  type AttributeTargetLevel,
  type QualityStatus,
  type ReferenceAngle,
  type ReferenceAsset,
} from "@/lib/types";

import { CatalogError } from "./widgets";

// 角度中文标签（受控枚举常量，非产品值；导出供完整度面板等复用）
export const ANGLE_LABELS: Record<ReferenceAngle, string> = {
  front: "正面",
  back: "背面",
  left: "左侧",
  right: "右侧",
  top: "顶部",
  bottom: "底部",
  interface: "接口",
  package: "包装",
  installed: "安装后",
  powered_on: "通电",
  powered_off: "断电",
  detail: "细节",
  other: "其他",
};

// 人工质量标记中文标签（非 AI 判定）
const QUALITY_LABELS: Record<QualityStatus, string> = {
  unchecked: "未标记",
  qualified: "合格",
  blurred: "模糊",
  occluded: "遮挡",
  wrong_product: "产品错误",
  duplicate: "重复",
  low_resolution: "分辨率低",
};

function angleLabel(angle: string | null): string {
  if (!angle) return "未标角度";
  return ANGLE_LABELS[angle as ReferenceAngle] ?? angle;
}

// 单张参考图缩略：先 thumbnail，加载失败回退 /file，再失败显示占位（绝不显示破图）
function ReferenceThumb({ asset, onOpen }: { asset: ReferenceAsset; onOpen: () => void }) {
  // 0=缩略 1=原图 2=占位
  const [stage, setStage] = useState<0 | 1 | 2>(asset.has_thumbnail ? 0 : 1);
  const src = stage === 0 ? referenceThumbnailUrl(asset.id) : stage === 1 ? referenceFileUrl(asset.id) : null;

  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid={`ref-thumb-${asset.id}`}
      className="relative block aspect-square w-full overflow-hidden rounded bg-gray-100"
      aria-label="查看原图"
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={asset.original_filename ?? `参考图 ${asset.id}`}
          loading="lazy"
          onError={() => setStage((s) => (s < 2 ? ((s + 1) as 0 | 1 | 2) : 2))}
          className="h-full w-full object-cover"
        />
      ) : (
        <span
          data-testid={`ref-thumb-fallback-${asset.id}`}
          className="flex h-full w-full items-center justify-center px-1 text-center text-[10px] text-gray-400"
        >
          无法预览
        </span>
      )}
      {asset.is_primary ? (
        <span
          data-testid={`ref-primary-badge-${asset.id}`}
          className="absolute left-1 top-1 rounded bg-brand px-1 py-0.5 text-[10px] font-medium text-white"
        >
          主图
        </span>
      ) : null}
    </button>
  );
}

// 单张参考图卡片：缩略 + 角度/质量/状态编辑 + 设主图/归档/恢复
function ReferenceCard({
  asset,
  level,
  targetId,
  readOnly,
  onPreview,
}: {
  asset: ReferenceAsset;
  level: AttributeTargetLevel;
  targetId: number;
  readOnly: boolean;
  onPreview: (a: ReferenceAsset) => void;
}) {
  const m = useReferenceMutations(level, targetId);
  const archived = asset.state === "archived" || asset.archived_at != null;

  return (
    <div
      className="space-y-1.5 rounded border border-gray-200 bg-white p-2"
      data-testid={`ref-card-${asset.id}`}
    >
      <ReferenceThumb asset={asset} onOpen={() => onPreview(asset)} />

      <div className="flex flex-wrap items-center gap-1">
        <Chip tone="neutral">{angleLabel(asset.angle)}</Chip>
        {asset.quality_status !== "unchecked" ? (
          <Chip tone={asset.quality_status === "qualified" ? "success" : "warning"}>
            {QUALITY_LABELS[asset.quality_status]}
          </Chip>
        ) : null}
        {archived ? <Chip tone="muted">已归档</Chip> : null}
        {asset.state === "rejected" ? <Chip tone="danger">已否决</Chip> : null}
      </div>

      {!readOnly ? (
        <div className="space-y-1.5">
          {/* 角度选择 */}
          <select
            value={asset.angle ?? ""}
            onChange={(e) =>
              m.update.mutate({
                id: asset.id,
                req: { angle: (e.target.value || null) as ReferenceAngle | null },
              })
            }
            aria-label="角度"
            data-testid={`ref-angle-${asset.id}`}
            className="w-full rounded border border-gray-300 px-1.5 py-1 text-xs focus:border-brand focus:outline-none"
          >
            <option value="">未标角度</option>
            {REFERENCE_ANGLES.map((a) => (
              <option key={a} value={a}>
                {ANGLE_LABELS[a]}
              </option>
            ))}
          </select>

          {/* 人工质量标记（非 AI） */}
          <select
            value={asset.quality_status}
            onChange={(e) =>
              m.update.mutate({
                id: asset.id,
                req: { quality_status: e.target.value as QualityStatus },
              })
            }
            aria-label="质量标记"
            data-testid={`ref-quality-${asset.id}`}
            className="w-full rounded border border-gray-300 px-1.5 py-1 text-xs focus:border-brand focus:outline-none"
          >
            {QUALITY_STATUSES.map((q) => (
              <option key={q} value={q}>
                {QUALITY_LABELS[q]}
              </option>
            ))}
          </select>

          <div className="flex flex-wrap gap-1">
            {!archived ? (
              <>
                {!asset.is_primary ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => m.setPrimary.mutate(asset.id)}
                    loading={m.setPrimary.isPending}
                    data-testid={`ref-set-primary-${asset.id}`}
                  >
                    设为主图
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => m.archive.mutate(asset.id)}
                  loading={m.archive.isPending}
                  data-testid={`ref-archive-${asset.id}`}
                >
                  归档
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => m.restore.mutate(asset.id)}
                loading={m.restore.isPending}
                data-testid={`ref-restore-${asset.id}`}
              >
                恢复
              </Button>
            )}
          </div>
          <CatalogError
            error={m.update.error ?? m.setPrimary.error ?? m.archive.error ?? m.restore.error}
          />
        </div>
      ) : null}
    </div>
  );
}

// 上传区：点击选择或拖拽多图，multipart 上传；单张失败进 errors 但成功图不消失
// EVAL：从已确认绑定的图片素材提升参考图（仅 family 级、参考图不足时显示；逐张人工采纳）
function PromotionZone({ familyId }: { familyId: number }) {
  const suggestions = usePromotionSuggestions();
  const promote = usePromoteReference("family", familyId);
  const [lastError, setLastError] = useState<string | null>(null);
  const mine = suggestions.data?.find((s) => s.family_id === familyId);
  if (!mine) return null;
  return (
    <div
      className="space-y-2 rounded border border-amber-200 bg-amber-50 p-3"
      data-testid="ref-promotion-zone"
    >
      <p className="text-xs text-amber-800">
        该产品参考图不足（当前 {mine.active_refs} 张）。可从<b>人工确认过</b>的绑定图片中逐张提升为参考图
        （复制文件，不动源素材；提升后自动计算视觉向量并刷新识别基准）。
      </p>
      {mine.candidates.length === 0 ? (
        <p className="text-xs text-amber-700" data-testid="ref-promotion-empty">
          暂无可提升的已确认绑定图片——请在上方直接上传标准产品图。
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="ref-promotion-list">
          {mine.candidates.slice(0, 12).map((c) => (
            <div key={c.asset_id} className="rounded border border-amber-100 bg-white p-1.5">
              {c.has_poster ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={`/api/assets/${c.asset_id}/poster`}
                  alt={c.filename}
                  className="aspect-square w-full rounded object-cover"
                />
              ) : (
                <div className="flex aspect-square items-center justify-center rounded bg-gray-100 text-[10px] text-gray-400">
                  无预览
                </div>
              )}
              <p className="mt-1 truncate text-[10px] text-gray-500" title={c.filename}>
                {c.filename}
              </p>
              <Button
                size="sm"
                variant="secondary"
                className="mt-1 w-full"
                disabled={promote.isPending}
                data-testid={`ref-promote-${c.asset_id}`}
                onClick={() => {
                  setLastError(null);
                  promote.mutate(
                    { assetId: c.asset_id },
                    { onError: (e) => setLastError(e instanceof Error ? e.message : "提升失败") },
                  );
                }}
              >
                设为参考图
              </Button>
            </div>
          ))}
        </div>
      )}
      {lastError ? (
        <p className="text-xs text-red-600" data-testid="ref-promotion-error">
          {lastError}
        </p>
      ) : null}
    </div>
  );
}


function UploadZone({ level, targetId }: { level: AttributeTargetLevel; targetId: number }) {
  const upload = useUploadReferences(level, targetId);
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [angle, setAngle] = useState<string>("");
  const [errors, setErrors] = useState<{ filename: string; detail: string }[]>([]);

  const doUpload = (files: File[]) => {
    if (files.length === 0) return;
    setErrors([]);
    upload.mutate(
      { files, angle: angle || undefined },
      {
        onSuccess: (res) => {
          setErrors(res.errors ?? []);
        },
      },
    );
  };

  return (
    <div className="space-y-2" data-testid="ref-upload-zone">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={angle}
          onChange={(e) => setAngle(e.target.value)}
          aria-label="上传时默认角度"
          data-testid="ref-upload-angle"
          className="rounded border border-gray-300 px-2 py-1 text-xs focus:border-brand focus:outline-none"
        >
          <option value="">上传时不指定角度</option>
          {REFERENCE_ANGLES.map((a) => (
            <option key={a} value={a}>
              {ANGLE_LABELS[a]}
            </option>
          ))}
        </select>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          doUpload(Array.from(e.dataTransfer.files));
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        data-testid="ref-dropzone"
        className={`cursor-pointer rounded border-2 border-dashed px-4 py-6 text-center text-sm ${
          dragOver ? "border-brand bg-brand-light" : "border-gray-300 bg-gray-50"
        }`}
      >
        <p className="text-gray-600">点击选择图片，或将图片拖拽到此处上传</p>
        <p className="mt-1 text-[11px] text-gray-400">支持一次选择多张；单张失败不影响其它成功图。</p>
        {upload.isPending ? (
          <p className="mt-2 text-xs text-brand-dark" data-testid="ref-upload-progress">
            正在上传…
          </p>
        ) : null}
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          data-testid="ref-file-input"
          onChange={(e) => {
            doUpload(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
      </div>

      <CatalogError error={upload.error} />

      {errors.length > 0 ? (
        <ul
          className="space-y-1 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
          data-testid="ref-upload-errors"
        >
          {errors.map((err, i) => (
            <li key={`${err.filename}-${i}`}>
              {err.filename}：{err.detail}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// 原图预览弹窗（点击缩略看 /file）
function PreviewDialog({
  asset,
  onClose,
}: {
  asset: ReferenceAsset | null;
  onClose: () => void;
}) {
  return (
    <Dialog
      open={asset != null}
      onClose={onClose}
      title={asset?.original_filename ?? "参考图预览"}
      widthClass="max-w-3xl"
    >
      {asset ? (
        <div className="space-y-2" data-testid="ref-preview">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={referenceFileUrl(asset.id)}
            alt={asset.original_filename ?? `参考图 ${asset.id}`}
            className="mx-auto max-h-[70vh] w-auto rounded"
          />
          <div className="flex flex-wrap gap-1.5 text-xs text-gray-500">
            <Chip tone="neutral">{angleLabel(asset.angle)}</Chip>
            <Chip tone="neutral">{QUALITY_LABELS[asset.quality_status]}</Chip>
            {asset.width && asset.height ? (
              <span>
                {asset.width}×{asset.height}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </Dialog>
  );
}

// 参考图库 Tab：网格展示 + 上传 + 角度/主图/质量/归档/恢复 + 原图预览。
// 明确说明「自动产品识别尚未启用」，绝不显示虚假相似度/识别结果/模型状态。
export function ReferenceGallery({
  level,
  targetId,
  readOnly = false,
  includeArchived = false,
}: {
  level: AttributeTargetLevel;
  targetId: number;
  readOnly?: boolean;
  includeArchived?: boolean;
}) {
  const listQ = useReferences(level, targetId);
  const [preview, setPreview] = useState<ReferenceAsset | null>(null);

  const all = listQ.data ?? [];
  // rejected/archived 默认隐藏（除非显式包含归档）
  const visible = includeArchived
    ? all
    : all.filter((a) => a.state !== "archived" && a.state !== "rejected" && a.archived_at == null);

  return (
    <div className="space-y-3" data-testid="reference-gallery">
      {/* 诚实说明：自动识别未启用；绝不伪造相似度/识别结果 */}
      <div
        role="note"
        data-testid="ref-recognition-notice"
        className="rounded border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-700"
      >
        自动产品识别尚未启用。当前参考图用于建立产品资料和后续识别基线。
      </div>

      {!readOnly ? <UploadZone level={level} targetId={targetId} /> : null}
      {!readOnly && level === "family" ? <PromotionZone familyId={targetId} /> : null}

      <CatalogError error={listQ.error} />

      {listQ.isLoading ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" data-testid="ref-loading">
          {[0, 1, 2].map((i) => (
            <div key={i} className="aspect-square animate-pulse rounded bg-gray-100" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <p className="rounded border border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500" data-testid="ref-empty">
          暂无参考图。{readOnly ? "" : "上传产品各角度图片以建立资料库。"}
        </p>
      ) : (
        <div
          className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
          data-testid="ref-grid"
        >
          {visible.map((asset) => (
            <ReferenceCard
              key={asset.id}
              asset={asset}
              level={level}
              targetId={targetId}
              readOnly={readOnly}
              onPreview={setPreview}
            />
          ))}
        </div>
      )}

      <PreviewDialog asset={preview} onClose={() => setPreview(null)} />
    </div>
  );
}
