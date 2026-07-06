"use client";

import { useEffect, useState } from "react";

import { Button, ConfirmDialog, TextInput } from "@/components/ui";
import { cn } from "@/lib/cn";
import {
  useArchiveCatalogNode,
  useCatalogNode,
  useCatalogProfile,
  useCategories,
  useFamilies,
  useRestoreCatalogNode,
  useSetCatalogStatus,
  useSkus,
  useUpdateCategory,
  useUpdateFamily,
  useUpdateSku,
  useUpdateVariant,
  useVariants,
} from "@/lib/hooks";
import type { AttributeTargetLevel, CatalogStatus, Family, Sku, Variant } from "@/lib/types";

import { AliasManager } from "./AliasManager";
import { AttributesTab } from "./AttributesTab";
import { ConfusionsPanel } from "./ConfusionsPanel";
import { HistoryPanel } from "./HistoryPanel";
import { MergeDialog } from "./MergeDialog";
import { OnboardingPanel } from "./OnboardingPanel";
import { ReadinessPanel } from "./ReadinessPanel";
import { ReferenceGallery } from "./ReferenceGallery";
import type { SelectedNode } from "./CatalogTree";
import { CatalogError, CatalogStatusBadge, LevelBadge, levelLabel } from "./widgets";

// 允许的状态切换（与后端 _TRANSITIONS 对齐；archive/restore 走各自按钮）
const STATUS_ACTIONS: Record<CatalogStatus, { to: CatalogStatus; label: string }[]> = {
  draft: [{ to: "active", label: "启用" }],
  active: [{ to: "paused", label: "暂停" }],
  paused: [{ to: "active", label: "恢复启用" }],
  archived: [],
  merged: [],
};

// 通用节点字段（各层都有）
interface NodeCommon {
  id: number;
  code: string;
  name_zh: string;
  name_en: string | null;
  status: CatalogStatus;
  category_id?: number | null;
  family_id?: number;
  variant_id?: number | null;
}

// 详情内 Tab（仅 family/variant/sku 层展示 basic 之外的资产 / 治理 Tab）
type DetailTab =
  | "basic"
  | "attributes"
  | "references"
  | "readiness"
  | "onboarding"
  | "confusions"
  | "history";

export function EntityDetail({
  selected,
  onSelect,
}: {
  selected: SelectedNode;
  onSelect: (n: SelectedNode) => void;
}) {
  const { level, id } = selected;
  const nodeQ = useCatalogNode(level, id);
  const node = nodeQ.data as NodeCommon | undefined;

  if (nodeQ.isLoading) {
    return (
      <div className="animate-pulse space-y-3 p-4" data-testid="detail-loading">
        <div className="h-6 w-1/2 rounded bg-gray-100" />
        <div className="h-4 w-1/3 rounded bg-gray-100" />
        <div className="h-24 rounded bg-gray-100" />
      </div>
    );
  }
  if (nodeQ.isError || !node) {
    return (
      <div className="p-4" data-testid="detail-error">
        <CatalogError error={nodeQ.error ?? new Error("加载失败")} />
      </div>
    );
  }

  return <DetailBody key={`${level}-${id}`} node={node} level={level} onSelect={onSelect} />;
}

