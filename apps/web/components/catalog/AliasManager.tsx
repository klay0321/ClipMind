"use client";

import { useState } from "react";

import { Button, Chip } from "@/components/ui";
import {
  useCatalogAliases,
  useCreateCatalogAlias,
  useDeleteCatalogAlias,
} from "@/lib/hooks";
import { CATALOG_ALIAS_TYPES, type CatalogAliasType, type CatalogLevel } from "@/lib/types";

import { CatalogError } from "./widgets";

// 别名类型标签（受控枚举常量，非产品值）
const ALIAS_TYPE_LABELS: Record<CatalogAliasType, string> = {
  zh_name: "中文别名",
  en_name: "英文别名",
  short_name: "运营简称",
  folder_alias: "文件夹别名",
  historical_name: "历史名称",
  sku_alias: "SKU 别名",
};

export function AliasManager({
  level,
  targetId,
  readOnly = false,
}: {
  level: CatalogLevel;
  targetId: number;
  readOnly?: boolean;
}) {
  const aliasesQ = useCatalogAliases(level, targetId);
  const create = useCreateCatalogAlias();
  const del = useDeleteCatalogAlias(level, targetId);

  const [alias, setAlias] = useState("");
  const [aliasType, setAliasType] = useState<CatalogAliasType>("zh_name");
  const [adding, setAdding] = useState(false);

  const aliases = aliasesQ.data ?? [];

  const submit = () => {
    const value = alias.trim();
    if (!value) return;
    create.mutate(
      { target_level: level, target_id: targetId, alias: value, alias_type: aliasType },
      {
        onSuccess: () => {
          setAlias("");
          setAdding(false);
        },
      },
    );
  };

  return (
    <div className="space-y-2" data-testid="alias-manager">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium text-gray-600">别名</h4>
        {!readOnly ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setAdding((v) => !v)}
            data-testid="toggle-add-alias"
          >
            {adding ? "收起" : "+ 添加别名"}
          </Button>
        ) : null}
      </div>

      {aliasesQ.isLoading ? (
        <p className="text-xs text-gray-400">加载别名中…</p>
      ) : aliases.length === 0 ? (
        <p className="text-xs text-gray-400" data-testid="alias-empty">
          暂无别名
        </p>
      ) : (
        <ul className="space-y-1" data-testid="alias-list">
          {aliases.map((a) => (
            <li
              key={a.id}
              className="flex items-center justify-between gap-2 rounded border border-gray-100 bg-gray-50 px-2 py-1"
              data-testid={`alias-item-${a.id}`}
            >
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="truncate text-sm text-gray-700">{a.alias}</span>
                <Chip tone="neutral">
                  {ALIAS_TYPE_LABELS[a.alias_type as CatalogAliasType] ?? a.alias_type}
                </Chip>
                {a.is_primary ? <Chip tone="brand">主</Chip> : null}
              </span>
              {!readOnly ? (
                <button
                  type="button"
                  onClick={() => del.mutate(a.id)}
                  disabled={del.isPending}
                  data-testid={`delete-alias-${a.id}`}
                  className="shrink-0 text-xs text-red-500 hover:text-red-700 disabled:opacity-50"
                >
                  删除
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {adding && !readOnly ? (
        <div className="space-y-2 rounded border border-gray-200 bg-white p-2">
          <input
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            placeholder="输入别名"
            aria-label="别名"
            data-testid="alias-input"
            maxLength={255}
            className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-brand focus:outline-none"
          />
          <select
            value={aliasType}
            onChange={(e) => setAliasType(e.target.value as CatalogAliasType)}
            aria-label="别名类型"
            data-testid="alias-type"
            className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-brand focus:outline-none"
          >
            {CATALOG_ALIAS_TYPES.map((t) => (
              <option key={t} value={t}>
                {ALIAS_TYPE_LABELS[t]}
              </option>
            ))}
          </select>
          <CatalogError error={create.error} />
          <div className="flex justify-end">
            <Button
              size="sm"
              variant="primary"
              onClick={submit}
              disabled={!alias.trim() || create.isPending}
              loading={create.isPending}
              data-testid="submit-alias"
            >
              添加
            </Button>
          </div>
        </div>
      ) : null}
      <CatalogError error={del.error} />
    </div>
  );
}
