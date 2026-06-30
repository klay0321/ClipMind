# 使用感知检索规格（USAGE_AWARE_RETRIEVAL_SPEC）

> 阶段：Phase 0 Discovery（需求冻结）。本文件冻结**使用感知检索（usage-aware retrieval）**的过滤维度、排序因素与规则。
> 业务语境见 `ECOMMERCE_MEDIA_ASSET_REQUIREMENTS.md`（《业务需求》）；产品身份与使用血缘见 `PRODUCT_IDENTITY_AND_USAGE_LINEAGE_SPEC.md`（《身份血缘》）；
> 结构化分镜匹配见 `STORYBOARD_MATCHING_SPEC.md`。
>
> **本阶段只写规格**：不创建任何 Alembic 迁移、不改模型、不改搜索排序、不接新模型、不下载模型权重。
> 字段与因素为设计草案，落地 PR 再评审。
>
> 标注约定：**[复用]** 现有模型/逻辑可承载 / **[扩展]** 现有加列、加关系或加因素 / **[新增]** 本批新建。
> **本规格的核心定位是：在现有 Hybrid Search 与 `ScriptShotCandidate` 评分因子之上，新增 usage 过滤与降权因子**，
> 不重写检索内核，不改动 `document_status` / `embedding_status` 正交语义与嵌入不可用回退。

---

## 0. 目标与边界

### 0.1 解决的业务痛点（对应 《业务需求》 业务问题）

| 业务问题（《业务需求》） | 本规格能力 |
|---|---|
| 6. 搜索结果产品/动作/场景不准确 | 产品/变体硬过滤 + 动作/场景/景别过滤 + 内容/产品/动作/场景匹配度因素 |
| 7. 高频素材重复出现、成片同质化 | 使用次数惩罚 + 近期重复惩罚 + 同源素材重复惩罚 + 同一 Asset 结果数量限制 + 结果多样性 |
| 8. 未使用素材沉底、浪费拍摄成本 | 未使用过滤维度 + 未使用奖励因素 + "优先未使用"档 |
| 4. 使用次数不可追踪 / 5. 不知被哪些成片引用 | 每个结果显示使用次数与"被哪些成片使用"（来自 《身份血缘》 引用链） |

### 0.2 明确边界

- 本规格只描述**检索时如何使用**使用情况信号；使用次数、证据等级、引用链的**定义与计算**以 《身份血缘》 为准，本文件不重复定义、不冲突。
- **不冻结权重**：下文只列**可配置因素**与**默认倾向**，所有权重、阈值、上限均为运行期可配置项，落地 PR 评审默认值。
- 继承项目硬约束：不做任何生成式视频能力；源素材只读；证据分层（事实 / 规则推断 / AI 推断 / 人工确认），UI 不伪造"已识别 / 已匹配 / 使用次数"。

---

## 1. 复用与新增总览（务必先读）

> 本规格是**扩展**，不是重写。落地时严禁另起一套检索/评分内核。

### 1.1 复用现有（不要重写）

- **Hybrid Search [复用]**：现有多通道召回与融合（语义向量 + 词法/pg_trgm + 标签 + 产品 + 结构化召回），
  融合逻辑见 `packages/shared/clipmind_shared/search/scoring.py`（RRF + 在场通道加权均值 + 有限加权 − 风险惩罚）。
- **`document_status` / `embedding_status` 正交语义 [复用]**：见 `ShotSearchDocument`
  （`packages/shared/clipmind_shared/models/search.py`）。两者**正交**：
  - 文档层（`document_status` / `is_searchable`）门控**非向量召回**（词法 / 标签 / 产品 / 结构化）；
  - 嵌入层（`embedding_status`）只影响**向量召回是否可用**；
  - **嵌入不可用（缺失/降级）时文档仍 `is_searchable`，继续非向量召回，绝不因嵌入缺失而无法搜索**。
    本规格的所有 usage 能力**同样不依赖嵌入**：嵌入降级时 usage 过滤/降权照常生效。
- **现有融合因素 [复用]**：`Candidate` / `ScriptShotCandidate` 已有的评分字段——
  `semantic_score` / `lexical_score` / `tag_score` / `product_score` / `quality_score` /
  `review_bonus` / `risk_penalty` / `final_score` 及 `matched_reasons` / `unmatched_requirements` / `risk_warnings`。
