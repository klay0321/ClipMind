# 公司内部评测计划（COMPANY_MEDIA_BENCHMARK_PLAN）

> 阶段：Phase 0 Discovery（规格冻结）。本文件冻结 ClipMind 面向**跨境电商产品带货视频生产**场景的
> **公司内部评测体系**：用哪几类评测集、各自的指标、真值来源、规模目标、对应 PR，以及如何在
> **不伪造人工真值**的前提下持续度量产品识别 / 素材搜索 / 成片引用识别 / 分镜匹配的质量。
>
> 配套文档（术语、对象模型、状态机、证据等级须与本文件完全一致）：
> - 业务需求：`../requirements/ECOMMERCE_MEDIA_ASSET_REQUIREMENTS.md`（下称 §业务需求）
> - 产品身份与使用血缘：`../requirements/PRODUCT_IDENTITY_AND_USAGE_LINEAGE_SPEC.md`（下称 §身份血缘）
> - 使用感知检索：`USAGE_AWARE_RETRIEVAL_SPEC.md`
> - 结构化分镜匹配：`STORYBOARD_MATCHING_SPEC.md`
> - 现状差距分析：`CURRENT_SYSTEM_GAP_ANALYSIS.md`
> - 路线图（权威 PR 编号 PR-A..PR-I）：`../roadmap/ECOMMERCE_ASSET_INTELLIGENCE_ROADMAP.md`
>
> **本阶段只写评测规格，不创建 Alembic 迁移、不改模型、不改搜索排序、不接新模型、不下载模型权重。**
> 指标阈值与排序权重**不在本文件冻结**：本文件只列**可配置因素与默认倾向**，具体阈值/权重在落地 PR 评审。

---

## 0. 评测哲学（最高约束）

1. **不自动伪造人工真值**。所有"哪条素材相关 / 哪款产品正确 / 哪条成片引用了哪个镜头 / 哪个镜头最适合该分镜"的
   **真值（ground truth）必须由公司运营 / 剪辑 / 素材管理员人工标注**。系统产出的候选（规则推断 / AI 推断）
   只能作为**待标注的预填项**，**绝不**直接当作真值参与打分。
2. **证据分层贯穿评测**（与 §业务需求 §7、§身份血缘 §3 一致）。每条真值与每条系统结论都携带分层标记：
   **事实 / 规则推断 / AI 推断 / 人工确认**。只有 **人工确认** 的标注进入"金标准（gold）"；
   规则/AI 预填进入"银标准（silver）"，仅用于加速标注与回归对照，不单独定级模型质量。
3. **复用而非重写**。评测**复用现有对象模型与字段**（`Product`/`ProductAlias`/`ProductImage`/`AssetProduct`、
   `Shot`/`ShotTag`/`Tag`、`ShotReviewState`/`ReviewEvent`、Hybrid Search 的 `ShotSearchDocument`、
   `ScriptProject`/`ScriptSegment`/`ScriptShotCandidate`、`Final Video` / `Final Video Usage`）。
   评测**新增**的仅是：评测集容器、标注模板、指标计算脚本与报告（**新增**，不改业务表）。
4. **离线评测，不动源素材**。评测全程遵循只读安全：源目录只读核对（文件数/大小/mtime），派生只写 `/app/data`，
   评测产物（标注、指标、报告）只写受控目录，**绝不**移动 / 改名 / 删除源文件。
5. **真实素材验收优先**（与 §业务需求 §7 一致）。CI 可用合成 / Fake 数据跑通指标脚本的"管线正确性"，
   但**功能是否达标必须用公司真实素材 + 真实 Provider 验收**，**不得**以合成素材作为"达标"依据。
6. **不冻结阈值与权重**。本文件给出指标定义与默认倾向（例如"未使用素材应被优先"），
   但每个指标的**通过线**与排序**权重**在对应落地 PR 评审中确定，可配置、可随数据演进调整。

---

## 1. 评测数据底座（来自只读审计，事实）

评测集的"候选种子"来自一次**严格只读**审计（脚本 `scripts/discovery/audit_material_library.py`，
明细在 git 忽略的 `.local/material-audit/`，**不入库、不进可提交文档**）。可引用的**聚合事实**：

