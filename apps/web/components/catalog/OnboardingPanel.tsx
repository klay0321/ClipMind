"use client";

import { useState } from "react";

import { Button, Chip, ConfirmDialog, TextArea, TextInput, type Tone } from "@/components/ui";
import { useOnboarding, useOnboardingAction } from "@/lib/hooks";
import type { AttributeTargetLevel, OnboardingStatus } from "@/lib/types";

import { CatalogError } from "./widgets";

// 入驻审核状态中文标签 + 色调（状态不只靠颜色，含文字）
const ONBOARDING_STATUS_META: Record<OnboardingStatus, { label: string; tone: Tone }> = {
  incomplete: { label: "资料不完整", tone: "warning" },
  ready_for_review: { label: "待人工审核", tone: "info" },
  approved: { label: "已批准", tone: "success" },
  needs_changes: { label: "需修改", tone: "warning" },
  blocked: { label: "已阻止使用", tone: "danger" },
};

export function onboardingStatusLabel(status: OnboardingStatus): string {
  return ONBOARDING_STATUS_META[status]?.label ?? status;
}

function fmtTime(v: string | null | undefined): string {
  if (!v) return "-";
  return new Date(v).toLocaleString();
}

// 入驻审核面板：状态机操作（提交/批准/退回/阻止）+ 审核意见。
// 明示：当前为可信内网人工审核，无用户权限体系；actor_label 只是显示名。
export function OnboardingPanel({
  level,
  targetId,
  readOnly = false,
}: {
  level: AttributeTargetLevel;
  targetId: number;
  readOnly?: boolean;
}) {
  const onboardingQ = useOnboarding(level, targetId);
  const action = useOnboardingAction(level, targetId);
  const [note, setNote] = useState("");
  const [actorLabel, setActorLabel] = useState("");
  const [confirmBlock, setConfirmBlock] = useState(false);

  const review = onboardingQ.data ?? null;
  const status = review?.status ?? null;

  // 状态机按钮可见性（与后端守卫一致：block 需已有记录；approve/退回仅待审核时）
  const canSubmit =
    !readOnly && (status === null || status === "incomplete" || status === "needs_changes");
  const canReview = !readOnly && status === "ready_for_review";
  const canBlock = !readOnly && review != null && status !== "blocked";

  const run = (kind: "submit" | "approve" | "request" | "block") => {
    action.mutate(
      {
        action: kind,
        req: {
          note: note.trim() || undefined,
          actor_label: actorLabel.trim() || undefined,
        },
      },
      {
        onSuccess: () => {
          setNote("");
          setConfirmBlock(false);
        },
      },
    );
  };

  if (onboardingQ.isLoading) {
    return (
      <div className="space-y-2 p-1" data-testid="onboarding-loading">
        <div className="h-10 animate-pulse rounded bg-gray-100" />
        <div className="h-20 animate-pulse rounded bg-gray-100" />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="onboarding-panel">
      {/* 诚实声明：无用户权限体系，审批不是安全控制 */}
      <div
        role="note"
        data-testid="onboarding-permission-notice"
        className="rounded border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-700"
      >
        当前为可信内网人工审核，尚未启用用户权限。
      </div>

      <CatalogError error={onboardingQ.error ?? action.error} />

      {/* 当前状态与审核信息 */}
      <div className="space-y-2 rounded border border-gray-200 bg-white p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-gray-500">当前状态</span>
          <span data-testid="onboarding-status">
            {status ? (
              <Chip tone={ONBOARDING_STATUS_META[status].tone} dot>
                {ONBOARDING_STATUS_META[status].label}
              </Chip>
            ) : (
              <Chip tone="neutral">未提交</Chip>
            )}
          </span>
          {review?.readiness_score != null ? (
            <span className="text-xs text-gray-500" data-testid="onboarding-score">
              提交时完整度 {review.readiness_score}/100
            </span>
          ) : null}
        </div>

        {review ? (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs text-gray-600 sm:grid-cols-2">
            <div className="flex gap-1">
              <dt className="shrink-0 text-gray-400">提交时间</dt>
              <dd>{fmtTime(review.submitted_at)}</dd>
            </div>
            <div className="flex gap-1">
              <dt className="shrink-0 text-gray-400">审核时间</dt>
              <dd>{fmtTime(review.reviewed_at)}</dd>
            </div>
            {review.submitted_by ? (
              <div className="flex min-w-0 gap-1">
                <dt className="shrink-0 text-gray-400">提交人</dt>
                <dd className="truncate">{review.submitted_by}</dd>
              </div>
            ) : null}
            {review.reviewed_by ? (
              <div className="flex min-w-0 gap-1">
                <dt className="shrink-0 text-gray-400">审核人</dt>
                <dd className="truncate">{review.reviewed_by}</dd>
              </div>
            ) : null}
          </dl>
        ) : (
          <p className="text-xs text-gray-400" data-testid="onboarding-empty">
            该产品尚未提交入驻审核。资料按完整度策略达标后可提交。
          </p>
        )}

        {review?.reviewer_note ? (
          <div
            className="rounded border border-gray-100 bg-gray-50 px-2.5 py-1.5"
            data-testid="onboarding-reviewer-note"
          >
            <p className="text-[11px] text-gray-400">审核意见</p>
            <p className="break-words text-xs text-gray-700">{review.reviewer_note}</p>
          </div>
        ) : null}

        {review?.readiness_snapshot ? (
          <details className="text-xs">
            <summary className="cursor-pointer text-gray-400 hover:text-gray-600">
              查看提交时完整度快照（原始 JSON）
            </summary>
            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded bg-gray-50 p-2 text-[11px] text-gray-600">
              {JSON.stringify(review.readiness_snapshot, null, 2)}
            </pre>
          </details>
        ) : null}
      </div>

      {/* 操作区：按状态机显示按钮；note / 显示名输入 */}
      {!readOnly ? (
        <div className="space-y-2 rounded border border-gray-200 bg-white p-3">
          <TextInput
            label="操作人显示名（可选；非登录身份，仅用于记录）"
            value={actorLabel}
            onChange={(e) => setActorLabel(e.target.value)}
            maxLength={64}
            data-testid="onboarding-actor"
          />
          {canReview || canBlock ? (
            <TextArea
              label="审核意见（可选）"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              maxLength={2000}
              data-testid="onboarding-note"
            />
          ) : null}

          <div className="flex flex-wrap justify-end gap-2">
            {canSubmit ? (
              <Button
                size="sm"
                variant="primary"
                onClick={() => run("submit")}
                loading={action.isPending}
                data-testid="onboarding-submit"
              >
                提交审核
              </Button>
            ) : null}
            {canReview ? (
              <>
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => run("approve")}
                  loading={action.isPending}
                  data-testid="onboarding-approve"
                >
                  批准
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => run("request")}
                  loading={action.isPending}
                  data-testid="onboarding-request-changes"
                >
                  退回修改
                </Button>
              </>
            ) : null}
            {canBlock ? (
              <Button
                size="sm"
                variant="danger"
                onClick={() => setConfirmBlock(true)}
                data-testid="onboarding-block"
              >
                阻止使用
              </Button>
            ) : null}
          </div>
          {status === "approved" ? (
            <p className="text-[11px] text-gray-400">
              已批准的产品如需重审，请先「阻止使用」或由审核人退回后重新提交。
            </p>
          ) : null}
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmBlock}
        title="阻止使用"
        message="确认将该产品标记为「已阻止使用」？表示资料存在明确错误，暂不可用于后续识别与检索。"
        confirmLabel="确认阻止"
        loading={action.isPending}
        onConfirm={() => run("block")}
        onClose={() => setConfirmBlock(false)}
      />
    </div>
  );
}