- **产品硬过滤 [复用]**：基于 `AssetProduct` / `ShotReviewState.confirmed_product_id` /
  `ShotTag(type=product)`，含 《身份血缘》 confusable group 的"按族 / 按变体"两档。
- **人工审核状态 [复用]**：`ShotReviewState` + `ReviewStatus`（unreviewed/pending_review/confirmed/modified/rejected/unable）。
- **稳定全序排序与分页 [复用]**：`order_candidates` / `paginate` 的 tie-breaker（final↓ quality↓ human优先 created_at↑ shot_id↑）。

### 1.2 本规格新增（只新增 usage 维度）

- **usage 过滤维度 [新增]**：未使用 / 优先未使用 / 允许少量使用 / 排除高频 / 最近 N 天未使用 等（§2）。
- **usage 排序因素 [新增/扩展]**：未使用奖励、使用次数惩罚、近期重复惩罚、同源素材重复惩罚（§3）。
  作为新因素**叠加进现有融合公式**，不替换现有因素。
- **结果约束 [新增]**：同一 Asset 结果数量限制、结果多样性、每结果展示使用次数与引用成片（§4）。
- **usage 信号来源 [复用 《身份血缘》]**：`confirmed_usage_count` / `suspected_usage_count` / `legacy_used_flag` /
  `last_used_at` / `distinct_final_video_count` 及 Asset `usage_rollup`（《身份血缘》 §2.3 的投影列/物化，本规格只**读**这些派生信号）。

---

## 2. 检索过滤维度

> 过滤分两类：**硬过滤**（不满足直接排除出结果集）与 **usage 软偏好**（不排除，只改排序，见 §3）。
> usage 类过滤默认是**软偏好**；可被用户显式切到硬过滤（如"严格未使用"）。

### 2.1 内容/属性过滤（[复用] 现有 Hybrid Search 过滤）

| 维度 | 类型 | 来源（复用） |
|---|---|---|
| 产品（family / SKU） | 硬过滤 | `AssetProduct` / `confirmed_product_id`（《身份血缘》） |
| 产品变体（如 软屏/硬屏） | 硬过滤 | confusable group "按变体"档（《身份血缘》 §1.2）；低置信不强判 |
| 动作 action | 软/硬可选 | `ShotTag(type=action)` |
| 场景 scene | 软/硬可选 | `ShotTag(type=scene)` |
| 景别 shot_type | 软/硬可选 | `ShotTag(type=shot_type)` |
| 风险 risk | 硬排除（含风险） / 软惩罚 | `ShotTag(type=risk)`；硬排除在 SQL 过滤，软惩罚见 `risk_penalty` |
| 人工确认状态 | 过滤 | `ReviewStatus`（如"仅看 confirmed/modified"、"排除 rejected/unable"） |

> 变体硬过滤遵循 《身份血缘》：confusable group 内变体**默认不自动判定**，低置信镜头标"未知/待确认"，
> "按变体"硬过滤时此类镜头默认**不计入**该变体结果（可由用户切到"按族"放宽）。

### 2.2 使用感知过滤（[新增]）

> 信号字段来自 《身份血缘》 投影（本规格只读不写）：`confirmed_usage_count`、`last_used_at`、`legacy_used_flag`、Asset `usage_rollup`。

| 过滤维度 | 语义 | 默认行为 | 可切换 |
|---|---|---|---|
| **仅未使用** | 只保留 `confirmed_usage_count = 0` 且无 confirmed 引用 | 硬过滤（用户显式选择时） | — |
| **优先未使用** | 未使用排前，已使用仍可出现 | 软偏好（加"未使用奖励"，不排除） | 可升级为"仅未使用"硬过滤 |
| **允许少量使用** | 保留 `confirmed_usage_count ≤ 阈值低` | 硬过滤（阈值可配） | 阈值可配 |
| **排除高频使用** | 排除 `confirmed_usage_count ≥ 阈值高` | 硬过滤（阈值可配） | 可降级为"高频降权"软偏好 |
| **最近 N 天未使用** | 排除 `last_used_at` 在近 N 天内 | 硬过滤（N 可配） | 可降级为"近期重复降权"软偏好 |
| **使用情况未知可见性** | 是否包含 `usage_unknown`（仅 legacy/弱证据） | 默认包含并提示"使用情况未知" | 可切换隐藏 |

