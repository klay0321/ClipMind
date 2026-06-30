# 结构化分镜匹配规格（STORYBOARD_MATCHING_SPEC）

> 阶段：Phase 0 Discovery（需求/规格冻结）。本文件冻结**结构化分镜段字段**与**全脚本分镜匹配流程**
> （多路召回 → 产品硬过滤 → 动作/场景匹配 → 二阶段重排 → 使用次数降权 → 同源去重 → 全脚本全局分配 →
> 锁定保护 → 缺口/补拍建议）的规格。
>
> 业务语境见 `ECOMMERCE_MEDIA_ASSET_REQUIREMENTS.md`（§1 痛点 9：分镜匹配不稳定、同一镜头被塞进多段）；
> 产品身份与使用血缘见 `PRODUCT_IDENTITY_AND_USAGE_LINEAGE_SPEC.md`（产品硬约束、6 级证据、usage_count 规则）；
> 检索召回与使用感知降权见 `USAGE_AWARE_RETRIEVAL_SPEC.md`（同批冻结）。
>
> **本阶段只写规格，不创建任何 Alembic 迁移、不改模型、不改搜索排序、不接新模型、不下载模型权重。**
> 字段与权重为设计草案，落地 PR 再评审。
>
> 标注约定：**[复用]** 现有模型/逻辑可直接承载 / **[扩展]** 现有上加列/加参数/加因子 / **[新增]** 本批新建。
> 证据分层标注：所有自动结论必须标注【事实 / 规则推断 / AI 推断 / 人工确认】，UI 不伪造"已识别/已匹配/使用次数"。

---

## 0. 本规格与现有实现的关系（最重要前置说明）

ClipMind **已经实现** PR-05 脚本匹配（`script_match_service.py` + `clipmind_shared.script.editlist`），
本规格是**对现有 `ScriptSegment` / `ScriptShotCandidate` 的扩展**，不是另起一套。先把"已有什么"说清楚，避免重复造轮子：

| 能力 | 现状 | 出处 | 本规格定位 |
|---|---|---|---|
| 结构化段落需求 | 已有 `structured_requirements`(JSONB)、`product_id` 硬约束、`excluded_risks`、`negative_terms`、`allow_similar_scene/action`、`target_duration_min/max` | `models/script.py` `ScriptSegment` | **[扩展]** 补充字段维度（变体/景别/镜头运动/画幅/使用策略），统一字段字典 |
| 单段多路召回 | 已复用 `run_description_match` → Hybrid Search（语义 + 词法/pg_trgm + 标签 + 产品 + 结构化）；**不另写搜索、不把全量镜头读进 Python、不让 LLM 决定 shot_id** | `script_match_service.build_match_request` / `match_segment` | **[复用]** 召回管线不重写 |
| 候选评分因子 | 已有 `final_score` / `semantic_score` / `lexical_score` / `tag_score` / `product_score` / `quality_score` / `review_bonus` / `risk_penalty` + `matched_reasons` / `unmatched_requirements` / `risk_warnings` | `models/script.py` `ScriptShotCandidate` | **[扩展]** 新增 `usage_penalty` 维度（使用感知降权），并在重排阶段消费 |
| 代次原子替换 | 已有 `current_generation` + `(segment_id, generation, shot_id)` 唯一；旧代次在新代次完整成功前可用 | `match_segment` | **[复用]** 不改 |
| 人工选择/锁定 | 已有 `selected_shot_id` / `locked_shot_id` / `lock_version`（乐观锁，409 冲突）；锁定段重匹配默认跳过 | `select_shot` / `lock_shot` / `match_script(skip_locked=True)` | **[复用]** 锁定保护语义不变 |
| 缺口/补拍建议 | 已有 `derive_match_outcome`（规则派生 `match_status` pending/matched/gap/degraded + `gap_reasons` + `reshoot_recommendation`，**绝不由 LLM 编造**） | `editlist.derive_match_outcome` | **[复用]** 规则派生不变，扩展输入维度 |
| 全局分配 + 同源去重 | **已有雏形** `editlist.allocate`：锁定 > 选择 > 候选分；`max_reuse` 限制单镜头复用、`_adjacent_similar` 避免相邻段相似、`DEDUP_MAX_SCORE_DROP` 不为去重明显降质 | `editlist.allocate` / `build_edit_list` | **[扩展]** 见 §0.1：现状是**剪辑清单派生层的贪心单遍**，且**不感知使用历史**；本规格扩展为使用感知 + 可配置全局分配 |