function DetailBody({
  node,
  level,
  onSelect,
}: {
  node: NodeCommon;
  level: SelectedNode["level"];
  onSelect: (n: SelectedNode) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [nameZh, setNameZh] = useState(node.name_zh);
  const [nameEn, setNameEn] = useState(node.name_en ?? "");
  // family 层：归属分类（激活前置条件——完整度检查项"归属分类/上级已启用"）
  const [categorySel, setCategorySel] = useState<string>(
    node.category_id != null ? String(node.category_id) : "",
  );
  const [showMerge, setShowMerge] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [tab, setTab] = useState<DetailTab>("basic");

  useEffect(() => {
    setEditing(false);
    setNameZh(node.name_zh);
    setNameEn(node.name_en ?? "");
    setCategorySel(node.category_id != null ? String(node.category_id) : "");
    setTab("basic");
  }, [node.id, node.name_zh, node.name_en, node.category_id]);

  // 分类列表：family 编辑下拉 + 非编辑态显示归属名（其余层不拉取）
  const categoriesQ = useCategories(level === "family" ? { limit: 100 } : { limit: 1 });
  const categories = level === "family" ? (categoriesQ.data?.items ?? []) : [];
  const currentCategory =
    level === "family" && node.category_id != null
      ? categories.find((c) => c.id === node.category_id)
      : undefined;

  // 属性 / 参考图仅 family/variant/sku 层承载（category 层不显示这两个 Tab）
  const hasAssetTabs = level !== "category";
  const attrLevel = level as AttributeTargetLevel;

  // profile 提供该节点所属 category_id（variant/sku 不直接持有）+ Tab 徽标计数（真实计数，不估算）。
  // 仅在有资产 Tab 的层拉取，避免 category 层多余请求。
  const profileQ = useCatalogProfile(hasAssetTabs ? level : null, hasAssetTabs ? node.id : null);
  const profile = profileQ.data;
  // category_id：family 自身有；variant/sku 从 profile 取（未加载时为 null，属性定义仅拉全局）
  const categoryId =
    level === "family" ? (node.category_id ?? null) : (profile?.category_id ?? null);

  const updateCategory = useUpdateCategory();
  const updateFamily = useUpdateFamily();
  const updateVariant = useUpdateVariant();
  const updateSku = useUpdateSku();
  const setStatus = useSetCatalogStatus();
  const archive = useArchiveCatalogNode();
  const restore = useRestoreCatalogNode();

  const updateError =
    updateCategory.error ??
    updateFamily.error ??
    updateVariant.error ??
    updateSku.error ??
    setStatus.error ??
    archive.error ??
    restore.error;

  const readOnly = node.status === "archived" || node.status === "merged";

  const saveRename = () => {
    const zh = nameZh.trim();
    if (!zh) return;
    const opts = { onSuccess: () => setEditing(false) };
    const req = { name_zh: zh, name_en: nameEn.trim() || null };
    switch (level) {
      case "category":
        updateCategory.mutate({ id: node.id, req }, opts);
        break;
      case "family":
        updateFamily.mutate(
          {
            id: node.id,
            req: {
              ...req,
              category_id: categorySel === "" ? null : Number(categorySel),
            },
          },
          opts,
        );
        break;
      case "variant":
        updateVariant.mutate({ id: node.id, req }, opts);
        break;
      case "sku":
        updateSku.mutate({ id: node.id, req: { name_zh: zh, name_en: nameEn.trim() || null } }, opts);
        break;
    }
  };

  const doStatus = (to: CatalogStatus) => {
    setStatus.mutate({ level, id: node.id, status: to });
  };

  // family_id 用于 variant/sku 合并候选约束
  const familyId =
    level === "variant" || level === "sku" ? (node.family_id ?? null) : null;

  // 四层统一：draft→active / active→paused / paused→active（archive/restore 走各自按钮）
  const statusActions = STATUS_ACTIONS[node.status];
  const savingRename =
    updateCategory.isPending ||
    updateFamily.isPending ||
    updateVariant.isPending ||
    updateSku.isPending;

  return (
    <div className="space-y-4 p-4" data-testid="entity-detail">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <LevelBadge level={level} />
            <CatalogStatusBadge status={node.status} />
          </div>
          <h2
            className="mt-1 break-words text-lg font-semibold text-gray-900"
            data-testid="detail-name"
          >
            {node.name_zh}
          </h2>
          {node.name_en ? (
            <p className="break-words text-sm text-gray-500">{node.name_en}</p>
          ) : null}
          <p className="mt-0.5 text-[11px] text-gray-400">编码 {node.code}</p>
          {level === "family" ? (
            <p className="mt-0.5 text-[11px] text-gray-400" data-testid="detail-category">
              归属分类：
              {node.category_id == null ? (
                <span className="text-amber-600">未归属（激活前须在「编辑」中选择分类）</span>
              ) : (
                <span className="text-gray-600">
                  {currentCategory
                    ? `${currentCategory.name_zh}${currentCategory.status !== "active" ? "（该分类未启用，须先启用）" : ""}`
                    : `#${node.category_id}`}
                </span>
              )}
            </p>
          ) : null}
        </div>
        {!readOnly ? (
          <div className="flex flex-wrap gap-1.5">
            {!editing ? (
              <Button size="sm" variant="secondary" onClick={() => setEditing(true)} data-testid="edit-node">
                编辑
              </Button>
            ) : null}
            {statusActions.map((a) => (
              <Button
                key={a.to}
                size="sm"
                variant="outline"
                onClick={() => doStatus(a.to)}
                loading={setStatus.isPending}
                data-testid={`status-to-${a.to}`}
              >
                {a.label}
              </Button>
            ))}
            {level !== "category" ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowMerge(true)}
                data-testid="open-merge"
              >
                合并
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="danger"
              onClick={() => setConfirmArchive(true)}
              data-testid="archive-node"
            >
              归档
            </Button>
          </div>
        ) : node.status === "archived" ? (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => restore.mutate({ level, id: node.id })}
            loading={restore.isPending}
            data-testid="restore-node"
          >
            恢复
          </Button>
        ) : null}
      </div>

      {readOnly ? (
        <div
          role="status"
          data-testid="readonly-banner"
          className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
        >
          {node.status === "archived"
            ? "该节点已归档，为只读状态。恢复后可继续编辑。"
            : "该节点已合并到其他目标，为只读终态。"}
        </div>
      ) : null}

      {editing ? (
        <div className="space-y-2 rounded border border-gray-200 bg-gray-50 p-3" data-testid="rename-form">
          <TextInput
            label="中文名称（必填）"
            value={nameZh}
            onChange={(e) => setNameZh(e.target.value)}
            maxLength={255}
            data-testid="rename-zh"
          />
          <TextInput
            label="英文名称（可选）"
            value={nameEn}
            onChange={(e) => setNameEn(e.target.value)}
            maxLength={255}
            data-testid="rename-en"
          />
          {level === "family" ? (
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                归属分类（激活产品的前置条件）
              </label>
              <select
                value={categorySel}
                onChange={(e) => setCategorySel(e.target.value)}
                className="w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm"
                data-testid="rename-category"
              >
                <option value="">未归属</option>
                {categories
                  .filter((c) => c.status !== "archived" && c.status !== "merged")
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name_zh}
                      {c.status === "active" ? "" : c.status === "draft" ? "（草稿，须先启用）" : "（已暂停）"}
                    </option>
                  ))}
              </select>
              <p className="mt-1 text-[11px] text-gray-400">
                完整度检查中的「归属分类」「上级已启用」由此决定：产品须归属一个
                <span className="font-medium">已启用</span>的分类才能通过。没有合适的分类时，
                可在左侧目录树的分类层新建并启用。
              </p>
            </div>
          ) : null}
          <p className="text-[11px] text-gray-400">更名不改变编码与既有关联。</p>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              取消
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={saveRename}
              disabled={!nameZh.trim()}
              loading={savingRename}
              data-testid="save-rename"
            >
              保存
            </Button>
          </div>
        </div>
      ) : null}

      <CatalogError error={updateError} />

      {/* Tab 导航：基本信息 / 产品属性 / 参考图库 / 完整度 / 入驻审核 / 易混淆 / 变更历史。
          仅 family/variant/sku 显示 basic 之外的 Tab；治理 Tab 惰性挂载（切到才请求）。 */}
      {hasAssetTabs ? (
        <div
          className="flex flex-wrap gap-2 border-b border-gray-200 text-sm"
          role="tablist"
          data-testid="detail-tabs"
        >
          {([
            { key: "basic", label: "基本信息" },
            {
              key: "attributes",
              label: profile ? `产品属性 (${profile.value_count}/${profile.definition_count})` : "产品属性",
            },
            {
              key: "references",
              label: profile ? `参考图库 (${profile.reference_total})` : "参考图库",
            },
            { key: "readiness", label: "完整度" },
            { key: "onboarding", label: "入驻审核" },
            { key: "confusions", label: "易混淆" },
            { key: "history", label: "变更历史" },
          ] as { key: DetailTab; label: string }[]).map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              data-testid={`detail-tab-${t.key}`}
              className={cn(
                "-mb-px border-b-2 px-3 py-1.5 font-medium",
                tab === t.key
                  ? "border-brand text-brand"
                  : "border-transparent text-gray-500 hover:text-gray-800",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      ) : null}

      {tab === "basic" || !hasAssetTabs ? (
        <div data-testid="detail-tabpanel-basic" className="space-y-4">
          <div className={hasAssetTabs ? "" : "border-t border-gray-100 pt-3"}>
            <AliasManager level={level} targetId={node.id} readOnly={readOnly} />
          </div>

          <div className="border-t border-gray-100 pt-3">
            <ChildList level={level} node={node} onSelect={onSelect} />
          </div>
        </div>
      ) : null}

      {hasAssetTabs && tab === "attributes" ? (
        <div data-testid="detail-tabpanel-attributes">
          <AttributesTab
            level={attrLevel}
            targetId={node.id}
            categoryId={categoryId}
            readOnly={readOnly}
          />
        </div>
      ) : null}

      {hasAssetTabs && tab === "references" ? (
        <div data-testid="detail-tabpanel-references">
          <ReferenceGallery level={attrLevel} targetId={node.id} readOnly={readOnly} />
        </div>
      ) : null}

      {hasAssetTabs && tab === "readiness" ? (
        <div data-testid="detail-tabpanel-readiness">
          <ReadinessPanel
            level={attrLevel}
            targetId={node.id}
            categoryId={categoryId}
            readOnly={readOnly}
          />
        </div>
      ) : null}

      {hasAssetTabs && tab === "onboarding" ? (
        <div data-testid="detail-tabpanel-onboarding">
          <OnboardingPanel level={attrLevel} targetId={node.id} readOnly={readOnly} />
        </div>
      ) : null}

      {hasAssetTabs && tab === "confusions" ? (
        <div data-testid="detail-tabpanel-confusions">
          <ConfusionsPanel
            level={attrLevel}
            targetId={node.id}
            // 同层级候选约束：family 层用自身 id；variant/sku 用所属 family
            familyId={level === "family" ? node.id : (node.family_id ?? null)}
            readOnly={readOnly}
            onSelect={onSelect}
          />
        </div>
      ) : null}

      {hasAssetTabs && tab === "history" ? (
        <div data-testid="detail-tabpanel-history">
          <HistoryPanel level={level} targetId={node.id} />
        </div>
      ) : null}

      {level !== "category" ? (
        <MergeDialog
          open={showMerge}
          onClose={() => setShowMerge(false)}
          level={level}
          sourceId={node.id}
          sourceName={node.name_zh}
          familyId={familyId}
        />
      ) : null}

      <ConfirmDialog
        open={confirmArchive}
        title={`归档${levelLabel(level)}`}
        message={`确认归档「${node.name_zh}」？归档后默认从列表隐藏，可随时恢复；不会删除任何历史关联。`}
        confirmLabel="确认归档"
        loading={archive.isPending}
        onConfirm={() =>
          archive.mutate(
            { level, id: node.id },
            { onSuccess: () => setConfirmArchive(false) },
          )
        }
        onClose={() => setConfirmArchive(false)}
      />
    </div>
  );
}

// 子级列表：category→families / family→variants+直属skus / variant→skus / sku→无
function ChildList({
  level,
  node,
  onSelect,
}: {
  level: SelectedNode["level"];
  node: NodeCommon;
  onSelect: (n: SelectedNode) => void;
}) {
  const famQ = useFamilies({ category_id: node.id, limit: 500 }, level === "category");
  const varQ = useVariants({ family_id: node.id, limit: 500 }, level === "family");
  const skuByFamilyQ = useSkus({ family_id: node.id, limit: 500 }, level === "family");
  const skuByVariantQ = useSkus({ variant_id: node.id, limit: 500 }, level === "variant");

  if (level === "sku") {
    return <p className="text-xs text-gray-400" data-testid="child-leaf">SKU 为最末层级，无下级。</p>;
  }

  let title = "";
  let rows: { level: SelectedNode["level"]; id: number; name: string; status: CatalogStatus }[] = [];
  let loading = false;

  if (level === "category") {
    title = "产品";
    loading = famQ.isLoading;
    rows = (famQ.data?.items ?? []).map((f: Family) => ({
      level: "family" as const,
      id: f.id,
      name: f.name_zh,
      status: f.status,
    }));
  } else if (level === "family") {
    title = "型号 / SKU";
    loading = varQ.isLoading || skuByFamilyQ.isLoading;
    rows = [
      ...(varQ.data?.items ?? []).map((v: Variant) => ({
        level: "variant" as const,
        id: v.id,
        name: v.name_zh,
        status: v.status,
      })),
      ...(skuByFamilyQ.data?.items ?? [])
        .filter((s: Sku) => s.variant_id == null)
        .map((s: Sku) => ({
          level: "sku" as const,
          id: s.id,
          name: s.name_zh,
          status: s.status,
        })),
    ];
  } else {
    title = "SKU";
    loading = skuByVariantQ.isLoading;
    rows = (skuByVariantQ.data?.items ?? []).map((s: Sku) => ({
      level: "sku" as const,
      id: s.id,
      name: s.name_zh,
      status: s.status,
    }));
  }

  return (
    <div className="space-y-1.5" data-testid="child-list">
      <h4 className="text-xs font-medium text-gray-600">下级{title}</h4>
      {loading ? (
        <p className="text-xs text-gray-400">加载中…</p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-gray-400" data-testid="child-empty">
          暂无下级
        </p>
      ) : (
        <ul className="space-y-1">
          {rows.map((r) => (
            <li key={`${r.level}-${r.id}`}>
              <button
                type="button"
                onClick={() => onSelect({ level: r.level, id: r.id })}
                data-testid={`child-${r.level}-${r.id}`}
                className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-sm text-gray-700 hover:bg-gray-50"
              >
                <span className="shrink-0 rounded bg-gray-100 px-1 text-[10px] text-gray-500">
                  {levelLabel(r.level)}
                </span>
                <span className="truncate">{r.name}</span>
                {r.status !== "active" ? (
                  <CatalogStatusBadge status={r.status} />
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
