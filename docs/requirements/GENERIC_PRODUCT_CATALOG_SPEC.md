# 通用产品目录规格（GENERIC_PRODUCT_CATALOG_SPEC）

> 阶段：Phase 0.5 通用产品系统设计（规格冻结）。本文件冻结 ClipMind 作为**通用产品视频素材管理系统**的
> **动态产品目录（Product Catalog）**：通用产品层级、规格对象、动态属性体系、别名/多语言/参考图/识别特征/易混淆、
> 启用·停用·合并·更名的历史保留，以及 `ProductCatalogRevision` 版本化。
>
> 配套文档（术语、对象模型、状态机、证据等级须与本文件完全一致）：
> - 业务需求：`ECOMMERCE_MEDIA_ASSET_REQUIREMENTS.md`（下称《业务需求》）
> - 产品身份与使用血缘：`PRODUCT_IDENTITY_AND_USAGE_LINEAGE_SPEC.md`（下称《身份血缘》）
> - 使用感知检索：`USAGE_AWARE_RETRIEVAL_SPEC.md`（下称《使用感知检索》）
> - 结构化分镜匹配：`STORYBOARD_MATCHING_SPEC.md`（下称《结构化分镜匹配》）
> - 现状差距分析：`CURRENT_SYSTEM_GAP_ANALYSIS.md`（下称《现状差距》）
> - 评测计划：`../evaluation/COMPANY_MEDIA_BENCHMARK_PLAN.md`（下称《评测计划》）
> - 路线图：`../roadmap/ECOMMERCE_ASSET_INTELLIGENCE_ROADMAP.md`（下称《路线图》）
>
> **本阶段只写规格，不创建任何 Alembic 迁移、不改模型、不接模型、不下载模型权重、不改搜索排序、不开始任何落地 PR。**
> 表名、字段、枚举均为**设计草案**，落地 PR（《路线图》PR-A1/PR-A2 起）再评审建库。
>
> 标注约定（继承上游规格）：**[复用]** 现有模型可直接承载，不重写 / **[扩展]** 现有上加列、加关系或加配置 / **[新增]** 本批新建。
> 证据分层标签：`事实 / 规则推断 / AI 推断 / 人工确认`——UI 不伪造"已识别 / 已匹配 / 使用次数"。

---

## 0. 本文件的定位与最高原则

### 0.1 系统管理的是"动态产品目录"，不是文件夹名称列表

ClipMind 面向一家跨境电商公司，必须能管理公司**当前与未来任意**产品系列 / 变体 / SKU。
本文件定义的核心是一个**动态产品目录（Product Catalog）**：它是**运行期数据**，由运营在系统内动态创建与维护，
**不是**当前 NAS 文件夹名称的镜像，**不是**写死在代码里的产品清单。

**新增任意产品都绝不需要**（贯穿《业务需求》§8 通用化原则）：

- 修改代码（Python / TypeScript）
- 增加数据库枚举（Python `StrEnum` / SQL `CHECK`）
- 创建数据库迁移
- 重新设计页面 / 新增 UI 固定选项
- 修改搜索规则 / 排序算法特例
- 修改 Prompt 固定产品列表
- 修改文件夹判断逻辑

> 推论：本文件定义的所有"产品种类 / 层级节点 / 属性键 / 角度 / 状态"中，**唯有"产品种类"和"属性键"是运行期数据**
> （动态创建、可增删改）；而层级**结构**、属性**值类型集**、参考图角度集、入驻状态集、识别结果态集、命名约定本身是
> 系统能力，可随版本演进，但**不随单个产品变化**。这条边界是"既通用又稳定"的关键。

### 0.2 当前 4 产品 = 仅 seed / 评测数据，绝不进代码逻辑

当前已知 4 产品（恶魔之眼软屏、恶魔之眼硬屏、车换挡握把、小键盘；其中恶魔之眼软 / 硬屏为第一组高相似混淆案例）
与盘点得到的 6 候选（`family×variant` 展开，见《业务需求》§0.1）**只能**出现在：示例 / 本地评测说明 / 混淆案例 /
产品识别种子数据。它们**绝不**出现在：Python / TypeScript 枚举、SQL `CHECK`、迁移里的固定产品、搜索规则硬编码、
Prompt 固定产品列表、UI 固定选项、文件夹判断逻辑、排序特例。

当前素材库盘点结果（190 文件 / 102 视频 / 81 参考图 / 6 候选）= **第一批 seed 样本**，
**不代表公司完整产品目录**；本文件定义的数据模型 / API / UI / 识别 / 检索**不得依赖当前产品的数量、名称、目录结构或差异**。
seed 的唯一合法用途见《业务需求》§8.3 与本文件 §11。

