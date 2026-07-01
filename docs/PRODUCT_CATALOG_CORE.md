# 通用产品目录核心（PR-A1）操作说明

> ClipMind 面向跨境电商公司**全部现有与未来产品**。本 PR（PR-A1）实现**通用产品目录核心**：
> 动态层级 `Category → Family → Variant → SKU` + 别名 + 生命周期 + 合并重定向。
> **新增任意产品只需插入数据（经 API/UI），无需改代码、加枚举、改 SQL CHECK、建迁移、改页面。**
> 规格见《通用产品目录》`docs/requirements/GENERIC_PRODUCT_CATALOG_SPEC.md`；PR 边界见 `docs/roadmap/ECOMMERCE_ASSET_INTELLIGENCE_ROADMAP.md`。

## 1. 架构（方案 B：与既有扁平 `product` 并存）
现有 `product` 是**扁平业务产品**（混合 family/variant/sku 语义），被 Asset / Shot 审核 / Script / Project 等引用。
PR-A1 **不改动** `product` 及其引用与 `/api/products` API，而是**新增独立的通用目录表**：
`product_category` / `product_family` / `product_variant` / `product_sku` / `product_catalog_alias`。
`product_family.legacy_product_id`（可空软引用 `product`）为**兼容桥**（空初始，运营/后续 PR 按需映射，绝不自动猜层级）。

## 2. 层级与可选性（决策 4）
- **Family 是核心产品实体**；**Category 建议必填**（允许 draft 暂缺）；**Variant / SKU 可选**。
- 业务对象至少挂到 Family，可按需细化到 Variant / SKU（可变粒度）。
- SKU 可直接属于 Family，或属于**同一 Family** 的 Variant（禁跨 Family）。
- 稳定身份：`id`（PK）+ `code`（稳定业务码，缺省由归一化名自动生成并保证唯一）；**更名只改 `name_*`，不改 id/code**。

## 3. 生命周期（`catalog_status`）
`draft → active → paused → archived`（可 `restore` 回 active）；`merged` 为合并终态。
- **归档 / 合并均非物理删除**，历史关系保留；`archived` 默认不出现在 active 列表，`include_archived=true` 可见。
- **合并**：`POST .../merge {target_id}` → 源节点 `status=merged`、`merged_into_id=目标`；禁自合并、禁环、禁跨不兼容层级（跨 family 的 variant/sku 合并被拒）。

## 4. API（前缀 `/api`，与 `/api/products` 并存）
- Category：`GET/POST /product-categories`，`GET/PATCH /product-categories/{id}`，`POST .../archive|restore`
- Family：`GET/POST /product-families`，`GET/PATCH /{id}`，`POST .../archive|restore|merge|status`
- Variant：`GET/POST /product-variants`，`GET/PATCH /{id}`，`POST .../archive|restore|merge`
- SKU：`GET/POST /product-skus`，`GET/PATCH /{id}`，`POST .../archive|restore|merge`
- Alias：`GET/POST /product-aliases`，`PATCH/DELETE /product-aliases/{id}`（单表多目标，同目标 `normalized_alias` 唯一，大小写/空白无关，409 冲突）
- 目录：`GET /product-catalog/tree`，`GET /product-catalog/search?q=`，`GET /product-catalog/resolve?value=`
  - `resolve` 支持 中文名 / 英文名 / code / sku_code / 别名 / merge 重定向；**无精确命中返回 null（绝不强制猜测）**。
- 错误：`404` 不存在、`422` 校验、`409` 唯一/环冲突。分页 `limit/offset`；状态筛选；`category_id`/`family_id`/`variant_id` 层级筛选。

## 5. 迁移与既有数据保护
- 迁移 `0013_generic_product_catalog`：**一次性建通用基础 Schema（正式 Alembic）**；此后新增产品/别名只是插入数据、**免迁移**。
- **非破坏**：不删表/列/FK/数据；不改历史迁移 0001–0012；不写入 seed 产品；不猜层级。
- 已验证：隔离库 upgrade→0013 / downgrade→0012 / re-upgrade；既有 `product` 行与 FK 全程保留；`alembic check` 无 diff。

## 6. 本 PR **不做**（留 PR-A2 / 后续）
动态产品属性、产品参考图与角度、混淆组、Catalog Revision、完整入驻工作流、自动视觉识别、使用血缘/次数、检索排序、分镜算法。
前端预留"参考图与自动产品识别将在后续版本提供"，**不伪造**"AI 已识别"。

## 7. 通用性护栏
`apps/api/tests/test_catalog_generalization_guard.py` 静态检查：生产代码零 seed 产品名硬编码、生产不 import discovery、`CatalogStatus` 为生命周期枚举（非产品名）、产品层级为动态表（无产品名 Enum/CHECK）。