### 0.1 现状缺口（本规格真正"新增"的部分）

诚实结论：**"全局分配"与"同源去重"在剪辑清单派生层（`editlist.allocate`）已有可用雏形，但有三处缺口**，
这三处才是本规格"新增/扩展"的实质内容，不应被描述成"从零新增全局分配"：

1. **使用感知降权完全缺失**【新增】：现有召回/评分/分配链路**没有任何 `usage_count` / `last_used_at` 反馈**。
   高频素材（"已使用"历史多、被多条成片引用）在候选与分配中**不被降权**，直接违背业务痛点 7/8
   （高频重复露出、未使用素材沉底）。这是本规格最核心的新增维度。
2. **去重只在派生层、不回写候选评分**【扩展】：`editlist.allocate` 是"取数后在 Python 里贪心选一遍"，
   结果**不持久化为 `ScriptShotCandidate` 的分数或排名**，重排逻辑与候选分数两套，解释口径易漂移。
   本规格要求把"使用感知降权"作为可解释因子注入候选评分（`usage_penalty` + `matched_reasons`/`risk_warnings`），
   并让全局分配消费同一份因子，口径统一。
3. **全局分配是贪心单遍，不是全脚本全局优化**【扩展】：`allocate` 按 `order_index` 单遍贪心，
   缺"全脚本视角下的整体冲突消解"（如把稀缺优质镜头让给更需要它的段、跨非相邻段的同源去重预算）。
   本规格冻结**可配置的全局分配目标**（默认仍贪心兜底，允许后续替换为更强分配器），不冻结具体算法/权重。

> 落地边界：以上 1/2/3 的实现拆分到 `USAGE_AWARE_RETRIEVAL_SPEC.md` 指向的落地 PR；
> 本规格**只冻结字段、流程、口径与可配置因素**，**不写迁移、不改排序、不接新模型**。

---

## 1. 结构化分镜段字段（Storyboard Segment Schema）

> **[扩展]** 现有 `ScriptSegment.structured_requirements`(JSONB) + 既有列。本节统一字段字典，落地时
> 既有列保持不变，新增维度优先进 `structured_requirements`（JSONB，免迁移），仅在需要硬约束/索引时再评审建列。
> 每个字段标注**约束类型**：`硬约束`（不满足直接排除候选）/ `软偏好`（影响排序，不排除）/ `展示/建议`（不入排序，仅供人工与清单）。