### 0.3 复用现状基线（PR-03B），扩展而非重写

ClipMind 已实现 PR-03B 产品库：`Product` / `ProductAlias` / `ProductImage` / `AssetProduct`
（出处 `packages/shared/clipmind_shared/models/product.py`），并有 `normalized_name` / `normalized_alias` 标准化匹配。
本文件**复用**这套基线，把**扁平 `Product` 表扩展为 `Category → Family → Variant → SKU` 层级**，
**不重写、不反向改造**已稳定的多对多关联与来源标注。逐项"复用 X / 新增 Y / 扩展 Z"见 §3、§13。

---

## 1. 通用产品层级（canonical：Category → Family → Variant → SKU）

### 1.1 层级定义（全部动态创建、无需迁移）

ClipMind 采用统一的四级产品层级。**每一层都是运行期可动态创建的目录节点**，新增节点不需要任何代码改动或数据库迁移。

```text
ProductCategory（产品类别，动态，如 汽配 / 数码 / 键盘 / 握把 …）
  └── ProductFamily（产品族 / 产品系列，seed 示例 恶魔之眼）
        └── ProductVariant（产品变体，seed 示例 软屏 / 硬屏；十字架档把 / mini 键盘 等待运营确认归并）
              └── ProductSKU（货号，可空）
                    ├── ProductAlias（别名 / 多语言名 / 文件夹别名，可挂任意层级）
                    └── ProductReferenceAsset（参考图，多张，带角度）
```

> **核心实体与可选性（《业务需求》§9 决策 4，已锁定）**：**ProductFamily 是核心产品实体**；
> **ProductCategory 建议必填**；**ProductVariant 与 ProductSKU 可选**。业务对象（素材 / 镜头 / 成片使用）
> **至少挂到 Family 级**，可按需细化到 Variant / SKU。

| 层级 | 含义 | 是否可空 | 动态创建 | 需要迁移 |
|---|---|---|---|---|
| **ProductCategory** | 顶层品类，承载未来不同品类的产品 | **建议必填**（Family 默认归属一个 Category；允许临时无类别待归并） | 是 | 否 |
| **ProductFamily** | 产品族 / 产品系列，**核心产品实体** | **必填**（业务对象至少挂到 Family） | 是 | 否 |
| **ProductVariant** | 族下可区分的版本（外观或规格差异） | **可选**（一个 Family 可无变体；业务对象可直接挂 Family 级） | 是 | 否 |
| **ProductSKU** | 货号 / 最小销售单元 | **可选**（很多产品没有细分 SKU） | 是 | 否 |

> **可变粒度语义**：当一个 Family 无需细分变体、或一个 Variant 无需细分到货号时，业务对象可直接挂到
> **Family 级或 Variant 级**，不强制建 Variant / SKU。识别、检索、分镜匹配的"产品粒度"因此是**可变粒度**
> （Category / Family / Variant / SKU 任一），见《身份血缘》§1.5、《使用感知检索》§7.5、《结构化分镜匹配》§1.1。

> **层级是结构、不是枚举**：四级层级是系统能力（稳定），但每级里**具体有哪些节点是数据**（动态）。
> 新增"无人机"品类、"某新款屏"族、"Pro 版"变体、"SKU-XX"货号，全部是**插入数据行**，
> 不是改枚举、不是写迁移、不是加 UI 选项。

> **建表 vs 加数据（《业务需求》§9 决策 6，已锁定）**：**PR-A1 一次性建立通用基础 Schema 须使用正式 Alembic migration**；
> 此后**新增产品 / 属性是纯数据，免迁移**。两者不得混为"PR-A 不建迁移"。

### 1.2 与现有模型的映射（复用 / 扩展 / 新增）

