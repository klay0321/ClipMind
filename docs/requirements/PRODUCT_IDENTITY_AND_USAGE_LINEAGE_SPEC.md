# 产品身份与使用血缘规格（PRODUCT_IDENTITY_AND_USAGE_LINEAGE_SPEC）

> 阶段：Phase 0 Discovery。本文件冻结**产品身份层级**与**使用血缘（成片↔镜头引用、使用次数）**的规格。
> 业务语境见 `ECOMMERCE_MEDIA_ASSET_REQUIREMENTS.md`；检索用法见 `USAGE_AWARE_RETRIEVAL_SPEC.md`。
> **本阶段只写规格，不创建任何 Alembic 迁移、不改模型、不改搜索排序。** 字段为设计草案，落地 PR 再评审。
>
> 标注约定：**[复用]** 现有模型可承载 / **[扩展]** 现有加列或加关系 / **[新增]** 新建表。
> 现有模型出处见 `packages/shared/clipmind_shared/models/`（`product.py`/`asset.py`/`shot.py`/`review.py`/`enums.py`）。

---

## 1. 产品身份层级

> **通用层级（全部动态创建、无需迁移）**：`Product Category → Product Family → Product Variant → SKU`
> （canonical 对象名 `ProductCategory` / `ProductFamily` / `ProductVariant` / `ProductSKU`，二者等价，权威定义见《通用产品目录》）。
> 完整通用产品目录（含动态属性、入驻、版本化、更名/合并）见《通用产品目录》《产品入驻流程》。
> 下方"恶魔之眼/软屏"等仅为 **seed 示例**，**非架构依赖**（系统不得依赖当前产品名/数量/目录）。

```text
Product Category（产品类别，动态，如 数码/汽配 …）
  └── Product Family（产品族，seed 示例 恶魔之眼）
        └── Product Variant（产品变体，seed 示例 软屏 / 硬屏）
              └── SKU（货号，可空）
                    ├── Alias（别名 / 多语言名 / 文件夹别名）
                    └── Product Reference Image（参考图，多张，带角度）
```

### 1.1 与现有模型映射

| 层级 | 现有承载 | 状态 | 设计草案 |
|---|---|---|---|
| Product Category | 无独立表 | [新增] | 新增 `product_category` 表（动态创建），承载未来不同品类；`product_family.category_id` 外键。详见《通用产品目录》。 |
| Product Family | 无独立表 | [扩展/新增] | 方案 A：新增 `product_family` 表，`product.family_id` 外键；方案 B：`product` 自引用 `parent_id` + `is_family`。**倾向方案 A**（family 有独立别名/混淆组语义）。 |
| Product Variant | 现有 `Product` 行 | [复用] | 每个变体 = 一行 `Product`；用 `Product.model` 承载变体名（如 `软屏`），`family_id` 指向族。 |
| SKU | `Product.sku` | [复用] | 已有，可空；运营台账补全。 |
| Alias | `ProductAlias` | [复用] | 已有 `normalized_alias` 候选匹配；family 级别名需 `product_family` 也支持别名（[扩展]）。 |
| Reference Image | `ProductImage` | [复用] | 已有受控相对路径 `products/{product_id}/images/`。 |
| 素材↔产品 | `AssetProduct`（多对多） | [复用] | 已有 `source`(ai/human)/`confidence`/`match_type`/`active`/`confirmed_by`。 |
| 镜头↔产品 | `ShotReviewState.confirmed_product_id` + `ShotTag`(type=product) | [复用] | 镜头级产品以人工确认或 AI 候选为准。 |

### 1.2 混淆组（Confusable Group）[新增概念]

为治理"软屏 vs 硬屏"这类**同族易混变体**，引入 **confusable group**：

- 一个 family 内若存在易混变体，标记为同一 confusable group。
- 视觉识别（后续 PR）对 confusable group 内变体**默认不自动判定**，强制进入待人工确认；
  仅当置信度高于"变体区分阈值"（高于普通产品阈值）才给出变体级判定。
- 检索/分镜的"产品硬过滤"在 confusable group 上提供"按族过滤"与"按变体过滤"两档。

### 1.3 软屏 vs 硬屏 —— 人工差异特征（运营需提供）

> 本阶段**不**对软/硬屏做任何自动断言。以下为需运营确认的可见识别特征（来自审计 `product_review_queue.csv`）：