| 字段 | 中文 | 承载 | 约束类型 | 证据分层 | 说明 |
|---|---|---|---|---|---|
| `product_id` | 产品 | 现有列 [复用] | **硬约束** | 人工确认优先 | 段落要求的产品（族或变体，见 §1.1）。命中靠镜头侧 `confirmed_product_id` / `AssetProduct.active`。 |
| `product_variant_mode` | 产品变体匹配档 | 新增于 JSONB [扩展] | 硬约束 | 人工确认 | `family`（按族过滤，软/硬屏都算）/ `variant`（必须变体级一致）。对接 《身份血缘》 confusable group：变体级默认更严。 |
| `actions` | 动作 | 现有 JSONB key [复用] | 软偏好（`allow_similar_action=False` 时升为硬约束） | AI 推断→人工确认 | 镜头需含的动作标签（type=action）。 |
| `scenes` | 场景 | 现有 JSONB key [复用] | 软偏好（`allow_similar_scene=False` 时升为硬约束） | AI 推断→人工确认 | 镜头需含的场景标签（type=scene）。 |
| `shot_types` | 景别 | 现有 JSONB key [复用] | 软偏好 | AI 推断→人工确认 | 特写/近景/中景/远景等（type=shot_type）。 |
| `camera_movements` | 镜头运动 | 新增于 JSONB [扩展] | 软偏好 | AI 推断→人工确认 | 固定/推/拉/摇/移/环绕等。当前标签体系若无该维度，落地 PR 评审是否新增 `TagType`；本阶段不新增。 |
| `target_duration_min` / `max` | 目标时长 | 现有列 [复用] | **展示/建议（绝不硬过滤）** | 规则推断 | 时长是软偏好；剪辑清单单独算入/出点建议（`compute_duration_suggestion`）。段文本"不超过3秒"等措辞**不据此硬过滤镜头**（现有 `suppress_parsed_duration=True`）。 |
| `must_include` | 必须包含 | 现有 JSONB key [复用] | 软偏好（可升硬约束） | AI 推断→人工确认 | 画面必含元素（产品部位/卖点）。是否硬约束由 `allow_*`/落地策略决定。 |
| `negative_terms` | 禁止包含（词法） | 现有列 [复用] | **硬约束** | 规则推断 | 词法硬排除关键词。 |
| `excluded_risks` | 禁止包含（风险） | 现有列 [复用] | **硬约束** | AI 推断→人工确认 | 风险标签硬排除（type=risk），不静默放宽。 |
| `aspect_ratio` | 画幅 | 新增于 JSONB [扩展] | 软偏好 | 事实（ffprobe 派生） | 目标画幅（如 9:16 / 1:1 / 16:9）。命中靠 `Asset` ffprobe 宽高比【事实】，不裁切源、不生成。 |
| `marketing_uses` | 营销用途 | 现有 JSONB key [复用] | 软偏好 | AI 推断→人工确认 | 卖点展示/开箱/对比等（type=marketing）。 |
| `quality_requirements` | 画质要求 | 现有 JSONB key [复用] | 软偏好 | AI 推断/事实 | 清晰/无抖动等（type=quality）。低码率代理镜头按需降权。 |
| `selling_points` / `people` / `objects` | 卖点/人物/物体 | 现有 JSONB key [复用] | 软偏好（并入自由文本召回） | AI 推断 | 现有 `build_match_request` 已把这些并入 `target_description` 供语义/词法召回。 |
| `usage_policy` | 使用策略 | 新增于 JSONB [扩展] | 软偏好（影响降权强度） | 规则推断（派生自 usage_count/last_used_at） | 见 §1.2。 |

> 字段缺省与回退：任一字段缺失=不约束（不报错、不伪造）。硬约束缺省更安全（产品/风险/词法）；
> 软偏好缺省更宽松（场景/动作/景别等）。**绝不**因软偏好缺失而判定"无匹配"。

### 1.1 产品与产品变体（对接 《身份血缘》 产品身份）

- `product_id` 硬过滤复用现有 `AssetProduct.active` / `ShotReviewState.confirmed_product_id`【人工确认优先】。
- **软屏 vs 硬屏（confusable group）**：`product_variant_mode=variant` 时要求变体级一致；
  变体级判定置信不足 → 不自动命中，进**待人工确认**（继承 《身份血缘》 "confusable 变体默认不自动判定"）。
  `product_variant_mode=family` 时按族过滤（软/硬屏都算候选），由人工在候选里选具体变体。
- **绝不仅凭目录名/文件名确认产品身份**；低置信宁可返回"未知/待确认"也不伪造产品归属。

**分镜输入中的产品可以是任意粒度（产品来源 = 动态 Product Catalog，非固定枚举）**：
精确 SKU / 产品变体 / 产品系列 / 产品类别 / 别名 / 自由文本 / **未指定产品**。匹配时：
1. 先尝试**解析到 Product Catalog**（运行期数据，新增产品无需改代码）；
2. 无法精确解析 → 返回**候选**而非强绑；
3. **未指定产品** → **不强行绑定**任何产品；
4. **未知产品** → 进入人工确认（`unknown_product`，见《身份血缘》§1.5）；
5. 结果显示**产品识别依据**（证据分层）；
6. 使用次数排序对**全部产品一致**生效。
> 系统**不得依赖当前产品列表**；分镜段的 `product_id` 只是"解析结果"，UI 产品选项由目录动态生成（见《业务需求》§8、《通用产品目录》）。