| 维度 | 数值 | 对评测的意义 |
|---|---|---|
| 文件总数 | 190 | 标注工作量上界估算基数 |
| 视频 | 102（疑似源视频 94 / 疑似低码率代理 14） | 搜索集 / 分镜集候选来源 |
| 产品参考图 | 81 | 产品识别集候选来源（每图一条种子） |
| 系统垃圾 | 7 | 评测一律排除 |
| 总体积 | ≈ 4.66 GB | — |
| 顶层目录 | 8（7 个"日期-品类"拍摄目录 + 1 个产品参考图目录） | 拍摄目录名只表达**品类**（汽配/数码/键盘/握把），**不等于产品**，故目录名不可作识别真值 |
| 产品候选（family×variant） | 6 | 产品识别集类目基数 |
| "已使用"证据 | 8（均在 `已使用` 子目录） | 仅 `legacy_path_rule` 级，**只标"可能用过"，不计入正式次数** |
| 能确定使用**次数**的 | 0 | 成片引用识别集真值**无法从现有目录得知**，必须人工 + 工程文件解析建立 |
| 能确定对应**成片**的 | 0 | 同上；本库**疑似成片 = 0**，需运营导入真实成片才能建血缘真值 |
| 字节级精确重复组 | 0 | 印证"已使用靠移动而非复制"，同源去重评测需以**内容身份**（full_hash/quick_hash）而非路径判定 |

> 已知 4 产品（family×variant）：**恶魔之眼软屏 / 恶魔之眼硬屏 / 车换挡握把 / 小键盘**；
> 品类词：**汽配 / 数码 / 键盘 / 握把**。审计另发现易混变体（软屏 vs 硬屏、十字架档把、mini 键盘）需运营确认归并。
> 上述均为可提交内容；**具体媒体文件名、UUID、日期编码目录全名一律不写入本文件**。

### 1.1 审计生成的种子与标注模板（用途说明）

审计已生成可直接用于建集的"**候选种子 + 空真值标注模板**"。它们的作用是**减少运营从零开始的标注量**，
而非提供真值——所有 `relpath` / 文件名都**只存在于本地 `.local/material-audit/`，不抄入任何可提交文档**：

| 文件（本地，不提交） | 用途 | 喂给哪个评测集 |
|---|---|---|
| `benchmark_seed_candidates.csv` | 评测种子总表，列 `benchmark_type`(`product_id`/`search`)、`scope`、`candidate_input`、`expected_note`、`needs_human_truth`。`product_id` 种子 81 条（每张参考图一条）、`search` 种子 94 条（每个疑似源视频一条）。**`needs_human_truth=true` 表示真值必须人工补**。 | 产品识别集（`product_id` 行）、素材搜索集（`search` 行） |
| `query_labeling_template.csv` | 检索查询标注模板，列含 `natural_language_query`、`product_family/variant`、`action`、`scene`、`shot_size`、`must_include/exclude`、`relevant_relpaths`、`notes`。**`relevant_relpaths` 留空待人工填**。 | 素材搜索集 |
| `usage_lineage_labeling_template.csv` | 成片引用标注模板，列含 `final_video_relpath`、`source_asset_relpath`、`source_shot_timecode`、`evidence_level`、`confirmed`、`notes`。**全行待人工 / 工程文件填**。 | 成片引用识别集 |
| `storyboard_labeling_template.csv` | 分镜标注模板，列含 `storyboard_id`、`segment_index`、`product/variant`、`action`、`scene`、`shot_size`、`camera_move`、`target_duration_sec`、`must_include/exclude`、`aspect_ratio`、`risk`、`usage_policy`、`chosen_relpath`、`notes`。**`chosen_relpath`（理想镜头）待人工填**。 | 分镜匹配集 |
| `product_catalog_draft.csv` / `product_alias_draft.csv` / `product_review_queue.csv` | 产品主数据 / 别名 / 待确认问题草案（含软硬屏可见特征与开放问题）。 | 产品识别集类目与混淆组定义 |
| `used_evidence.csv` | "已使用"目录证据（8 条，均 `legacy_path_rule`、`can_determine_count=0`、`can_determine_final=0`）。 | 成片引用识别集的 legacy 负样本 / 弱证据基线 |