| 层级 | 现有承载 | 状态 | 设计草案 |
|---|---|---|---|
| ProductCategory | 无独立表 | **[新增]** | 新增 `product_category`（动态创建）；`product_family.category_id` 外键。承载未来不同品类。 |
| ProductFamily | 无独立表（现有 `Product` 扁平） | **[新增]** | 新增 `product_family`；`product.family_id` 外键。族有独立别名 / 混淆组语义（《身份血缘》§1.1 倾向方案 A）。 |
| ProductVariant | 现有 `Product` 行 | **[复用 / 扩展]** | 每个变体 = 一行 `Product`；`Product.model` 承载变体名（如 `软屏`），`family_id` 指向族。 |
| ProductSKU | `Product.sku` | **[复用]** | 已有，可空；运营台账补全。 |
| ProductAlias | `ProductAlias` | **[复用 / 扩展]** | 复用 `normalized_alias`；扩展为可挂 Category / Family / Variant / SKU 任意层级（见 §4）。 |
| ProductReferenceAsset | `ProductImage` | **[复用 / 扩展]** | 复用受控相对路径 `products/{...}/images/`；扩展角度字段（§5）。 |
| 素材↔产品 | `AssetProduct`（多对多） | **[复用]** | 已有 `source` / `confidence` / `match_type` / `active` / `confirmed_by`，关联到 Variant（=`Product`）。 |

> **命名规范化复用**：现有 `normalized_name` / `normalized_alias` 的标准化（大小写 / 空格 / 标点 / 全角半角 / 连字符）
> 直接复用到 Category / Family / Variant / SKU / Alias 的归一化匹配与唯一性判定，不另造一套。
>
> **现有 `ProductStatus`（仅 `active`/`archived`）= [扩展]**：本文件 §8 的 6 态入驻状态是其**超集**，
> 落地 PR 评审如何扩展该枚举或以独立 `onboarding_status` 列承载（草案，不在本阶段冻结）。

---

## 2. 通用化设计约束（落到产品目录的具体红线）

> 本节把《业务需求》§8 的通用化原则**具体落到"新增一个产品时系统会发生什么"**，作为后续所有规格对象设计的验收口径。

| # | 场景 | 系统行为（通用化要求） | 绝不允许 |
|---|---|---|---|
| 1 | 新增一个全新品类的产品 | 运营在 UI 新建 `ProductCategory` + `Family` + `Variant`（+ 可选 SKU）数据行 | 不改代码 / 不加枚举 / 不写迁移 / 不重设计页面 |
| 2 | 同一 Family 下新增 Variant | 插入 `product_variant`（=新 `Product` 行） | 不写变体名硬编码 / 不加排序特例 |
| 3 | 给某 Category 新增一个识别相关属性 | 插入一条 `ProductAttributeDefinition`（§6） | 不加数据库列 / 不写迁移 |
| 4 | 产品改名 / 合并 / 停用 | 通过 §9 + `ProductCatalogRevision` 记录，旧映射保留 | 不丢历史素材关系 / 不重算使用次数为 0 |
| 5 | 识别模型升级后重识别 | 绑定 `model_version` + `catalog_revision` 重跑，**人工确认结果不被自动覆盖** | 不静默覆盖人工确认（《身份血缘》§1.5） |
| 6 | 文件夹名 ≠ 正式产品名 | 文件夹名只作 `ProductAlias`（文件夹别名）候选线索 | 不作判定真值 / 不写文件夹判断逻辑 |
| 7 | 无法识别的产品 | 输出 `unknown_product` / 待确认 | 不在已知产品中强制猜测（《身份血缘》§1.5） |

> **既不"全写死列"、也不"无约束 JSON"**：稳定的业务核心（层级、状态、命名）用结构化列；
> 易变的产品特性用**受 `ProductAttributeDefinition` 约束的动态属性**（§6）。两个极端都禁止——
> 全写死列会让"新增属性必须迁移"，无约束 JSON 会让搜索 / 识别 / 校验无据可依。

---

## 3. 规格对象总览（10 个，本阶段只定义不建库）

> 下表是本文件冻结的 10 个规格对象。**全部为草案表名**，本阶段**不建库**；落地见《路线图》。
> "复用 / 新增 / 扩展" 与《现状差距》§2 新增对象清单一致。

| # | 规格对象（草案表名） | 状态 | 一句话职责 | 详见 |
|---|---|---|---|---|
| 1 | `ProductCategory` | [新增] | 顶层品类节点（动态） | §1 |
| 2 | `ProductFamily` | [新增] | 产品族 / 系列节点（动态，族级别名 / 混淆组语义） | §1、§7 |
| 3 | `ProductVariant` | [复用 `Product` 行 / 扩展] | 族下变体节点（=现有 `Product`，`model`=变体名，`family_id`） | §1 |
| 4 | `ProductSKU` | [复用 `Product.sku`] | 货号（可空） | §1 |
| 5 | `ProductAlias` | [复用 / 扩展] | 别名 / 多语言名 / 文件夹别名（可挂任意层级） | §4 |
| 6 | `ProductReferenceAsset` | [复用 `ProductImage` / 扩展] | 参考图（多张、带角度、受控相对路径） | §5 |
| 7 | `ProductAttributeDefinition` | [新增] | 动态属性**定义**（Category 级，约束值类型 / 可搜 / 识别相关 / 必填 / 版本） | §6 |
| 8 | `ProductAttributeValue` | [新增] | 动态属性**取值**（挂在产品节点上，受定义约束） | §6 |
| 9 | `ProductConfusionPair` | [新增] | 易混淆产品对 / 组（如 软屏↔硬屏），治理混淆识别 | §7 |
| 10 | `ProductCatalogRevision` | [新增] | 产品目录版本化（更名 / 合并 / SKU 迁移 / 模型重识别基线） | §9、§10 |