约束（与 《身份血缘》 一致）：
- **`suspected_*` 与 `legacy_path_rule` 不计入正式 `usage_count`**：因此"仅未使用 / 排除高频"等基于次数的硬过滤**只看 confirmed**；
  仅有 legacy/suspected 证据的镜头在"未使用次数"维度上视为"未使用但使用情况未知"，UI 必须标注其证据等级，不得显示为"已使用 N 次"。
- 过滤维度可组合（产品硬过滤 + 动作软过滤 + 优先未使用 + 最近 30 天未使用 …），组合为合取（AND）。

---

## 3. 排序因素（可配置，**不冻结权重**）

> 排序 = **现有融合公式 [复用] + 新增 usage 因素 [新增]**。
> 现有公式见 `scoring.py`：`final = base(RRF+加权均值) + 精确产品加权 + 审核加权 + 质量加权 − 风险惩罚`，全部在 [0,1] 截断。
> 本规格在该公式上**追加 usage 加权/惩罚项**，所有系数为**可配置**，此处只列因素与默认倾向，**不冻结具体权重**。

### 3.1 复用的现有因素（不重定义）

| 因素 | 字段（复用） | 方向 | 说明 |
|---|---|---|---|
| 内容匹配度 | `semantic_score` + `lexical_score`（经 RRF/加权均值融合） | 越高越前 | 语义 + 词法通道 |
| 产品匹配度 | `product_score` + 精确产品加权（`exact_product`） | 越高越前 | 产品通道 + SKU/型号精确命中 |
| 动作匹配度 | `tag_score`（action 维度贡献） | 越高越前 | 标签通道（action） |
| 场景匹配度 | `tag_score`（scene 维度贡献） | 越高越前 | 标签通道（scene） |
| 质量分 | `quality_score`（质量加权） | 越高越前 | 派生质量 |
| 人工确认奖励 | `review_bonus`（`is_human_effective` → confirmed/modified 未 stale） | 加分 | 人工有效结果上浮 |
| 风险惩罚 | `risk_penalty`（`has_unexcluded_risk`） | 减分 | 含未排除风险标签的软惩罚（硬排除在 SQL 过滤） |

> 动作/场景匹配度当前由统一 `tag_score` 通道承载；落地 PR 可评审是否将其拆为独立可配置子因素
> （`action_score` / `scene_score`），本阶段不强制拆分，仅在规格上声明它们是独立的"可配置因素"。

### 3.2 新增的 usage 因素（[新增]，叠加进融合公式）

| 因素 | 信号来源（《身份血缘》，只读） | 方向 | 默认倾向（不冻结数值） |
|---|---|---|---|
| **未使用奖励** unused_bonus | `confirmed_usage_count = 0` 且无 confirmed 引用 | 加分 | 默认开启，幅度受上限约束；"优先未使用"档加大 |
| **使用次数惩罚** usage_count_penalty | `confirmed_usage_count`（越大惩罚越大，建议次线性/对数衰减） | 减分 | 默认**软降权、不绝对排除**（§4.1）；上限受限，避免压过强内容命中 |
| **近期重复惩罚** recency_penalty | `last_used_at` 距今越近惩罚越大（近 N 天窗口可配） | 减分 | 默认开启；窗口外惩罚归零 |
| **同源素材重复惩罚** same_asset_penalty | 同一 Asset / 同一拍摄目录在**本次结果集内**已出现次数 | 减分（结果集内动态） | 默认开启，配合 §4.2 数量限制做多样性 |

公式形态（示意，**系数全部可配置、此处不冻结**）：

```text
final_usage_aware =
    final_score (现有融合，[0,1])
  + W_unused        * unused_bonus
  - W_usage_count   * f_count(confirmed_usage_count)        # f_count 建议 log/次线性，避免线性爆惩
  - W_recency       * f_recency(last_used_at, now, window)  # 窗口外为 0
  - W_same_asset    * f_dup(same_asset_seen_in_result)      # 结果集内去重降权
然后整体在 [0,1] 截断；再走现有 order_candidates 稳定全序排序。
```

约束：
- **usage 因素只改 base 之上的加权项，绝不改动 RRF 召回与 `document_status`/`embedding_status` 门控**；
  嵌入降级（向量召回缺失）时，usage 因素仍照常叠加到非向量召回结果上。