> **标注产物去向**：人工填好的真值写入受控评测目录（建议 `.local/benchmark/<set>/gold/`，本地、git 忽略），
> 或落地后入评测专用表（见 §7）；**绝不**把真值或 relpath 写入可提交文档与代码。

---

## 2. 评测集总览（四类 + 一类横切）

| 编号 | 评测集 | 度量能力 | 真值来源 | 对应 PR（路线图） |
|---|---|---|---|---|
| **B1** | 产品识别集 | family/variant 识别、未知拒识、软硬屏混淆 | 运营人工确认产品归属（金标准） | PR-A 产品身份 + PR-F 视觉识别 |
| **B2** | 素材搜索集 | 自然语言检索相关性、排序质量、同源去重、未使用优先 | 运营标注查询↔相关镜头（金标准） | PR-E 使用感知检索（PR-04 Hybrid Search 之上）+ PR-G reranker |
| **B3** | 成片引用识别集 | 成片→源镜头反查、时间码精度、错误使用、确认工作量 | 工程文件解析 + 人工确认引用（金标准） | PR-B 血缘 + PR-D 人工确认 + PR-H 成片反查 |
| **B4** | 分镜匹配集 | 全脚本全局分配、首选可用、产品/动作正确、重复与未使用 | 运营标注理想镜头 + 实际选用（金标准） | PR-I 结构化分镜匹配（PR-05 之上）+ PR-E 使用降权 |
| **B0** | 标注一致性横切集 | 双标注者 IAA（Inter-Annotator Agreement） | 同批样本双人独立标注 | 贯穿 B1–B4，先于各集达标判定 |

> 每个评测集都遵循统一生命周期：**审计种子 → 运营人工标注（金标准）→ 冻结版本（vN）→ 指标脚本计算 → 报告归档**。
> 评测集一旦冻结即打版本号；新增样本进下一版本，**不改历史冻结集**（与"不改历史迁移"同精神）。

---

## 3. B1 产品识别集（Product Identification）

### 3.1 目标与范围

度量"给定一段素材 / 一帧画面，系统判定其 **Product Family / Product Variant** 的准确性"，
重点考核 **软屏 vs 硬屏混淆组**（§身份血缘 §1.2 confusable group）与**未知拒识**（低置信宁可返回未知）。

复用：`Product`(family_id/model=变体名)、`ProductFamily`(扩展)、`ProductAlias`、`ProductImage`、`AssetProduct`、
`ShotReviewState.confirmed_product_id`、`ShotTag`(type=product)。**新增**：仅评测标注与指标脚本。

### 3.2 构建方法

1. 以审计 `benchmark_seed_candidates.csv` 中 `benchmark_type=product_id` 的 81 条（每张参考图一条）为正样本种子，
   外加从疑似源视频抽取的代表帧（FFmpeg 派生关键帧，只读派生，写 `/app/data`）作为视频侧样本。
2. 类目体系来自 `product_catalog_draft.csv`（6 个 family×variant 候选，含混淆组 `confusable_with`）。
3. **运营人工确认**每条样本的 family / variant 真值；混淆组样本必须由能区分软硬屏可见特征的人确认
   （特征清单见 §身份血缘 §1.3）。
4. 加入**未知 / 拒识样本**：故意混入无明确产品归属或产品外的画面，真值标为 `unknown`，用于考核拒识。

### 3.3 真值来源与分层

- 金标准 = **人工确认**（`AssetProduct.active=true` / `ShotReviewState.confirmed_product_id`）。
- 规则推断（目录/文件名命中）与 AI 推断（视觉 Provider）**只作预填**，进银标准，不定级。
- 与 §身份血缘 §1.4 一致：**绝不只根据目录名最终确认产品身份**；目录品类词不得作真值。

### 3.4 规模目标

- 起步：≥ 81 张参考图全覆盖 + ≥ 60 段视频代表帧；其中**混淆组（软/硬屏）≥ 30 对**，**未知样本 ≥ 20**。
- 目标：family 每类 ≥ 30 样本、variant 每个 ≥ 20 样本，未知样本占比 ≈ 15–20%（保证拒识统计显著）。