- 屏体是否可弯曲贴合曲面（软屏柔性 vs 硬屏刚性）
- 屏体边缘 / 包边结构差异
- 排线 / 接线方式与位置
- 安装方式（曲面贴合 vs 平面安装）
- 厚度与背板结构
- 外包装与丝印标识
- SKU / 货号差异

落地前由运营提供对照图或文字说明，写入 `product_family`/`Product` 的可见特征字段与参考图标注。

### 1.4 产品识别置信与分层

| 来源 | inference_type | 是否自动生效 |
|---|---|---|
| 文件名/目录规则命中（如目录含"软屏"） | 规则推断 | 仅作候选，needs_human=true |
| 视觉识别 Provider（后续 PR） | AI 推断 | 候选；confusable 变体必须人工确认 |
| 运营/审核确认 | 人工确认 | 生效（`AssetProduct.active=true` / `confirmed_product_id`） |

**绝不只根据目录名最终确认产品身份**；低置信宁可标"未知/待确认"。

### 1.5 开放集产品识别（不在已知产品中强制选一个）

> ClipMind 是**面向公司产品目录的开放集识别系统**（见《业务需求》§8）：识别**不能**只在已知产品中强制选一个；
> 无法识别必须输出 unknown / 待确认，**绝不强制猜测**。软/硬屏只是**第一组高相似混淆案例**，不得成为识别流程的特例代码。

**识别结果（6 态，canonical，对全部产品一致）**：

| 结果 | 含义 |
|---|---|
| `confirmed_product` | 已（人工）确认产品 |
| `probable_product` | 高置信单一候选，待确认 |
| `multiple_candidates` | 多个候选（含 confusable 组），需人工选 |
| `unknown_product` | 不在公司目录中 / 无法判定 → 人工确认 |
| `no_product_visible` | 画面无产品 |
| `human_review_required` | 低置信 / 多产品 / 遮挡等，强制人工 |

**识别结果字段**：`product_family_candidate` / `product_variant_candidate` / `sku_candidate` / `confidence` /
`top_candidates` / `evidence` / `reference_matches` / `unknown_score` / `review_status` / `model_version` / `catalog_revision`。

**必须支持**：Top-1 / Top-3 / 未知拒识 / 多产品 / 无产品 / 低置信 / 人工覆盖 / **模型更新后重识别** / **人工确认结果不被自动覆盖**。
识别结果绑定 `model_version` + `catalog_revision`：模型或目录版本变化可触发重识别，但人工已确认结果保留（与 `ShotReviewState` stale 机制一致，进复核而非静默覆盖）。

---

## 2. 使用记录粒度与血缘

### 2.1 引用链

```text
Final Video（成片）
  └── Final Video Usage（成片使用记录：一条 = 成片在某时间码用了某源镜头）
        └── Source Shot（被引用的源镜头）
              └── Source Asset（镜头所属源素材）
                    └── Product（素材/镜头归属产品）
```

- **正式使用记录的最小粒度是 Shot**（不是 Asset）。
- **Asset 的使用情况 = 其全部 Shot 的使用汇总**（任一 Shot 被用 → Asset"被用过"；次数为去重后的成片数或引用数，规则见 §4）。

> **通用性（与产品类型无关）**：使用次数与成片引用**与产品类型无关**。`Final Video Usage` 可引用**任意产品的任意 Shot**，
> **绝无当前产品特例**。产品只是 Shot 的**业务归属**；**未知产品（`unknown_product`）的 Shot 也可以有使用记录**。
> 产品**更名**保留旧映射、**合并**保留旧产品映射（见《通用产品目录》Catalog Revision），**历史引用不丢失**。

### 2.2 新增模型草案

> 字段为草案，落地 PR 评审；命名沿用现有风格（`*_id`、`created_at`、SET NULL 引用保护、JSONB 证据）。

**`final_video`** [新增]
| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| title | str | 成片名 |
| project_id | FK project SET NULL | 可选归属业务项目（与现有 `Project` 一致） |
| source_type | enum | `uploaded_mp4` / `editor_project` / `external_link` / `manual` |
| asset_fingerprint | str? | 成片自身指纹（若导入文件） |
| duration / width / height / fps | … | ffprobe（若有文件） |
| storage_path | str? | 受控相对路径（若导入文件，绝不写源目录） |
| status | enum | `imported` / `linked` / `archived` |
| created_at / updated_at | ts | |