- 所有 usage 惩罚有**上限**（cap），保证"强内容/产品命中"不会被 usage 惩罚单独翻盘到结果集外（除非用户显式开"严格未使用"硬过滤）。
- usage 因素必须可整体关闭（开关 + 权重置 0），关闭后退化为现有 Hybrid Search 行为，**不破坏既有检索**（继承 《业务需求》 §7 "可回退"）。

---

## 4. 规则

### 4.1 使用次数是软降权，不默认绝对排除

- 默认：使用次数**只软降权**（§3.2 `usage_count_penalty`，带上限），**不**把已使用镜头排除出结果集。
- 理由：高频镜头可能仍是某段的唯一/最佳产品命中；绝对排除会造成"产品对但全被滤掉"的空结果（《业务需求》 痛点 6/9 反例）。

### 4.2 可切换"严格未使用"

- 用户可显式开启 **严格未使用模式**：等价于"仅未使用"硬过滤（§2.2），`confirmed_usage_count > 0` 的镜头直接排除出结果集。
- 严格模式是**显式、可见、可一键关闭**的状态，UI 必须明确提示当前为严格未使用，避免用户误以为"库里没有可用镜头"。
- 严格模式同样不依赖嵌入：嵌入降级时严格未使用过滤照常生效。

### 4.3 锁定镜头不受重排影响

- 与 《身份血缘》 / 分镜规格一致：`script_segment.locked_shot_id`（人工锁定）**不参与 usage 重排，也不被 usage 过滤剔除**。
- usage 降权 / 过滤只作用于"候选检索结果"，**绝不覆盖人工锁定**；锁定镜头即使高频使用，也保持锁定位置。
- `selected_shot_id`（人工已选但未锁定）默认置顶展示，usage 因素可对其给出"已高频使用"提示但不自动替换（替换需人工动作）。

### 4.4 同一 Asset 结果数量限制

- 默认对**同一 Asset**（及其全部 Shot）在单次结果集中的出现数量设上限（如每 Asset 最多 N 个镜头进结果首屏，N 可配）。
- 目的：避免同一条原片的多个镜头霸屏，挤掉其他素材（呼应 《业务需求》 痛点 7 同质化）。
- 超出上限的同 Asset 镜头折叠为"同源更多镜头"，可展开，不直接丢弃。

### 4.5 结果多样性

- 在满足匹配度的前提下，鼓励**产品变体 / 拍摄目录 / Asset 来源的多样性**（同源素材重复惩罚 §3.2 + 同 Asset 数量限制 §4.4 共同实现）。
- 多样性是软目标：不得为多样性牺牲明显更强的内容/产品命中（多样性惩罚有上限）。

### 4.6 每个结果显示使用次数与被哪些成片使用

- 每个检索结果必须可展示（来自 《身份血缘》 引用链 `Final Video →(Final Video Usage)→ Shot → Asset → Product`，只读）：
  - **正式使用次数** = `confirmed_usage_count`（仅 confirmed 计入）；
  - **被哪些成片使用** = 该镜头 confirmed 引用对应的 Final Video 列表（标题/项目）；
  - **最近使用时间** = `last_used_at`；
  - **待确认/历史证据** = `suspected_usage_count`、`legacy_used_flag` 单独展示，**标注证据等级，不混入正式次数**。
- **证据分层展示（强约束）**：使用次数标注【人工确认】（confirmed），疑似引用标注【AI 推断】（suspected_visual/audio），
  legacy 标注【规则推断】（legacy_path_rule）。**UI 绝不把 suspected/legacy 显示为"已使用 N 次"**，绝不伪造"已识别/已匹配/使用次数"（继承硬约束 + 《身份血缘》）。
- 使用频次状态徽标（7 态：never_used / legacy_used_unknown / used_once / used_multiple / recently_used / overused /
  usage_unknown）+ 正交确认轴（usage_pending_review / usage_confirmed）按 《业务需求》 §5 的派生定义展示，**派生条件以底层字段为准**，本规格不冻结阈值。

---

## 5. 与脚本/分镜匹配的关系（[扩展] `ScriptShotCandidate`）