### 3.5 指标

| 指标 | 定义 | 默认倾向（不冻结阈值） |
|---|---|---|
| **Family Top-1** | 识别族正确率（最高分候选 = 真值族） | 越高越好；族级应显著高于变体级 |
| **Variant Top-1** | 识别变体正确率（含软/硬屏） | 重点；混淆组上单列 |
| **Top-3** | 真值变体落在前 3 候选的比例 | 召回兜底，用于审核预填质量 |
| **Unknown rejection rate（未知拒识率）** | 真值=unknown 的样本被正确判为"未知/待确认"的比例 | **高于强行识别**：宁可拒识，避免伪造软硬屏归属 |
| **错判为已知率（false-known rate）** | 真值=unknown 却给出确定产品判定的比例 | 越低越好；混淆组上严控 |
| **混淆矩阵（Confusion Matrix）** | family×variant 真值 vs 预测矩阵，单列 confusable group 子矩阵 | 软屏↔硬屏互错为重点观测格 |
| **变体区分阈值命中率** | confusable 组内仅当置信 ≥ 变体区分阈值才自动判定的命中比例 | 该阈值**可配置**，默认高于普通产品阈值 |

> 报告须同时给出**整体**与**混淆组隔离**两套数字；混淆组指标不达标即视为产品识别不达标，不被整体高分掩盖。

### 3.6 通用化子评测 A–F（不只在当前产品随机切分）

> 产品识别评测**必须验证通用性**，不能只在当前 seed 产品上随机切分（会因近似画面泄漏而虚高）。下设 6 类子评测：

| 子评测 | 目的 | 构建要点 |
|---|---|---|
| **A 已知产品识别** | 同一产品不同视频/角度/背景的识别稳定性 | 每产品多视频、多角度、多背景样本 |
| **B 相似变体识别** | 高相似变体区分（首组 = 软屏 vs 硬屏混淆案例） | confusable group 内成对样本，单列混淆子矩阵 |
| **C 跨品类识别** | 不同 Product Category 之间区分 | 跨类别样本，验证不串类 |
| **D 新产品冷启动** | 加入**从未参与调优**的新产品，仅少量参考图 | 分别测 **1 / 3 / 5 / 10 张参考图**下的识别效果，度量"少样本上线"能力 |
| **E 未知产品拒识** | 输入不在公司 Catalog 的产品 / 无产品画面 | 系统应输出 `unknown_product` / `no_product_visible`，**不强制猜测** |
| **F 产品留出评测** | 防数据泄漏（同视频/近似画面既进训练又进测试） | **按产品 / 按变体 / 按拍摄批次 / 按场景留出**，绝不仅随机切分同一产品素材 |

**留出纪律（强约束）**：训练/调优集与测试集**不得**共享同一视频或近似画面；同一拍摄批次不得跨越两侧；
冷启动（D）的新产品**绝不**出现在任何调优数据中。这是"是否真正通用、而非过拟合 seed"的核心防线。

**扩展指标（在 §3.5 基础上补全）**：Family Top-1 / Variant Top-1 / **SKU Top-1** / Top-3 /
**Unknown Recall** / **Unknown Precision** / **Macro F1**（跨类别均衡，避免大类掩盖小类）/
Confusion Matrix（含 confusable 子矩阵）/ **Calibration Error**（置信度校准，避免过度自信误导人工）/ **人工确认率**。

> D（冷启动）与 F（留出）是产品识别通用性的核心门禁，**优先级高于在 seed 上刷高分**；A/B/C/E 覆盖已知/混淆/跨类/拒识。

---

## 4. B2 素材搜索集（Asset / Shot Search）

### 4.1 目标与范围

度量"运营/剪辑输入自然语言查询，系统返回相关镜头"的**相关性、排序质量**，并新增度量
**同源去重**与**未使用素材优先**（对应 §业务需求 §1 第 6/7/8 条痛点）。

复用：PR-04 Hybrid Search（语义向量 + 词法/pg_trgm + 标签 + 产品 + 结构化召回）、`ShotSearchDocument`
（`document_status` 与 `embedding_status` **正交**：嵌入不可用仍 `is_searchable`、继续非向量召回）、
E5 本地 embedder（384 维）+ pgvector HNSW、产品硬过滤、使用感知排序（落地 PR）。**新增**：查询集与指标脚本。