### 1.2 使用策略 `usage_policy`（新增维度，软偏好）

> 控制"使用感知降权"在该段的强度。**软信号、可被人工锁定/选择覆盖、默认不绝对排除**（继承 《身份血缘》 使用次数规则 7）。

| 取值 | 含义 | 行为（草案，权重不在此冻结） |
|---|---|---|
| `prefer_unused`（默认倾向） | 优先未使用/低频镜头 | 未使用奖励 + 高频降权（应对痛点 7/8） |
| `balanced` | 平衡 | 轻度降权，主要看匹配质量 |
| `allow_reuse` | 允许复用 | 几乎不降权（如确需复用某经典镜头） |
| `strict_unused` | 仅未使用 | 仅 `confirmed usage_count=0` 进候选（**硬约束模式，需显式开启**，对应检索规格"严格未使用模式"） |

证据口径（继承 《身份血缘》 6 级证据 + 使用次数规则）：
- 只有 `confirmed_*` 计入正式 `usage_count`，参与降权强度；
- `suspected_*`（视觉/音频疑似）仅作弱信号提示，**默认不计入降权、不绝对排除**，进"待确认引用"；
- `legacy_path_rule`（"已使用"目录历史）仅"可能用过"，**不计入正式次数**，至多 `balanced` 级轻提示。
- 降权理由必须可解释并写入候选 `matched_reasons`/`risk_warnings`（如"该镜头已被 3 条成片确认使用"），
  **UI 不得把降权说成"已用次数"事实之外的结论**。

---

## 2. 匹配流程（单分镜 → 全脚本）

> 总览（阶段 A–C 为单分镜段内；阶段 D–F 为全脚本层）。每阶段标注 [复用]/[扩展]/[新增] 与证据分层。

```text
单分镜段（ScriptSegment）
  A. 多路召回   ── [复用] run_description_match → Hybrid Search（语义+词法+标签+产品+结构化）
  B. 硬过滤     ── [复用/扩展] 产品硬约束 + 风险/词法硬排除 + allow_similar_*=False 的场景/动作硬过滤
  C. 二阶段重排 ── [扩展] 现有评分因子 + 新增 usage_penalty（使用感知降权），写入 ScriptShotCandidate（代次原子替换）
                    ↓（每段产当前代次候选，已含可解释理由/降权理由）
全脚本（ScriptProject 所有段）
  D. 全局分配   ── [扩展] 锁定/选择优先 → 候选综合分 → 同源去重 → 使用预算 → 缺口
  E. 锁定保护   ── [复用] locked/selected 不被覆盖；失效仅标注不静默换片
  F. 缺口/补拍  ── [复用] derive_match_outcome 规则派生 gap_reasons/reshoot（绝不编造素材事实）
```

> **明确禁止（红线，继承现有实现）**：不另写一套搜索；不把全量镜头读进 Python 内存打分；
> 不让 LLM 返回/决定 `shot_id`；不让 LLM 编造匹配理由或素材事实；硬约束不静默放宽。

### 2.A 单分镜多路召回 [复用]

复用 `build_match_request` → `run_description_match`（Hybrid Search）。装配规则不变：
- 自由文本（段文案 + 画面需求 + 卖点 + 必含 + 人物 + 物体）→ 语义向量 + 词法/pg_trgm；
- 结构化软信号（scenes/actions/shot_types/marketing_uses/quality）精确注入对应通道，**不依赖脆弱文本解析**；
- **降级正交**（继承 PR-04）：embedding 不可用时仍 `is_searchable`，回退词法/标签/产品/结构化召回，
  **绝不因嵌入缺失而召回失败**；降级状态记入 `degraded` 并在候选/缺口里如实标注。

### 2.B 产品硬过滤 + 风险/词法/场景动作硬约束 [复用/扩展]

- **产品硬过滤**【复用】：`request.product_id` 下推到召回侧（不在 Python 事后过滤全量）。
  confusable 变体按 §1.1 处理（变体级置信不足→待确认，不自动命中）。