> **复用映射重申**：1/2/7/8/9/10 为本批 **[新增]**；3/4 直接 **[复用]** 现有 `Product` / `Product.sku`；
> 5/6 在现有 `ProductAlias` / `ProductImage` 上 **[扩展]**。不重写 PR-03B 任何稳定结构。

---

## 4. 别名与多语言名称（`ProductAlias`，复用 + 扩展）

### 4.1 一个产品可有多别名、多语言名

`ProductAlias` 复用现有表（`alias` + `normalized_alias`），**扩展**以支持：

| 字段（草案） | 说明 |
|---|---|
| `target_level` | 别名挂在哪一层：`category` / `family` / `variant` / `sku`（**扩展**：现有仅挂 `Product`=variant 级，需支持族 / 类 / SKU 级别名） |
| `target_id` | 对应层级节点 id |
| `alias` / `normalized_alias` | 别名原文 + 归一化（**复用**现有标准化匹配） |
| `alias_type` | `display_name`（正式名）/ `synonym`（同义别名）/ `folder_alias`（文件夹别名）/ `legacy_name`（更名前旧名） |
| `lang` | 语言标签（如 `zh` / `en` / `ja`），支持**多语言商品名**；缺省视为默认语言 |
| `created_at` | — |

### 4.2 别名规则（通用化与证据分层）

- **文件夹别名（`folder_alias`）只作候选线索，绝不作判定真值**（《业务需求》§8.2 第 18 项、《身份血缘》§1.4）：
  目录名命中 = **规则推断**，仅产生 `needs_human=true` 候选，**绝不只凭目录名最终确认产品身份**。
- **多语言名称**通过多条 `lang` 不同的 `display_name` 别名承载，**不需要为每种语言加列或加迁移**。
- **更名保留旧名**：产品更名时旧名落为 `legacy_name` 别名（不删除），保证旧文件夹 / 旧素材仍能命中历史映射（§9）。
- 别名归一化与唯一性复用现有 `normalized_alias`，跨层级唯一性约束草案：`(target_level, target_id, normalized_alias)` 近似唯一。

---

## 5. 参考图与识别特征（`ProductReferenceAsset`，复用 + 扩展）

### 5.1 多参考图、多角度

`ProductReferenceAsset` 复用现有 `ProductImage`（受控相对路径 `products/{...}/images/`，**绝不写源目录**），**扩展**角度与归属层级：

| 字段（草案） | 说明 |
|---|---|
| `target_level` / `target_id` | 参考图归属层级（通常 `variant` / `sku`，也可挂 `family` 通用图） |
| `image_path` | 受控相对路径（**复用**） |
| `angle` | 参考图角度（canonical 12 角度，见 §5.2） |
| `is_identity_reference` | 是否作为**识别参考**（参与识别特征比对）/ 仅运营展示 |
| `notes` | 角度 / 局部说明（如"关键局部：排线接口"） |

> 一个产品可有**多张参考图、多角度**；同一 SKU 外观不同的多角度图归于同一 SKU；包装图与裸机图按角度区分
> （《业务需求》§8.2 第 5/6/7/8 项）。**参考图是 FFmpeg / 上传的派生或外部图，绝不是生成式产物。**

### 5.2 canonical 参考图角度（12）

> 角度集是**系统能力**（稳定、有限枚举语义），新增**产品**不需要改它；只有当业务确需新角度类别时才版本化扩展（§10）。

`正面 / 背面 / 侧面 / 顶部 / 底部 / 接口 / 包装 / 安装前 / 安装后 / 点亮状态 / 关键局部 / 其他`

### 5.3 识别特征（运营提供，混淆变体尤其重要）