### 4.2 构建方法

1. 以审计 `benchmark_seed_candidates.csv` 中 `benchmark_type=search` 的 94 条（每个疑似源视频一条）为镜头候选池。
2. 运营用 `query_labeling_template.csv` 编写**真实业务查询**（自然语言 + 结构化标签：产品/动作/场景/景别 + must_include/exclude）。
   查询应覆盖：产品检索、动作检索、场景检索、景别检索、混合检索、含产品硬约束的检索。
3. 对每条查询，运营在候选池中**人工标注相关镜头集合**（`relevant_relpaths`，可分级：高度相关/相关/不相关）。
4. 标注"**同源**"分组（同一 Asset 的多个 Shot、或内容身份相同的移动副本）以支持同源去重评测；
   同源判定以**内容身份**（quick_hash/full_hash，§身份血缘 §6）而非路径，呼应"已使用靠移动、0 字节级重复"。
5. 标注每条镜头的**使用状态**（来自使用血缘投影：never_used / used_once / used_multiple / overused …，7 态见《业务需求》§5）以支持"未使用优先"评测。

### 4.3 真值来源与分层

- 金标准 = 运营**人工标注**的查询↔相关镜头映射（事实/人工确认）。
- 系统召回（语义/词法/标签/结构化）只作预填顺序，不作真值。
- "未使用 / 已使用"状态真值来自使用血缘的 **confirmed/ legacy 标记**，与 B3 共享口径。

### 4.4 规模目标

- 起步：≥ 30 条查询，覆盖 4 产品 × 主要动作/场景；每条查询平均 ≥ 5 个已标注相关镜头。
- 目标：≥ 60 条查询；其中**含同源多镜头的查询 ≥ 15 条**、**含未使用素材应优先的查询 ≥ 15 条**。

### 4.5 指标

| 指标 | 定义 | 默认倾向（不冻结阈值） |
|---|---|---|
| **Precision@5** | 前 5 结果中相关比例 | 越高越好 |
| **Recall@10** | 前 10 结果覆盖标注相关镜头的比例 | 越高越好 |
| **NDCG@10** | 前 10 结果的分级相关性排序质量 | 主排序质量指标 |
| **首个可用结果排名（Rank of First Usable）** | 第一个"相关且可用（未过度使用/产品正确）"结果的位次 | 越小越好；体现剪辑实际体验 |
| **不相关率（Irrelevant Rate）** | 前 K 中被标注"不相关/产品错误"的比例 | 越低越好；产品硬过滤应压低 |
| **同源重复率（Same-Source Duplicate Rate）** | 前 K 中来自同一内容身份/同一 Asset 的重复镜头比例 | **越低越好**：同源去重生效则下降 |
| **未使用素材占比（Unused Coverage@K）** | 前 K 结果中"未使用/低频"素材占比 | 在相关前提下**越高越好**：体现未使用奖励排序 |

> **降级正确性**（与 §业务需求 §7 可回退一致）：嵌入不可用时，B2 必须仍可跑——
> 关闭向量召回后用词法/标签/结构化召回，指标允许下降但**不得为 0**（验证 `is_searchable` 正交性）。
> 排序权重（语义/词法/标签/产品/质量/使用降权/未使用奖励）**全部可配置、本文件不冻结**，只记录默认倾向。

---

## 5. B3 成片引用识别集（Final Video Usage Lineage）

### 5.1 目标与范围

度量"给定一条**成片（Final Video）**，系统反查出它**引用了哪些源镜头（Shot）**及对应**时间码**"的能力，
并度量**错误使用计数**与**人工确认工作量**。对应 §业务需求 §1 第 4/5 条与 §身份血缘 §2–§4。

复用：`Final Video`(新增)、`Final Video Usage`(新增，带 `evidence_level`/`confirmed`/时间码/JSONB 证据)、
`ShotReviewState`/`ReviewEvent`（审核 append-only、乐观锁、stale）、使用次数投影规则（§身份血缘 §4）。
引用链：`Final Video →(Final Video Usage)→ Shot → Asset → Product`。

