import { vi } from "vitest";

import type {
  CatalogAlias,
  CatalogTreeNode,
  Category,
  Family,
  Sku,
  Variant,
} from "@/lib/types";

// TanStack Query 结果桩（与既有测试一致的形状）
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function query(overrides: Record<string, any> = {}): any {
  return {
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    isFetching: false,
    refetch: vi.fn(() => Promise.resolve()),
    ...overrides,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function mutation(overrides: Record<string, any> = {}): any {
  return { mutate: vi.fn(), isPending: false, error: null, ...overrides };
}

export function makeCategory(o: Partial<Category> = {}): Category {
  return {
    id: 1,
    code: "cat-1",
    name_zh: "示例分类",
    name_en: null,
    description: null,
    status: "active",
    sort_order: 0,
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:00:00Z",
    archived_at: null,
    ...o,
  };
}

export function makeFamily(o: Partial<Family> = {}): Family {
  return {
    id: 10,
    code: "fam-10",
    category_id: 1,
    name_zh: "示例产品",
    name_en: null,
    description: null,
    status: "active",
    merged_into_id: null,
    legacy_product_id: null,
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:00:00Z",
    archived_at: null,
    ...o,
  };
}

export function makeVariant(o: Partial<Variant> = {}): Variant {
  return {
    id: 20,
    code: "var-20",
    family_id: 10,
    name_zh: "示例型号",
    name_en: null,
    description: null,
    status: "active",
    merged_into_id: null,
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:00:00Z",
    archived_at: null,
    ...o,
  };
}

export function makeSku(o: Partial<Sku> = {}): Sku {
  return {
    id: 30,
    code: "sku-30",
    family_id: 10,
    variant_id: null,
    sku_code: null,
    name_zh: "示例 SKU",
    name_en: null,
    status: "active",
    merged_into_id: null,
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:00:00Z",
    archived_at: null,
    ...o,
  };
}

export function makeAlias(o: Partial<CatalogAlias> = {}): CatalogAlias {
  return {
    id: 100,
    category_id: null,
    family_id: 10,
    variant_id: null,
    sku_id: null,
    alias: "示例别名",
    normalized_alias: "示例别名",
    language: null,
    alias_type: "zh_name",
    is_primary: false,
    ...o,
  };
}

// 一棵最小完整树：分类 → 产品 → 型号 → SKU
export function makeTree(): CatalogTreeNode[] {
  return [
    {
      level: "category",
      id: 1,
      code: "cat-1",
      name_zh: "示例分类",
      name_en: null,
      status: "active",
      children: [
        {
          level: "family",
          id: 10,
          code: "fam-10",
          name_zh: "示例产品",
          name_en: null,
          status: "active",
          children: [
            {
              level: "variant",
              id: 20,
              code: "var-20",
              name_zh: "示例型号",
              name_en: null,
              status: "draft",
              children: [
                {
                  level: "sku",
                  id: 30,
                  code: "sku-30",
                  name_zh: "示例 SKU",
                  name_en: null,
                  status: "active",
                  children: [],
                },
              ],
            },
          ],
        },
      ],
    },
  ];
}