- 识别特征 = **参考图（`is_identity_reference=true`）** + **`identity_relevant` 动态属性**（§6）+ 运营文字差异说明。
- 对易混淆变体（如软屏 vs 硬屏），运营需提供可见识别特征（屏体柔性 / 边缘包边 / 排线方式 / 安装方式 / 厚度背板 /
  外包装丝印 / SKU 货号差异，见《身份血缘》§1.3），写入 `identity_relevant` 属性与"关键局部"参考图。
- **本阶段不对任何混淆变体做自动断言**：识别特征只供后续 PR 的识别 Provider 比对，**AI 推断结果默认 `needs_human`**
  （《身份血缘》§1.2、《路线图》PR-F）。

---

## 6. 动态属性体系（`ProductAttributeDefinition` + `ProductAttributeValue`）

### 6.1 设计立场：稳定核心 + 受约束的可扩展属性（反对两个极端）

ClipMind 既**不把所有产品特性写死成数据库列**（否则新增属性必须迁移，违反通用化），
也**不用无约束的自由 JSON**（否则搜索 / 识别 / 校验无据可依、口径漂移）。折中方案：

- **稳定核心**用结构化列承载：层级（Category/Family/Variant/SKU）、入驻状态、别名、参考图、混淆组、版本——这些**不随产品种类变化**。
- **可扩展属性**用**受 `ProductAttributeDefinition` 约束**的键值承载：新增属性 = **插入一条定义**（不迁移、不改代码），
  取值落 `ProductAttributeValue`，并由定义约束**值类型 / 是否必填 / 是否可搜 / 是否参与识别 / 版本**。

### 6.2 `ProductAttributeDefinition`（属性定义，Category 级）

| 字段（草案） | 类型 | 说明 |
|---|---|---|
| `category_id` | FK `product_category` | **属性按 Category 定义**：不同品类可定义不同属性集 |
| `key` | str | 属性键（如 `screen_type` / `connector` / `dimension_mm`），Category 内唯一 |
| `display_name` | str | 展示名（可多语言，落 §4 别名或独立列，落地评审） |
| `value_type` | enum（7 种，见 §6.3） | 取值类型约束 |
| `allowed_values` | JSONB? | `enum` / `multi_enum` 的合法取值集（动态，免迁移） |
| `required` | bool | 是否必填（入驻校验用，见 §8） |
| `searchable` | bool | 是否**参与搜索**（《使用感知检索》§7.5 查询解析可入查询） |
| `identity_relevant` | bool | 是否**参与识别**（识别特征，混淆治理参与） |
| `version` | int | 属性定义版本（属性语义变化保留版本，§10） |
| `status` | enum | `active` / `deprecated`（停用属性不删历史取值） |

> **关键标注（强约束）**：每条属性定义必须明确标注 `identity_relevant`（参与识别）/ `searchable`（参与搜索）/
> 三者皆否=**仅运营信息**。这三类是后续识别（《身份血缘》）与检索（《使用感知检索》）的入口契约，**绝不**把运营信息
> 当识别依据，也**绝不**让未标 `searchable` 的属性悄悄进搜索。

### 6.3 canonical 值类型（7）

`value_type ∈ { text, number, boolean, enum, multi_enum, measurement, date }`

| 值类型 | 含义 | 取值校验 |
|---|---|---|
| `text` | 自由文本 | 长度上限（落地评审） |
| `number` | 数值 | 数值范围（可选） |
| `boolean` | 真 / 假 | — |
| `enum` | 单选 | 必须 ∈ `allowed_values` |
| `multi_enum` | 多选 | 子集 ⊆ `allowed_values` |
| `measurement` | 带单位量纲（如 `12.5 mm`） | 数值 + 单位（单位集落 `allowed_values` 或定义扩展） |
| `date` | 日期 | ISO 日期 |

> 值类型集是**系统能力**（稳定、有限），新增**属性**只选其一即可，不需扩值类型；
> 确需新增值类型才版本化扩展（§10），与"新增产品免迁移"互不冲突。

### 6.4 `ProductAttributeValue`（属性取值）

| 字段（草案） | 说明 |
|---|---|
| `definition_id` | FK `product_attribute_definition` |
| `target_level` / `target_id` | 取值挂在哪个产品节点（通常 Variant / SKU，也可 Family 级默认值） |
| `value_json` | JSONB，按定义 `value_type` 解释（受 `allowed_values` 约束） |
| `evidence_level` | `事实 / 规则推断 / AI 推断 / 人工确认`：属性来源分层 |
| `definition_version` | 写入时的定义版本（属性语义演进可追溯，§10） |
| `created_at` / `updated_at` | — |

> **证据分层落到属性**：AI 推断得到的属性值（后续识别 PR）默认 `needs_human`，不自动覆盖人工确认值
> （与《身份血缘》§1.5"人工确认结果不被自动覆盖"一致）。