### 5.2 构建方法（真值最难，必须人工 + 工程文件）

1. **本库疑似成片 = 0**，故 B3 真值**不能**从现有素材库直接建立；需运营**导入真实成片**
   （`Final Video.source_type`：`uploaded_mp4`/`editor_project`/`external_link`/`manual`）。
2. 优先用**剪辑工程文件解析**（`.prproj`/`.fcpxml`/`.edl`/剪映工程）建立**高置信引用真值**
   → 证据等级 `confirmed_editor_project`（计入正式次数）。
3. 无工程文件的成片由剪辑/运营**人工逐条确认**"此成片在某时间码用了此源镜头"→ `confirmed_manual`。
4. 审计 `used_evidence.csv`（8 条 `legacy_path_rule`）作为**弱证据/负样本基线**：
   验证系统**不会**把"已使用目录"自动当作确定引用（`can_determine_count=0`、`can_determine_final=0`）。
5. 用 `usage_lineage_labeling_template.csv` 收集真值（成片 relpath ↔ 源镜头 ↔ 时间码 ↔ evidence_level ↔ confirmed）。

### 5.3 真值来源与分层（与证据 6 级严格对齐）

| evidence_level | 进金标准? | 计入正式次数? | 在 B3 中的角色 |
|---|---|---|---|
| `confirmed_editor_project` | 是 | 是 | 主真值来源 |
| `confirmed_manual` | 是 | 是 | 主真值来源 |
| `confirmed_clipmap_export` | 是 | 是 | 回填真值（ClipMind 导出清单回填） |
| `suspected_visual_match` | 否（待确认） | 否 | 系统预测，待人工确认后才入金标准 |
| `suspected_audio_match` | 否（待确认） | 否 | 同上 |
| `legacy_path_rule` | 否 | 否 | 负/弱样本，仅"可能用过" |

> **绝不**把 suspected/legacy 自动当真值或自动计入次数（§身份血缘 §3–§4、§业务需求 §6 非目标第 5 条）。

### 5.4 规模目标

- 起步：≥ 10 条真实成片，其中 ≥ 5 条带剪辑工程文件（建高置信引用），合计 ≥ 50 条引用真值。
- 目标：≥ 30 条成片，覆盖 4 产品；引用真值 ≥ 200 条；含 legacy 弱证据负样本 ≥ 8。

### 5.5 指标

| 指标 | 定义 | 默认倾向（不冻结阈值） |
|---|---|---|
| **Precision（引用精确率）** | 系统给出的引用中真正引用的比例 | 越高越好；错误引用代价高 |
| **Recall（引用召回率）** | 真值引用中被系统找出的比例 | 越高越好；尽力而为，不承诺 100% |
| **时间码误差（Timecode Error）** | 预测 `source_timecode_*` / `final_timecode_*` 与真值之差（秒/帧），报告中位数与 P90 | 越小越好；超阈值算"定位失败" |
| **错误使用计数率（False Usage Count Rate）** | 把"未确认/弱证据"误计入正式 `usage_count` 的比例 | **应为 0**：只有 confirmed 计入次数（硬约束验证） |
| **人工确认工作量（Human Confirmation Effort）** | 达到目标 Precision/Recall 所需的人工确认动作数 / 引用条数（如确认率、平均每成片确认条数） | 越低越好；度量 suspected→confirmed 审核成本 |

> B3 同时是"**证据分层不被伪造**"的守门测试：UI/统计中 suspected/legacy 必须显示为"待确认/可能用过"，
> **不得**伪造"已确认引用 / 使用次数"。该断言失败直接判 B3 不达标。

---

## 6. B4 分镜匹配集（Storyboard / Script Matching）

### 6.1 目标与范围

度量"导入**脚本/分镜（Storyboard）**后，系统为每段（Segment）找到合适镜头"的能力，
重点考核现状缺失的三项：**全脚本全局分配**、**同源去重**、**使用感知降权**（§业务需求 §1 第 9 条）。