- 当前脚本匹配是**每段独立产候选**（《业务需求》 已知缺口：缺全局分配 + 同源去重 + 使用感知降权）。
- 本规格的 usage 过滤/降权因素同样作用于**单段候选检索**：`ScriptShotCandidate` 复用现有评分字段，
  usage 因素作为新加权项叠加进同一融合公式（与 §3 一致），落地时建议把 usage 信号也落到候选的可解释字段
  （如 `matched_reasons` 增加"未使用/低频"理由、`risk_warnings` 增加"高频重复露出"提示）。
- **全局分配 + 同源去重**（同一镜头不被塞进多段、跨段同 Asset 去重）属于 `STORYBOARD_MATCHING_SPEC.md` 范畴；
  本规格只提供"使用感知降权"这一可被全局分配器复用的因素，不在此定义全局分配算法。
- 锁定/已选镜头在脚本匹配中的处理见 §4.3，与分镜规格保持一致。

---

## 6. 可解释性与证据分层

- 每个结果的排序需可解释：复用现有 `matched_reasons` / `unmatched_requirements` / `risk_warnings`，
  并由 usage 因素补充"未使用奖励 / 高频降权 / 近期重复 / 同源去重"等可读理由（规则派生，**绝不由 LLM 编造**）。
- 结论证据分层（贯穿 《业务需求》 §7）：
  - 内容/标签匹配 → 【AI 推断】或【人工确认】（视有效结果来源）；
  - usage 次数 → 【人工确认】（仅 confirmed）；
  - 疑似引用 → 【AI 推断】；legacy → 【规则推断】；
  - 产品归属 → 按 《身份血缘》（规则/AI 候选/人工确认分层），confusable 变体低置信标"待确认"。

---

## 7. 默认倾向（草案，落地 PR 评审，**不冻结**）

> 仅描述默认**方向**，不写死数值；所有项运行期可配置。

- 默认开启：未使用奖励、使用次数软降权、近期重复降权、同源重复降权、同 Asset 数量限制。
- 默认关闭：严格未使用硬过滤（需用户显式开启）。
- 默认次数惩罚为**软、带上限、次线性**，不绝对排除（§4.1）。
- 默认 usage 因素**不依赖嵌入**，嵌入降级照常生效（§1.1）。
- 默认 usage 信号缺失（《身份血缘》 投影未回填）时，按"使用情况未知"处理，**不**因此把镜头判为"已使用"或排除（仅在 UI 标注 usage_unknown）。

---

## 7.5 通用产品过滤与查询解析（产品来源 = 动态 Product Catalog）

> 检索**不得依赖当前产品列表**（见《业务需求》§8）。产品过滤来源必须是**动态 Product Catalog**，**不是固定下拉枚举**。

- **查询解析支持的维度**：产品类别 / 产品系列 / 产品变体 / SKU / **动态产品属性**（按 Category 定义，`searchable=true` 的属性可入查询）/
  动作 / 场景 / 景别 / 镜头运动 / 必须包含 / 禁止包含 / 使用策略。
- **产品过滤来源 = Product Catalog**（运行期数据），UI 的产品选项**由目录动态生成**，新增产品**无需改前端或后端代码**。
- **未指定产品**时**不强行绑定**任何产品；解析不出确切产品时返回**候选**而非猜测；**未知产品**进入人工确认。
- **结果显示产品识别依据**（`evidence` / `top_candidates` / `catalog_revision`，证据分层），不伪造产品归属。
- **使用次数排序对全部产品一致生效**（与产品类型无关，见《身份血缘》）。
- confusable 变体按《身份血缘》§1.2「按族 / 按变体」两档，变体级低置信不强判。

---

## 8. 不做（本规格边界）

- 不创建任何数据库迁移 / 不改现有模型 / 不改搜索排序内核 / 不接新模型 / 不下载模型权重（本阶段）。
- 不冻结任何权重、阈值、上限（只列可配置因素与默认倾向）。
- 不重写 Hybrid Search 召回或 `scoring.py` 融合内核（只追加 usage 加权项）。
- 不改动 `document_status` / `embedding_status` 正交语义与嵌入不可用回退（usage 能力不依赖嵌入）。
- 不在此定义全局分配 / 跨段同源去重算法（归 `STORYBOARD_MATCHING_SPEC.md`）。
- 不把 suspected/legacy 计入正式使用次数（与 《身份血缘》 一致）；UI 不伪造"已识别/已匹配/使用次数"。
- 不对软/硬屏做自动断言（与 《身份血缘》 一致），低置信标"未知/待确认"。