### 6.5 不同 Category 不同属性、属性变化保留版本

- 数码类可定义 `screen_type` / `connector`；汽配类可定义 `mount_type`；键盘类可定义 `key_count`——
  **互不影响、各自定义，新增属性都不需要迁移**。
- 属性**改名 / 改值类型 / 改取值集 / 改 identity·searchable 标注**=**版本递增**（`version`），旧取值保留旧 `definition_version`，
  保证历史属性可追溯、可重算（§10）。

---

## 7. 易混淆产品（`ProductConfusionPair`，混淆组治理）

> 复用《身份血缘》§1.2 "Confusable Group" 概念，落为可持久化的规格对象。**软屏 vs 硬屏 = 第一组高相似混淆案例**，
> 是产品识别评测门禁（《评测计划》B1），**不是**识别流程的特例代码、**不是**通用数据结构的硬门禁。

| 字段（草案） | 说明 |
|---|---|
| `scope_level` | 混淆发生的层级（通常 `variant`，也可 `family` 跨族混淆） |
| `member_a_id` / `member_b_id` | 一对易混节点（多成员混淆组 = 多条对，或单独 `group_id` 聚合，落地评审） |
| `distinguishing_attributes` | JSONB：用于区分二者的 `identity_relevant` 属性键集（引用 §6 定义） |
| `notes` | 可见差异文字说明（运营提供） |
| `created_at` | — |

混淆治理规则（继承《身份血缘》§1.2，跨规格一致）：

- 识别 Provider 对混淆组内成员**默认不自动判定**，强制进**待人工确认**；仅当置信度 ≥ **变体区分阈值**
  （高于普通产品阈值，**阈值可配、不冻结**）才给出变体级判定。
- 检索 / 分镜的产品硬过滤在混淆组上提供**"按族过滤" / "按变体过滤"两档**（《使用感知检索》§2.1、《结构化分镜匹配》§1.1）。
- **一个产品可有多个易混淆产品**：通过多条 `ProductConfusionPair` 表达，新增混淆关系是插入数据行，免迁移。

---

## 8. 产品入驻状态（canonical 6 态）

> 入驻状态描述一个产品在目录中的**生命周期 / 可用度**，是**系统能力**（稳定有限态），新增产品只是在态间流转，不改枚举语义。
> 现有 `ProductStatus` 仅 `active`/`archived`，本 6 态为其 **[扩展]**（落地 PR 评审扩枚举或独立 `onboarding_status` 列）。
> 入驻**流程**（谁在什么条件下流转）详见《产品入驻流程》，本文件只冻结**状态集与语义**。

| 状态 | 含义 | 典型进入条件 |
|---|---|---|
| `draft` | 草稿 | 刚创建产品节点，信息不全 |
| `reference_incomplete` | 参考资料不全 | 缺必需参考图 / 缺 `required` 属性（§6） |
| `evaluation_required` | 待评测 | 资料齐备，但识别 / 检索基线未验证（《评测计划》） |
| `active` | 启用 | 通过入驻校验，正式可用于识别 / 检索 / 分镜匹配 |
| `paused` | 停用 | 暂时下线（不参与新识别 / 默认不出新检索），**历史关系保留** |
| `archived` | 归档 | 长期停用 / 退市，**历史素材关系与使用次数全部保留** |

> **停用 / 归档不丢历史（强约束）**：`paused` / `archived` 产品的素材↔产品关系、镜头使用记录、成片引用**全部保留**
> （《业务需求》§8.2 第 13 项、《身份血缘》§4 规则 9）。停用只影响"是否参与新识别 / 是否默认出现在新检索"，
> **绝不**删除既有血缘，**绝不**把使用次数重算为 0。

---

## 9. 启用 · 停用 · 合并 · 更名（历史关系绝不丢失）

> 总原则（最高优先级）：**产品更名 / 合并绝不丢失历史素材关系**（《业务需求》§8.2 第 14/15 项、《身份血缘》§2.1/§4 规则 9）。
> 所有变更通过 `ProductCatalogRevision`（§10）记录，旧映射保留，引用不丢失，使用次数不重算为 0。