**`final_video_usage`** [新增]（成片↔镜头引用，核心使用记录）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| final_video_id | FK final_video CASCADE | |
| shot_id | FK shot SET NULL | 被引用源镜头（删除镜头清引用不删记录，保留审计） |
| asset_id | FK asset SET NULL | 冗余便于 Asset 汇总（镜头删除仍可统计 Asset 维度） |
| evidence_level | enum（见 §3） | 证据等级 |
| final_timecode_start / end | float? | 在成片中的位置（若可定位） |
| source_timecode_start / end | float? | 对应源镜头时间码 |
| confirmed | bool | 是否人工确认（仅 confirmed 计入正式次数） |
| confirmed_by / confirmed_at | … | 审核信息 |
| evidence | JSONB | 原始证据（工程文件路径、匹配分、legacy 路径等） |
| created_at / updated_at | ts | |

约束草案：`(final_video_id, shot_id, source_timecode_start)` 近似唯一；引用用 SET NULL 保护（继承现有 `script_segment.locked_shot_id` 的处理风格）。

### 2.3 现有模型的使用情况扩展

- **`Shot`** [扩展]：派生只读统计列（或单独 `shot_usage_stat` 投影表）：
  `confirmed_usage_count`、`suspected_usage_count`、`legacy_used_flag`、`last_used_at`、`distinct_final_video_count`。
- **`Asset`** [扩展]：`usage_rollup`（由 Shot 汇总，物化或视图）。
- 选择**投影表/物化**而非直接写 Shot：与现有 `ShotTag`/`ShotSearchDocument` 投影模式一致，便于"删除/驳回引用后重算"。

---

## 3. 使用证据等级（evidence_level）

> 6 级，从强到弱。**只有 confirmed_* 计入正式 `usage_count`**；suspected_* / legacy 不计入。

| 等级 | 含义 | 默认是否计入正式次数 | 典型来源 |
|---|---|---|---|
| `confirmed_editor_project` | 来自剪辑工程文件解析（Premiere/FCP/剪映/EDL）确认引用 | 是 | 解析 `.prproj`/`.fcpxml`/`.edl`/剪映工程 |
| `confirmed_manual` | 人工明确确认"此成片用了此镜头" | 是 | 剪辑/运营手工确认 |
| `confirmed_clipmap_export` | 来自 ClipMind 自身导出的剪辑清单回填 | 是 | 系统导出清单 → 回填 |
| `suspected_visual_match` | 视觉相似度疑似引用（pHash/帧匹配） | 否（待确认） | 后续视觉反查 |
| `suspected_audio_match` | 音频指纹疑似引用（Chromaprint） | 否（待确认） | 后续音频反查 |
| `legacy_path_rule` | 历史"已使用"目录/后缀规则 | 否（仅"可能用过"） | 本阶段审计 `used_evidence.csv` |

> 业务规则（与审计一致）：位于"已使用"目录或带"已使用"后缀，**只能证明可能曾经使用，
> 不能自动认定准确使用次数，也不能自动确定被哪个成片引用**。

---

## 4. 使用次数规则

1. **只有 confirmed 计入正式 `usage_count`**；`suspected_*` 进入"待确认引用"队列，不计入。
2. **`legacy_path_rule` 只标记"可能使用过"**（usage_state=usage_unknown / 或 legacy_used_flag），不计入次数。
3. **删除或驳回引用后，次数重新计算**（投影重算，幂等）。
4. **Asset 使用次数 = 其 Shot 使用情况的汇总**（默认按"去重成片数"计；同一成片多次引用同一镜头是否折算见落地评审）。
5. **保留成片与项目关系**：`final_video.project_id`、引用链可回溯。
6. **保留最近使用时间** `last_used_at`（取该镜头/素材最近一条 confirmed 引用的成片时间）。
7. **次数为软信号**：用于检索/分镜**降权**，默认**不绝对排除**（严格未使用模式见检索规格）。
8. **对全部产品一致**：使用次数与产品类型无关；**未知产品的 Shot 也可有使用记录**（产品=Shot 的业务归属，非使用前提）。
9. **更名/合并保留历史**：产品更名/合并通过 Catalog Revision 保留旧产品映射，**使用次数与历史引用不丢失、不需重算为 0**。