- **风险硬排除**【复用】：`exclude_risks` 命中即排除，不静默放宽。
- **词法否定**【复用】：`negative_terms` 词法硬排除。
- **场景/动作硬过滤**【复用】：`allow_similar_scene=False` / `allow_similar_action=False` 时升为硬约束。
- **时长不参与硬过滤**【复用】：`suppress_parsed_duration=True`，时长只在剪辑清单算建议。

### 2.C 二阶段重排 + 使用次数降权 [扩展，本规格核心新增]

在召回结果上做二阶段重排，复用现有可解释评分因子，**新增 `usage_penalty` 维度**：

| 因子 | 状态 | 来源 | 方向 |
|---|---|---|---|
| `semantic_score` / `lexical_score` / `tag_score` | [复用] | Hybrid Search | 正 |
| `product_score` | [复用] | 产品匹配强度 | 正 |
| `quality_score` | [复用] | 画质/可用性 | 正 |
| `review_bonus` | [复用] | 人工确认加成（confirmed/modified） | 正 |
| `risk_penalty` | [复用] | 风险标签惩罚 | 负 |
| **`usage_penalty`** | **[新增]** | 由 《身份血缘》 `confirmed_usage_count` / `last_used_at` 派生（高频 + 近期重复→更大惩罚），强度受 §1.2 `usage_policy` 调节 | 负 |
| **`unused_bonus`** | **[新增，可选]** | `confirmed_usage_count=0` 的奖励（应对痛点 8 未使用沉底） | 正 |

落地原则：
- **可配置不冻结权重**：本规格只列因子与默认倾向（质量优先、产品硬过滤先行、`prefer_unused` 默认轻降权），
  具体权重在落地 PR 经真实素材评测（见 `../evaluation/COMPANY_MEDIA_BENCHMARK_PLAN.md`）调优，**不在规格冻结**。
- **降权是软信号**：默认只降排序，不绝对排除（`strict_unused` 例外，需显式开启）。
- **可解释**：降权写入候选 `matched_reasons`/`risk_warnings`（"已被 N 条成片确认使用，建议降低复用"）；
  使用数缺失（未建立血缘）时按 `usage_unknown` 处理，**不伪造使用次数、不臆造降权**。
- **代次原子替换**【复用】：重排结果写当前代次 `ScriptShotCandidate`，旧代次在新代次完整成功前可用。

### 2.D 全脚本全局分配 + 同源去重 [扩展]

> **明确：不能再用"每段独立 top-1"。** 现状 `editlist.allocate` 已避免"每段各取 top-1 导致同一镜头塞进多段"，
> 但需扩展为**使用感知 + 可配置预算**的全局分配。

分配优先级（继承现有，扩展预算维度）：
1. **人工锁定 `locked_shot_id`**【复用】：最高优先，占用复用预算，绝不被去重改动。
2. **人工选择 `selected_shot_id`**【复用】：次高优先。
3. **候选综合分**【扩展】：含 2.C 的 `usage_penalty`，即综合分本身已使用感知。

同源去重与预算（扩展 `editlist.allocate` 现有机制）：
- **单镜头复用上限**【复用，可配置】：`max_reuse`（默认 1），超出触发去重换候选；
  `DEDUP_MAX_SCORE_DROP` 控制"不为去重选明显更差镜头"。
- **同源去重**【扩展】：现有 `_adjacent_similar`（同 shot / 同素材且场景动作标签一致）只看**相邻段**；
  扩展为**跨段同源预算**（同一 `asset_id` 在整片出现次数上限可配），避免同素材不同镜头在非相邻段反复露出（痛点 7）。
- **使用预算**【新增】：把 2.C 的使用感知降权延伸到分配层——整片层面优先消化未使用/低频镜头，
  高频镜头即便综合分高也受复用预算约束（软约束，候选不足时允许重复并显式告警）。
- **全局优化目标**【扩展，算法不冻结】：本规格冻结**目标与可配置项**（最大化总匹配质量、最小化重复露出、
  尊重锁定/选择），默认实现仍为确定性贪心（`editlist.allocate` 兜底），允许后续 PR 替换为更强分配器。
  **确定性要求保留**：同输入同输出，便于评测与回归。