| 操作 | 行为 | 历史保留方式 |
|---|---|---|
| **启用 / 停用** | `active ↔ paused`（§8） | 仅改可用度，关系与血缘不动 |
| **更名（rename）** | 改 `display_name`，旧名落 `legacy_name` 别名（§4.2） | 旧名别名 + Revision 记录；旧文件夹 / 旧素材仍命中 |
| **合并（merge）** | 把源产品节点并入目标节点 | **保留源产品旧映射**：源节点的素材↔产品关系、镜头使用记录、成片引用**重指向**目标节点但**保留来源痕迹**（旧 id 映射 + Revision），不物理删除历史；使用次数随迁不丢、不归零 |
| **拆分（split）** | 一个节点拆为多个（如一个变体实为两个 SKU） | Revision 记录拆分映射；原引用按规则重指或标待人工归并（不静默丢） |
| **SKU 迁移** | SKU 在变体 / 族间移动 | Revision 记录，引用随迁不丢（《业务需求》§8.2 第 16 项） |

实现倾向（草案，复用现有模式）：

- **更名**：复用 `ProductAlias`（`legacy_name`），不改主键，**最稳**。
- **合并 / 拆分 / SKU 迁移**：保留**旧产品 id → 新节点**的映射记录（落 `ProductCatalogRevision` 或并行 `product_id_remap`），
  业务对象（`AssetProduct` / `final_video_usage` / `shot` 标签）的产品引用**经映射解析**，旧引用永不变成"悬空 / 归零"。
  这与现有 SET NULL 引用保护、`ScriptSegment` 代次原子替换是同一族保护思路（《现状差距》§3 一句话映射）。

> **与使用血缘的一致性**：使用次数与成片引用**与产品类型无关**，`final_video_usage` 可引用任意产品任意 Shot，
> 未知产品（`unknown_product`）的 Shot 也可有使用记录（《身份血缘》§2.1）。因此**产品合并 / 更名只改"业务归属指向"，
> 不触碰使用次数事实**——使用记录的最小粒度是 Shot，产品只是 Shot 的业务归属。

---

## 10. 产品目录版本化（`ProductCatalogRevision`）

### 10.1 职责

`ProductCatalogRevision` 为整个动态产品目录提供**版本基线（catalog_revision）**，用于：

- 记录目录结构 / 属性定义 / 命名的**演进历史**（谁在何时做了什么变更）；
- 为**识别结果**提供 `catalog_revision` 锚点（《身份血缘》§1.5：识别结果绑定 `model_version` + `catalog_revision`）；
- 支撑**模型更新后重识别**：目录或模型版本变化可触发重识别，但**人工已确认结果保留**，进复核而非静默覆盖
  （与 `ShotReviewState` stale 机制一致）。

### 10.2 字段（草案）

| 字段 | 说明 |
|---|---|
| `id` / `revision_no` | 版本号（单调递增） |
| `change_type` | `create` / `rename` / `merge` / `split` / `sku_migrate` / `attribute_def_change` / `confusion_change` / `status_change` |
| `target_level` / `target_id` | 受影响节点 |
| `payload` | JSONB：变更明细（旧 id→新 id 映射、属性定义 diff、别名增减等） |
| `actor` / `created_at` | 操作者 + 时间（append-only 审计风格，复用《身份血缘》§5 `ReviewEvent` 精神） |

### 10.3 版本化规则

- **append-only**：版本记录只追加不改写（与现有 `ReviewEvent` append-only 一致），保证历史可回溯。
- **属性定义版本 ↔ 目录版本**：§6 的 `ProductAttributeDefinition.version` 是单条属性的版本；
  `ProductCatalogRevision` 是整个目录的版本基线，二者配合（属性 diff 落 Revision `payload`）。
- **重识别不覆盖人工**：重识别时对比 `catalog_revision` / `model_version`，人工确认过的产品归属标 `stale` 进复核，
  **绝不**自动用新模型结果覆盖人工确认（《身份血缘》§1.5、《路线图》PR-F）。

---

## 11. 当前产品的唯一合法用途（seed-only）

> 重申《业务需求》§8.3：当前 4 产品 + 6 候选标为 **seed dataset only**。

- **合法用途**：产品目录结构验证、参考图流程验证、相似变体（软 / 硬屏）混淆验证、扫描验证、产品识别基线、
  搜索基线、动作 / 场景标注模板验证、《评测计划》各评测集种子。
- **非法用途**：进入 Python / TypeScript 枚举、SQL `CHECK`、迁移固定产品、搜索规则硬编码、Prompt 固定产品列表、
  UI 固定选项、文件夹判断逻辑、排序算法特例。
- 软屏 vs 硬屏 = **第一组高相似产品混淆案例**，是产品识别评测门禁（《评测计划》B1），**不是**特例代码、**不是**通用数据结构的硬门禁。
- 详细 seed 范围与通用化风险审查见《种子数据范围》《通用化风险审查》。