**使用频次状态（7 态，canonical，阈值全部配置化）**：由 `confirmed_usage_count` + `last_used_at` 派生 —
`never_used`（confirmed=0 且无 legacy/suspected）/ `legacy_used_unknown`（仅 legacy_path_rule）/ `used_once`（=1）/
`used_multiple`（≥2）/ `recently_used`（last_used_at 近 N 天，正交可叠加）/ `overused`（≥过度阈值，触发降权建议）/
`usage_unknown`（血缘未建立兜底）。**引用确认轴正交**：`usage_pending_review`（suspected 待确认）/ `usage_confirmed`（≥1 confirmed）。
阈值（低/高/过度/近期 N 天）**不在此冻结**，运行期可配置，且**可按 Category 差异化**（不同品类共用同一阈值是否合理见《通用化风险审查》）。

伪代码（投影重算，示意）：
```text
for shot in shots:
    confirmed = usages(shot, confirmed=True)
    shot.confirmed_usage_count = distinct(final_video_id for u in confirmed)
    shot.last_used_at = max(final_video.date for u in confirmed) or null
    shot.suspected_usage_count = count(usages(shot, evidence_level startswith 'suspected'))
    shot.legacy_used_flag = exists(usages(shot, evidence_level == 'legacy_path_rule'))
asset.usage_rollup = aggregate(shot stats for shot in asset.shots)
```

---

## 5. 人工审核（复用现有审核体系）

> 复用现有 `ShotReviewState` + `ReviewEvent` + `ReviewStatus`/`ReviewAction` 的设计模式（append-only 审计、乐观锁、stale 标记）。
> 使用血缘审核可新增并行的 `usage_review_event`（或复用 `review_event` 加 object_type='final_video_usage'）。

使用引用审核动作（针对 `final_video_usage`）：

| 动作 | 效果 |
|---|---|
| **确认** confirm | suspected → confirmed；计入正式次数（触发投影重算） |
| **驳回** reject | 删除/标记无效；从次数中扣除（重算） |
| **修改来源 Shot** | 改 `shot_id`（引用挂到正确镜头）；重算受影响镜头次数 |
| **修改时间码** | 改 `source_timecode_*` / `final_timecode_*` |
| **批量确认** | 对一批 suspected 引用批量 confirm（如一次成片导入的多条） |
| **查看证据** | 展示 `evidence`（工程文件路径/匹配分/legacy 路径），支持人工判断 |

审核原则：**append-only 审计**（每次动作新增 `review_event`，不改旧事件）；并发用 `lock_version` 乐观锁；
重拆镜头/重分析导致引用失效时标 `stale`，进入复核而非静默丢弃。

---

## 6. 稳定 Asset 身份策略（应对"移动到已使用"）

> 审计事实：公司"已使用"靠**移动**而非复制，库内 0 字节级重复。必须保证素材移动后仍识别为**同一个 Asset**，而非新建重复素材。

身份策略（分层）：

```text
Asset 内容身份（content identity）
  = full_hash（完整内容 SHA256，现有 Asset.full_hash 预留列）   ← 强身份，跨路径稳定
  + quick_hash（头尾+大小快速指纹，现有 Asset.quick_hash）       ← 快速候选
当前位置：source_directory_id + normalized_relative_path（现有唯一约束）
历史路径：path history（[新增] asset_path_history：记录每次扫描观察到的路径与时间）
```

落地原则（草案）：

1. **入库/重扫描时先按 content identity 匹配**（full_hash → 命中则视为同一 Asset，仅更新当前路径并追加历史），
   再回退到 `(source_directory_id, normalized_relative_path)`。
2. 文件被移动到 `已使用/`（同一 source_directory 内路径变化）→ full_hash 命中 → **更新位置 + 追加 path history**，
   不新建 Asset、不丢失既有镜头/标签/使用记录。
3. `已使用` 目录/后缀 → 写入 `legacy_path_rule` 级使用证据（"可能用过"），不改正式次数。
4. full_hash 计算成本：现有 `full_hash` 为预留列；落地 PR 决定何时计算（入库时或按需），
   遵循审计脚本的**分级策略**（先 size/quick_hash 候选，再 full_hash），避免对全部大视频无条件全量哈希。

> 注意：本阶段**不**启用 full_hash 回填、**不**新增 path history 表、**不**写迁移；以上为身份策略冻结，落地见路线图 PR-B/PR-C。

---

## 7. 不做（本规格边界）

- 不创建任何数据库迁移 / 不改现有模型 / 不改搜索排序（本阶段）。
- 不自动把 suspected/legacy 计入正式次数。
- 不对软/硬屏做自动断言。
- 不承诺仅凭最终 MP4 全自动精确反查原片（成片反向引用是带证据+人工的尽力而为）。