复用：PR-05 `ScriptProject`/`ScriptSegment`（`structured_requirements` JSONB、`product_id` 硬约束、
`target_duration_min/max`、`selected_shot_id`/`locked_shot_id`、`match_status` pending/matched/gap/degraded、reshoot 建议）、
`ScriptShotCandidate`（已有评分因子 `final_score`/`semantic_score`/`lexical_score`/`tag_score`/`product_score`/
`quality_score`/`review_bonus`/`risk_penalty` + `matched_reasons`/`unmatched_requirements`/`risk_warnings`）。
**新增（落地 PR，本阶段不实现）**：全局分配求解、同源去重约束、使用感知降权因子。本文件仅评测之。

### 6.2 构建方法

1. 运营用 `storyboard_labeling_template.csv` 编写**真实分镜脚本**（多段，含产品/变体硬约束、动作、场景、景别、
   机位、目标时长、宽高比、风险、`usage_policy`=优先未使用 等）。
2. 对每段，运营标注**理想镜头**（`chosen_relpath`，可多个候选并分级）作为金标准；
   并标注"**禁止同一镜头被塞进多段**"等全局约束。
3. 设计**缺口探针段**（gap probe）：故意写库内无满足镜头的段，验证系统返回 `gap`/`degraded` + reshoot 建议，
   而**不**强行塞入不相关镜头（呼应 PR-05 真实基线发现的内容缺口）。
4. 标注每条镜头的使用状态与同源分组（与 B2 共享口径），用于"重复镜头率""未使用采用率"。

### 6.3 真值来源与分层

- 金标准 = 运营标注的**每段理想镜头集合** + **实际选用镜头**（人工确认）。
- 系统候选（`ScriptShotCandidate`）只作预填，不作真值。
- 产品硬约束真值来自 B1 的产品识别金标准；使用状态真值来自 B3/使用血缘投影。

### 6.4 规模目标

- 起步：≥ 5 条分镜脚本（覆盖 4 产品），合计 ≥ 30 段；含**缺口探针段 ≥ 4**。
- 目标：≥ 15 条脚本、≥ 120 段；含同源约束段 ≥ 15、使用降权相关段 ≥ 15。

### 6.5 指标

| 指标 | 定义 | 默认倾向（不冻结阈值） |
|---|---|---|
| **Candidate Recall@10** | 每段前 10 候选覆盖该段理想镜头的比例 | 越高越好；召回是匹配上限 |
| **首选可用率（Top-1 Usable Rate）** | 每段排第一的候选"可用（产品对、动作对、未过度使用）"的比例 | 越高越好；直接影响剪辑效率 |
| **产品错误率（Product Error Rate）** | 候选/选用镜头违反该段产品硬约束的比例 | **应趋近 0**：产品硬约束为硬过滤 |
| **动作错误率（Action Error Rate）** | 选用镜头动作与该段要求不符的比例 | 越低越好 |
| **人工替换率（Human Replacement Rate）** | 剪辑把系统首选替换为其他镜头的段比例 | 越低越好；度量首选信任度 |
| **重复镜头率（Duplicate Shot Rate）** | 整脚本中同一镜头/同源内容被分配到多段的比例 | **越低越好**：全局分配 + 同源去重生效则下降 |
| **未使用素材采用率（Unused Adoption Rate）** | 最终方案中"未使用/低频"镜头被采用的比例 | 在满足需求前提下**越高越好**：使用感知降权生效 |
| **缺口识别正确率（Gap Detection Accuracy）** | 缺口探针段被正确判为 `gap`/`degraded` 且给 reshoot 建议、未强塞镜头的比例 | 越高越好；防伪造匹配 |

> B4 在"**单段独立产候选**"（现状 PR-05）与"**全脚本全局分配 + 同源去重 + 使用降权**"（落地后）两种模式下分别跑分，
> 报告并列对照，量化全局分配带来的**重复镜头率下降 / 未使用采用率上升**。匹配权重**可配置、本文件不冻结**。

---

## 7. B0 标注一致性横切集（Inter-Annotator Agreement）

> 真值由人工标注，必须先证明"人工真值本身可靠"，否则模型指标无意义。

- **方法**：从 B1–B4 各抽样一批样本，由 ≥ 2 名运营/剪辑**独立**标注，计算一致性。
- **指标**：分类类（产品 family/variant、动作、是否相关）用 **Cohen's / Fleiss' Kappa**；
  集合类（相关镜头集、引用集）用 **集合 F1 / Jaccard**；时间码用**误差分布一致性**。