### 2.E 锁定保护 [复用]

- 锁定/选择段在全脚本重匹配中默认跳过（`match_script(skip_locked=True)`），不被自动覆盖。
- 锁定/选择镜头即使失效（被删除或审核 rejected/unable）**保留并标注**"已失效请重新选择"，
  **绝不静默换片**（继承 `editlist.allocate` Pass 1）。
- 并发编辑经 `lock_version` 乐观锁，冲突返回 409（继承 `_conditional_update`）。

### 2.F 缺口与补拍建议 [复用]

复用 `derive_match_outcome`（规则派生，**绝不由 LLM 编造素材事实**）：
- 当前代次无候选 = **真实缺口**（不回退旧代次冒充有结果）；
- `gap_reasons` 按硬约束类型陈述（"无符合产品硬约束的镜头：X"、"缺少要求场景/动作"、"排除风险后无可用镜头"、"检索降级结果可能不完整"）；
- `reshoot_recommendation` 按要求类型给补拍提示（"补拍产品 X 的特写/使用镜头"）；
- 扩展：当缺口由**使用预算耗尽**导致（优质镜头都已达复用上限）时，缺口原因应区分
  "素材库无此镜头"与"合规镜头已全部高频使用，建议补拍以降低重复露出"——前者建议补拍，后者亦提示运营复用策略。

---

## 3. 与现有状态机/口径的一致性

| 维度 | 口径（继承） | 出处 |
|---|---|---|
| `match_status` | `pending`（从未匹配）/ `matched` / `gap`（真实无结果）/ `degraded`（降级匹配） | `ScriptSegment.match_status` |
| `requires_human_confirmation` | 低分/降级/缺口需人工确认；**系统推荐第一名 ≠ 人工已确认** | `derive_match_outcome` / `build_edit_list` |
| 使用状态（unused/lightly/heavily/recently/...） | 由 `usage_count` + `last_used_at` + 确认状态派生（部分维度正交） | 《业务需求》 §5 / 《身份血缘》 §4 |
| 证据等级 | 6 级，仅 confirmed 计入正式次数与降权强度 | 《身份血缘》 §3 |
| 审核体系 | `ShotReviewState` + `ReviewEvent` + `ReviewStatus`，append-only、乐观锁、stale | 《身份血缘》 §5 |

---

## 4. 验收原则（贯穿落地 PR）

- **真实素材验收**：分镜匹配/全局分配/使用降权效果，功能完成必须用**公司真实素材 + 真实 Provider**验收；
  CI 可用合成/Fake，但不得以合成素材作为"完成"依据（继承 《业务需求》 §7、真实素材验收制度）。
- **证据分层**：候选理由、降权理由、缺口原因均标注【事实/规则推断/AI 推断/人工确认】，UI 不伪造"已识别/已匹配/使用次数"。
- **可回退/降级正交**：embedding 不可用 → 回退非向量召回继续可用；使用血缘未建立 → 按 `usage_unknown`，不伪造降权；
  全局分配器替换失败 → 回退确定性贪心兜底。
- **确定性**：全局分配同输入同输出，便于评测回归。
- **只读安全**：分镜匹配全程只读镜头/派生事实，**绝不**移动/改名/删除源文件；不裁切源（时长仅给建议入出点）。

---

## 5. 不做（本规格边界）

- 不创建任何数据库迁移 / 不改现有模型 / 不改搜索排序 / 不接新模型 / 不下载模型权重（本阶段）。
- 不在规格中冻结评分/降权/分配权重（只列可配置因素与默认倾向，落地 PR 经真实评测调优）。
- 不把 `suspected_*` / `legacy_path_rule` 自动计入正式使用次数或强制排除（默认软信号）。
- 不对软/硬屏做自动断言（confusable 变体默认进人工确认）。
- 不让 LLM 决定 `shot_id` 或编造匹配理由/素材事实。
- 不做任何生成式视频能力（继承项目硬约束）；"裁切/建议入出点"仅指 FFmpeg 从源派生，不生成、不超出源时间码。
```