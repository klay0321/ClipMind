"use client";

import { useState } from "react";

import { Button, Drawer, TextInput } from "@/components/ui";
import {
  useCategories,
  useCreateCatalogAlias,
  useCreateCategory,
  useCreateFamily,
  useCreateSku,
  useCreateVariant,
  useSetFamilyStatus,
} from "@/lib/hooks";
import type { Family, Sku, Variant } from "@/lib/types";

import { CatalogError, CatalogFutureNotice } from "./widgets";

// 分步新建向导（Drawer）：
//   1 选择/创建 Category（可跳过分类，family 允许 category_id 为空）
//   2 创建 Family（必填 name_zh）
//   3 可选 Variant
//   4 可选 SKU
//   5 可选给 Family 添加别名
//   6 保存后为 Draft；可一键启用(active)。
// 全过程不硬编码任何产品名——分类下拉全部来自 /product-categories。

type Step = 1 | 2 | 3 | 4 | 5;

export function CreateWizard({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  // 创建出的 family 完成后回调（父级可选中它）
  onCreated?: (familyId: number) => void;
}) {
  const [step, setStep] = useState<Step>(1);

  // 分类：选择已有或新建
  const [categoryMode, setCategoryMode] = useState<"existing" | "new" | "none">("none");
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [newCategoryName, setNewCategoryName] = useState("");

  const [familyName, setFamilyName] = useState("");
  const [family, setFamily] = useState<Family | null>(null);

  const [variantName, setVariantName] = useState("");
  const [variant, setVariant] = useState<Variant | null>(null);

  const [skuName, setSkuName] = useState("");
  const [skuCode, setSkuCode] = useState("");
  const [sku, setSku] = useState<Sku | null>(null);

  const [aliasValue, setAliasValue] = useState("");

  const categoriesQ = useCategories({ include_archived: false, limit: 500 });
  const createCategory = useCreateCategory();
  const createFamily = useCreateFamily();
  const createVariant = useCreateVariant();
  const createSku = useCreateSku();
  const createAlias = useCreateCatalogAlias();
  const setFamilyStatus = useSetFamilyStatus();

  const reset = () => {
    setStep(1);
    setCategoryMode("none");
    setCategoryId(null);
    setNewCategoryName("");
    setFamilyName("");
    setFamily(null);
    setVariantName("");
    setVariant(null);
    setSkuName("");
    setSkuCode("");
    setSku(null);
    setAliasValue("");
  };

  const close = () => {
    reset();
    onClose();
  };

  // Step1 → Step2：如选「新建分类」，先建分类拿 id。
  const goToFamily = () => {
    if (categoryMode === "new") {
      const name = newCategoryName.trim();
      if (!name) return;
      createCategory.mutate(
        { name_zh: name },
        {
          onSuccess: (cat) => {
            setCategoryId(cat.id);
            setStep(2);
          },
        },
      );
    } else {
      setStep(2);
    }
  };

  const submitFamily = () => {
    const name = familyName.trim();
    if (!name) return;
    createFamily.mutate(
      {
        name_zh: name,
        category_id: categoryMode === "none" ? null : categoryId,
      },
      {
        onSuccess: (f) => {
          setFamily(f);
          setStep(3);
        },
      },
    );
  };

  const submitVariant = () => {
    if (!family) return;
    const name = variantName.trim();
    if (!name) {
      setStep(4);
      return;
    }
    createVariant.mutate(
      { family_id: family.id, name_zh: name },
      { onSuccess: (v) => { setVariant(v); setStep(4); } },
    );
  };

  const submitSku = () => {
    if (!family) return;
    const name = skuName.trim();
    if (!name) {
      setStep(5);
      return;
    }
    createSku.mutate(
      {
        family_id: family.id,
        variant_id: variant?.id ?? null,
        name_zh: name,
        sku_code: skuCode.trim() || undefined,
      },
      { onSuccess: (s) => { setSku(s); setStep(5); } },
    );
  };

  const finish = (enable: boolean) => {
    if (!family) return;
    const done = () => {
      onCreated?.(family.id);
      close();
    };
    const afterAlias = () => {
      if (enable) {
        setFamilyStatus.mutate({ id: family.id, status: "active" }, { onSuccess: done });
      } else {
        done();
      }
    };
    const value = aliasValue.trim();
    if (value) {
      createAlias.mutate(
        { target_level: "family", target_id: family.id, alias: value, alias_type: "zh_name" },
        { onSuccess: afterAlias },
      );
    } else {
      afterAlias();
    }
  };

  const categories = categoriesQ.data?.items ?? [];
  const finishing = createAlias.isPending || setFamilyStatus.isPending;

  return (
    <Drawer open={open} onClose={close} title="新建产品" widthClass="max-w-md">
      <div className="space-y-4" data-testid="create-wizard">
        <ol className="flex flex-wrap gap-1.5 text-[11px] text-gray-400">
          {["分类", "产品", "型号", "SKU", "别名/启用"].map((label, i) => (
            <li
              key={label}
              className={`rounded px-1.5 py-0.5 ${
                step === i + 1 ? "bg-brand/10 text-brand-dark" : "bg-gray-50"
              }`}
              aria-current={step === i + 1 ? "step" : undefined}
            >
              {i + 1}. {label}
            </li>
          ))}
        </ol>

        {step === 1 ? (
          <div className="space-y-3" data-testid="wizard-step-category">
            <p className="text-sm text-gray-600">先选择产品所属分类，或新建分类，也可暂不分类。</p>
            <div className="space-y-2 text-sm">
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name="cat-mode"
                  checked={categoryMode === "none"}
                  onChange={() => setCategoryMode("none")}
                  data-testid="cat-mode-none"
                />
                暂不分类
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name="cat-mode"
                  checked={categoryMode === "existing"}
                  onChange={() => setCategoryMode("existing")}
                  data-testid="cat-mode-existing"
                  disabled={categories.length === 0}
                />
                选择已有分类
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name="cat-mode"
                  checked={categoryMode === "new"}
                  onChange={() => setCategoryMode("new")}
                  data-testid="cat-mode-new"
                />
                新建分类
              </label>
            </div>
            {categoryMode === "existing" ? (
              <select
                value={categoryId ?? ""}
                onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : null)}
                aria-label="选择分类"
                data-testid="wizard-category-select"
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none"
              >
                <option value="">请选择分类…</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name_zh}
                  </option>
                ))}
              </select>
            ) : null}
            {categoryMode === "new" ? (
              <TextInput
                label="新分类名称"
                value={newCategoryName}
                onChange={(e) => setNewCategoryName(e.target.value)}
                maxLength={255}
                data-testid="wizard-new-category"
              />
            ) : null}
            <CatalogError error={createCategory.error} />
            <div className="flex justify-end">
              <Button
                variant="primary"
                onClick={goToFamily}
                loading={createCategory.isPending}
                disabled={
                  (categoryMode === "existing" && categoryId == null) ||
                  (categoryMode === "new" && !newCategoryName.trim())
                }
                data-testid="wizard-next-category"
              >
                下一步
              </Button>
            </div>
          </div>
        ) : null}

        {step === 2 ? (
          <div className="space-y-3" data-testid="wizard-step-family">
            <TextInput
              label="产品名称（中文，必填）"
              value={familyName}
              onChange={(e) => setFamilyName(e.target.value)}
              maxLength={255}
              data-testid="wizard-family-name"
            />
            <CatalogError error={createFamily.error} />
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(1)}>
                上一步
              </Button>
              <Button
                variant="primary"
                onClick={submitFamily}
                loading={createFamily.isPending}
                disabled={!familyName.trim()}
                data-testid="wizard-next-family"
              >
                创建并继续
              </Button>
            </div>
          </div>
        ) : null}

        {step === 3 ? (
          <div className="space-y-3" data-testid="wizard-step-variant">
            <p className="text-xs text-gray-500">可选：为「{family?.name_zh}」添加一个型号，或跳过。</p>
            <TextInput
              label="型号名称（可选）"
              value={variantName}
              onChange={(e) => setVariantName(e.target.value)}
              maxLength={255}
              data-testid="wizard-variant-name"
            />
            <CatalogError error={createVariant.error} />
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(4)} data-testid="wizard-skip-variant">
                跳过
              </Button>
              <Button
                variant="primary"
                onClick={submitVariant}
                loading={createVariant.isPending}
                data-testid="wizard-next-variant"
              >
                {variantName.trim() ? "创建并继续" : "下一步"}
              </Button>
            </div>
          </div>
        ) : null}

        {step === 4 ? (
          <div className="space-y-3" data-testid="wizard-step-sku">
            <p className="text-xs text-gray-500">
              可选：为「{family?.name_zh}」{variant ? `/${variant.name_zh}` : ""}添加一个 SKU，或跳过。
            </p>
            <TextInput
              label="SKU 名称（可选）"
              value={skuName}
              onChange={(e) => setSkuName(e.target.value)}
              maxLength={255}
              data-testid="wizard-sku-name"
            />
            <TextInput
              label="SKU 编码（可选）"
              value={skuCode}
              onChange={(e) => setSkuCode(e.target.value)}
              maxLength={128}
              data-testid="wizard-sku-code"
            />
            <CatalogError error={createSku.error} />
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(5)} data-testid="wizard-skip-sku">
                跳过
              </Button>
              <Button
                variant="primary"
                onClick={submitSku}
                loading={createSku.isPending}
                data-testid="wizard-next-sku"
              >
                {skuName.trim() ? "创建并继续" : "下一步"}
              </Button>
            </div>
          </div>
        ) : null}

        {step === 5 ? (
          <div className="space-y-3" data-testid="wizard-step-finish">
            <TextInput
              label="产品别名（可选）"
              value={aliasValue}
              onChange={(e) => setAliasValue(e.target.value)}
              maxLength={255}
              hint="别名用于检索与匹配时的产品识别线索"
              data-testid="wizard-alias"
            />
            <CatalogFutureNotice />
            <CatalogError error={createAlias.error} />
            <CatalogError error={setFamilyStatus.error} />
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                variant="secondary"
                onClick={() => finish(false)}
                loading={finishing}
                data-testid="wizard-save-draft"
              >
                保存为草稿
              </Button>
              <Button
                variant="primary"
                onClick={() => finish(true)}
                loading={finishing}
                data-testid="wizard-save-active"
              >
                保存并启用
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </Drawer>
  );
}