- **门槛（默认倾向，不冻结具体 Kappa 值）**：低于约定一致性的维度，**先统一标注规范 / 培训 / 仲裁**，
  再开放该维度建金标准；**不达一致性的维度不得用于给模型定级**。
- **争议仲裁**：分歧样本由第三方（主管/资深剪辑）仲裁，仲裁结果入金标准并记录 `ReviewEvent`（append-only）。

---

## 8. 评测运行与产物（复用现有审核与导出体系）

1. **标注存储**：人工真值落本地受控目录（`.local/benchmark/<set>/gold/`，git 忽略）；
   落地 PR 可引入评测专用投影表（**新增**，不改业务表），复用 `ReviewEvent` 风格的 append-only 审计记录标注历史。
2. **指标计算**：**新增**纯离线指标脚本（建议 `scripts/evaluation/`），输入 = 系统结果导出 + 金标准，
   输出 = 指标 JSON + 报告。脚本**只读** gold 与系统导出，不回写业务库。
3. **报告归档**：每次评测产出版本化报告（评测集版本 vN + 系统版本 + Provider 版本 + 指标表 + 混淆矩阵 +
   失败样本清单的**脱敏 ID**）。报告**不含**媒体文件名 / relpath / UUID，只含聚合数字与脱敏样本 ID。
4. **CI 与真实双轨**：CI 用合成/Fake 数据验证**指标脚本正确性**（管线绿）；
   **达标判定**用真实素材 + 真实 Provider（MiMo 视觉/文本、E5 embedder）离线跑，结论人工审阅。
5. **只读核对**：任何涉及源目录的派生（关键帧抽取等）前后核对文件数/大小/mtime，派生只写 `/app/data`。

---

## 9. 评测集 ↔ PR ↔ 能力对照（汇总）

| 评测集 | 度量能力 | 真值来源 | 规模目标（起步→目标） | 对应 PR |
|---|---|---|---|---|
| **B1 产品识别** | family/variant Top-1、Top-3、未知拒识、混淆矩阵 | 运营人工确认产品归属 | 81 图+60 帧 → 各类 ≥20–30、未知 15–20% | PR-A 产品身份 + PR-F 视觉识别 |
| **B2 素材搜索** | P@5、R@10、NDCG@10、首个可用排名、不相关率、同源重复率、未使用占比 | 运营标注查询↔相关镜头 | 30 查询 → 60 查询 | PR-E 使用感知检索（PR-04 之上）+ PR-G |
| **B3 成片引用** | Precision、Recall、时间码误差、错误使用计数率、人工确认工作量 | 工程文件解析 + 人工确认 | 10 成片/50 引用 → 30 成片/200 引用 | PR-B 血缘 + PR-D 确认 + PR-H 反查 |
| **B4 分镜匹配** | Candidate Recall@10、首选可用率、产品/动作错误率、人工替换率、重复镜头率、未使用采用率、缺口识别 | 运营标注理想镜头+实际选用 | 5 脚本/30 段 → 15 脚本/120 段 | PR-I 结构化分镜匹配（PR-05 之上） |
| **B0 一致性** | Kappa / 集合 F1 / 时间码一致性 | 双标注者独立标注 | 各集抽样双标 | 贯穿 B1–B4，先于定级 |

---

## 10. 不做（本评测计划边界）

1. **不自动伪造任何人工真值**；规则/AI 预填只加速标注，不参与定级。
2. **不冻结指标阈值与排序/匹配权重**；只列可配置因素与默认倾向。
3. **不在本阶段创建迁移 / 改模型 / 改搜索排序 / 接新模型 / 下载模型权重**；评测脚本与表为落地 PR 内容。
4. **不动源素材**；评测全程只读核对，派生只写 `/app/data`，真值/报告只写受控目录。
5. **不把媒体文件名 / relpath / UUID / 日期编码目录全名写入可提交文档与报告**；只用聚合数字与脱敏 ID。
6. **不以合成/Fake 数据作为达标依据**；达标须真实素材 + 真实 Provider 验收。