---

## 12. 与开放集识别 / 检索 / 分镜的接口契约（跨文档一致）

> 本文件只定义产品目录本身；目录如何被识别 / 检索 / 分镜消费，分别以下游规格为准，此处只声明**接口契约**，保证术语一致。

| 接口 | 本文件提供 | 下游消费 | 一致性要点 |
|---|---|---|---|
| 开放集识别 | 动态目录 + 混淆组 + identity_relevant 属性 + catalog_revision | 《身份血缘》§1.5 识别 6 态 | 识别面向**公司目录的开放集**，无法识别输出 `unknown_product` / 待确认，绝不强制猜测；人工结果不被自动覆盖 |
| 使用感知检索 | searchable 属性 + 可变粒度产品过滤 | 《使用感知检索》§7.5 | 产品过滤来源 = 动态 Catalog（非固定枚举）；UI 产品选项由目录动态生成；未指定不强绑 |
| 结构化分镜匹配 | 任意粒度产品（Category/Family/Variant/SKU/别名/自由文本） | 《结构化分镜匹配》§1.1 | 先解析到 Catalog，无法精确解析返回候选而非强绑，未知进人工确认 |
| 使用血缘 | 产品作为 Shot 的业务归属（可空 / unknown） | 《身份血缘》§2.1 | 使用记录最小粒度 = Shot；产品更名 / 合并保留旧映射，历史引用不丢 |

---

## 13. 复用 vs 新增 一句话映射（对照《现状差距》/《身份血缘》）

| 现有 X（复用 / 扩展） | → | 本文件 Y |
|---|---|---|
| 扁平 `Product` 表 | → | `ProductVariant`（=`Product` 行，`family_id` / `model`=变体名）+ 上层 `ProductCategory` / `ProductFamily` |
| `Product.sku`（可空） | → | `ProductSKU`（可空，可变粒度归属） |
| `ProductAlias` + `normalized_alias` | → | 多层级别名 + 多语言名 + 文件夹别名 + 更名旧名（`legacy_name`） |
| `ProductImage` 受控相对路径 | → | `ProductReferenceAsset`（多角度 12 种 + is_identity_reference） |
| `Product.normalized_name` 标准化 | → | Category / Family / Variant / SKU / Alias 统一归一化 |
| `AssetProduct` 多对多 + source/active | → | 关联到可变粒度产品节点（含 unknown）；合并 / 更名经旧映射解析不丢 |
| `ProductStatus`（active/archived） | → | 6 态入驻状态超集（draft/reference_incomplete/evaluation_required/active/paused/archived） |
| `ReviewEvent` append-only + stale | → | `ProductCatalogRevision` append-only 版本化 + 重识别不覆盖人工 |
| SET NULL 引用保护 / 代次原子替换 | → | 合并 / 拆分 / SKU 迁移的旧 id→新节点映射保护（引用不悬空 / 不归零） |
| 无独立表 | → | **[新增]** `ProductCategory` / `ProductFamily` / `ProductAttributeDefinition` / `ProductAttributeValue` / `ProductConfusionPair` / `ProductCatalogRevision` |

---

## 14. 不做（本规格边界）

- **本阶段只写文档**：不创建任何 Alembic 迁移、不建库、不改模型、不接模型、不下载模型权重、不改搜索排序、不开始任何落地 PR。
- 表名 / 字段 / 枚举均为**草案**，落地 PR（《路线图》PR-A1/PR-A2 起）再评审。
- **不把当前 4 产品 / 6 候选写进任何代码逻辑**（枚举 / CHECK / 迁移固定产品 / 搜索规则 / Prompt 列表 / UI 选项 / 文件夹判断 / 排序特例）。
- **不冻结任何阈值 / 权重**（变体区分阈值、必填校验严格度、识别置信门限等均运行期可配、落地 PR 评审）。
- **不对易混淆变体（软 / 硬屏）做任何自动断言**：识别特征只供后续 PR 比对，AI 推断默认 `needs_human`。
- **不丢历史**：停用 / 归档 / 更名 / 合并 / 拆分 / SKU 迁移一律保留旧映射，历史素材关系与使用次数不丢、不归零。
- **不依赖当前产品的数量 / 名称 / 目录结构 / 差异**：层级是结构、属性是受约束动态键值，新增产品全程免迁移、免改代码。
- 继承项目硬约束：绝不生成式视频；源素材只读（参考图受控存储，绝不写源目录）；证据分层，UI 不伪造结论。
