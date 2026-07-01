# 跨境电商素材智能化 PR 路线图（ECOMMERCE_ASSET_INTELLIGENCE_ROADMAP）

> 阶段：Phase 0 Discovery（路线冻结）。本文件是同批 Phase 0 文档引用的**权威 PR 编号来源**，
> 把"业务需求 / 产品身份与使用血缘 / 使用感知检索 / 结构化分镜 / 评测 / 开源评估"落到一组**小步可验收**的 PR。
>
> 上游事实来源（术语/对象模型/状态机/证据等级须完全一致）：
> - 业务需求：`../requirements/ECOMMERCE_MEDIA_ASSET_REQUIREMENTS.md`（下称《业务需求》）
> - 产品身份与使用血缘：`../requirements/PRODUCT_IDENTITY_AND_USAGE_LINEAGE_SPEC.md`（下称《身份血缘》）
> - 使用感知检索：`../requirements/USAGE_AWARE_RETRIEVAL_SPEC.md`
> - 结构化分镜匹配：`../requirements/STORYBOARD_MATCHING_SPEC.md`
> - 现状差距分析：`../requirements/CURRENT_SYSTEM_GAP_ANALYSIS.md`
> - 评测计划：`../evaluation/COMPANY_MEDIA_BENCHMARK_PLAN.md`
> - 开源评估：`../technical/OPEN_SOURCE_REUSE_EVALUATION.md`
>
> **本阶段不执行任何代码/迁移**；本文件只冻结 PR 拆分、顺序、边界与验收口径。

---

## 0. 拆分原则与总览

**核心判断（来自差距分析）**：ClipMind 的"理解—审核—检索—匹配—导出"主干（PR-01..PR-06）已稳定成熟。
本批新需求**绝大多数是在其上扩展/新增/投影**，**最大的全新缺口是"使用血缘"**。因此路线图遵循：

1. **小步可验收**：禁止把所有需求塞进一个巨型 PR；每个 PR 有独立输入/输出/验收。
2. **数据层先行，能力层后置**：先建产品身份与使用血缘的"事实存储"，再做检索/分镜的"消费"，最后做实验性视觉/视频识别。
3. **不推翻已稳定功能**：一律 [扩展]/[新增]/[投影]，不反向改造 PR-01..PR-06 主结构。
4. **每个能力可降级/回退**：视觉识别失败回退名称/目录规则；嵌入不可用回退非向量召回；全局分配器失败回退确定性贪心。
5. **真实素材 + 真实 Provider 验收**：CI 可用合成/Fake，但"达标"必须真实素材；评测用《评测计划》四套基准。

### 0.1 PR 一览

| PR | 标题 | 类型 | 关键产物 | 依赖 | GPU | NAS |
|---|---|---|---|---|---|---|
| **PR-A1** | 通用产品目录核心 | 新增（一次性基础 Schema） | Category/Family/Variant/SKU/Alias + 生命周期/更名/归档/合并重定向基础 + 基础 API + 基础管理 UI | PR-03B | 否 | 友好 |
| **PR-A2** | 动态属性、参考图库与产品入驻 | 新增 | ProductAttributeDefinition/Value、ProductReferenceAsset + 角度、ProductConfusionPair、参考完整度、入驻工作流、Catalog Revision | **PR-A1 已合并 main** | 否 | 友好 |
| **PR-B** | 成片与 Shot 使用血缘数据模型 | 新增为主 | `final_video`、`final_video_usage`、`shot_usage_stat`、Asset `usage_rollup` | PR-A1 | 否 | 友好 |
| **PR-C** | 历史"已使用"证据导入 + 稳定 Asset 身份 | 扩展+新增 | `asset_path_history`、legacy 证据导入、content identity 匹配策略 | PR-B | 否 | 友好 |
| **PR-D** | 使用中心与人工确认 | 复用为主 | `usage_review` 并行域、使用中心前端、工程文件解析 | PR-B、PR-C | 否 | 友好 |
| **PR-E** | 使用感知检索与排序 | 扩展为主 | `usage_score` 通道、未使用奖励、同源去重、可配权重 | PR-B | 否 | 友好 |
| **PR-F** | 视觉产品识别实验 Provider | 新增（实验） | Grounding DINO / CLIP 视觉识别 Provider（候选，强制人工确认） | PR-A2 | 可选 | 离线批可行 |
| **PR-G** | 多路召回与重排 | 扩展 | BGE Reranker 填 `rerank_candidates` 空槽、可选视觉嵌入通道 | PR-E | 可选 | 受控可行 |
| **PR-H** | 成片反向引用识别 | 新增（实验） | 视觉(pHash/DINOv2)/音频(Chromaprint) `suspected_*` 反查 | PR-B、PR-D | 可选 | 离线批可行 |
| **PR-I** | 结构化分镜全局匹配 | 扩展 | `editlist.allocate` 全局分配 + 同源去重 + 使用感知降权 | PR-E | 否 | 友好 |

> 依赖关系：**PR-A1 → PR-A2** → PR-B → (PR-C, PR-D, PR-E) → (PR-F, PR-G, PR-H, PR-I)。
> **不建 stacked PR**：PR-A2 须等 PR-A1 合并入 `main` 后再从 `main` 开新分支；PR-F 依赖 PR-A2（需参考图/混淆组）。
> PR-G/PR-H/PR-I 相对独立，可按价值与资源排程；视觉/视频/音频类（PR-F/G/H）须先过《开源评估》许可证审计清单。
>
> **建表 vs 加数据（决策 6）**：PR-A1 一次性建立通用基础 Schema **须用正式 Alembic migration**；此后**新增产品 / 属性是纯数据、免迁移**。

---

## 1. 逐 PR 详述

> 每个 PR 统一给出：**输入 / 输出 / 数据迁移 / API / UI / 测试 / 真实数据验收 / 风险 / 回退 / GPU / NAS**。

> **PR-A 拆为 PR-A1（目录核心）+ PR-A2（动态属性/参考图/入驻），不建 stacked PR**：PR-A2 须等 PR-A1 合并入 `main` 后再开分支。
> **下一实现分支 = `feat/generic-product-catalog-core`（PR-A1）**。当前 Discovery PR 不实现任何 PR-A 代码。

### PR-A1 通用产品目录核心

> **不是"为当前 4 个产品建产品表"**，而是**通用产品目录核心基础设施**：运营能新增**任意**当前/未来产品（不同品类、变体、SKU），**开发不需改代码**。当前 4 产品仅作 **seed 验收数据**。详见《通用产品目录》《业务需求》§9 决策。

- **范围**：`ProductCategory` / `ProductFamily` / `ProductVariant` / `ProductSKU` / `ProductAlias`（多语言 + 文件夹别名）；产品生命周期（Draft→Active→Paused→Archived 基础态）；**产品更名（稳定 ID 不变）**；**产品归档**；**产品合并 / 重定向基础**（保留旧 ID + 历史关系）；基础 API；基础管理 UI。
- **明确不做**：动态属性、产品参考图、自动视觉识别、使用血缘、使用次数、检索排序、分镜匹配（归 PR-A2 / PR-B+）。
- **输入**：现有 `Product`/`ProductAlias`/`ProductImage`/`AssetProduct`（PR-03B，扩展层级）；审计 `product_catalog_draft.csv` 等（本地，运营据此**录入 seed**，非架构依赖）。
- **输出**：通用动态产品目录核心；运营可新增任意产品（Family 核心实体，Category 建议必填，Variant/SKU 可选）。
- **数据迁移**：**一次性建立通用基础 Schema，须用正式 Alembic migration**（新增 `product_category`/`product_family` 等表 + `product.family_id`/`category_id` 外键、合并重定向表；**产品本身是数据行，不是枚举/CHECK**）；不改历史迁移。**此后新增产品是纯数据、免迁移。**
- **API**：Category/Family/Variant/SKU/Alias CRUD；生命周期/更名/归档/合并；按类别/族/变体/SKU 的**动态**过滤（来源 = 目录，非固定枚举）。
- **UI**：产品目录管理（类别-族-变体树、生命周期、更名/合并）；**产品选项由目录动态生成**。
- **测试**：新增产品**无需改代码/无需再迁移**；产品名**不进任何 Enum/CHECK/Prompt/UI 固定选项**；更名保留稳定 ID；合并保留旧 ID + 重定向 + 历史关系；至少 **2 个不同类别 seed 产品** 可建；反硬编码 CI 护栏（生产模块不得 import seed 产品常量）。
- **真实数据验收**：运营**实际新增**至少 2 类别 seed 产品（开发零介入）；6 候选录入并标 seed。**软/硬屏混淆组归 PR-A2；成片样本不阻塞 PR-A1。**
- **风险**：误把当前产品写进代码逻辑（见《通用化风险审查》20 项）；合并/重定向的引用解析路径须唯一。
- **回退**：层级外键可空，缺失时退化为现有扁平 `Product`，不破坏 PR-03B。
- **GPU**：否。**NAS**：友好（纯数据/CRUD）。

### PR-A2 动态属性、参考图库与产品入驻

> **依赖：PR-A1 已合并入 `main`**（非 stacked PR，从 `main` 新开分支）。

- **范围**：`ProductAttributeDefinition` / `ProductAttributeValue`（受类型约束的动态属性，7 种 value_type，按 Category）；`ProductReferenceAsset` + **参考图角度（12）**；`ProductConfusionPair`（混淆组）；**产品参考完整度**；**新产品入驻工作流**（14 步 + 6 态 Draft/reference_incomplete/evaluation_required/active/paused/archived）；`ProductCatalogRevision`（版本化）。
- **明确不做**：自动视觉识别（PR-F）、使用血缘（PR-B）、检索排序（PR-E）。
- **数据迁移**：一次性建属性/参考图/混淆/版本等表（正式 Alembic migration）；此后新增属性定义/属性值/参考图/版本是**纯数据、免迁移**。
- **API/UI**：属性定义/值、参考图（角度/完整度）、混淆组、入驻向导、Catalog Revision。
- **测试**：动态属性增删**免迁移** + 版本；参考图 1 张起（3 张建议最低、5 张+适合视觉识别）；入驻 Draft→Active 前置条件；**1 组相似变体（软/硬屏）混淆组**可建（差异特征人工提供）。
- **真实数据验收**：运营为 seed 产品配置动态属性 + 上传参考图 + 标角度 + 建软/硬屏混淆组并发布产品版本。
- **风险**：动态属性失控 → "稳定核心 + 受 Definition 约束的 attributes"，非自由 JSON。
- **回退**：属性/参考图为可选扩展，缺失退化为 PR-A1 纯目录，不破坏 PR-A1。
- **GPU**：否。**NAS**：友好。

### PR-B 成片与 Shot 使用血缘数据模型

- **目标**：建立"成片→源镜头"引用链与使用次数事实存储（最大的全新缺口）。
- **输入**：现有 `Shot`/`Asset`；PR-A1 的产品层级。
- **输出**：`Final Video`、`Final Video Usage`（6 级证据）、Shot/Asset 使用统计投影；引用链 `Final Video →(Usage)→ Shot → Asset → Product` 可查询。
- **数据迁移**：新增 `final_video`、`final_video_usage`（`evidence_level`/`confirmed`/时间码/JSONB 证据，`shot_id`/`asset_id` SET NULL）、`shot_usage_stat` 投影表；Asset `usage_rollup`（物化或视图）。枚举 `EvidenceLevel`(6)/`UsageStatus`(8)。**新迁移**。
- **API**：成片导入/查询；使用记录写入/查询；使用统计只读（usage_count/last_used_at/被哪些成片使用）。
- **UI**：最小（数据层为主，使用中心 UI 在 PR-D）。
- **测试**：投影重算幂等（删除/驳回后重算）；仅 confirmed 计入 usage_count；suspected/legacy 不计入；引用链查询；SET NULL 引用保护。
- **真实数据验收**：导入 ≥10 条真实成片（运营提供，本库疑似成片=0），建立 ≥50 条引用真值（《评测计划》B3）。
- **风险**：投影重算正确性；成片自身只读约束（受控 storage_path，绝不写源目录）。
- **回退**：纯新增表，不影响既有检索/审核；未建血缘时检索按 `usage_unknown` 兜底。
- **GPU**：否。**NAS**：友好。

### PR-C 历史"已使用"证据导入 + 稳定 Asset 身份

- **目标**：把 NAS 历史"已使用"目录/后缀作为 legacy 证据导入；保证素材移动后仍识别为同一 Asset。
- **输入**：审计 `used_evidence.csv`（8 条 legacy）、`Asset.quick_hash`/`full_hash`（预留）；扫描服务。
- **输出**：`legacy_path_rule` 级使用证据（仅"可能用过"）；`asset_path_history`；content identity 优先匹配策略。
- **数据迁移**：新增 `asset_path_history`；full_hash 回填**按需**（遵循审计分级策略 size/quick_hash→full_hash，不对全部大视频无条件全量哈希）。
- **API**：legacy 证据导入任务；path history 查询。
- **UI**：使用中心展示"历史可能使用过"（与 confirmed 严格分层）。
- **测试**：移动到"已使用/"后 full_hash 命中→同一 Asset（更新位置+追加历史，不新建重复）；legacy 不计入正式次数；只读核对（导入流程不改源）。
- **真实数据验收**：在真实库验证"已使用靠移动、0 字节级重复"场景下身份稳定（不产生重复 Asset）。
- **风险**：full_hash 计算成本 → 分级 + 按需触发。
- **回退**：full_hash 未回填时退化为路径唯一约束（现状），legacy 仅标记不影响主流程。
- **GPU**：否。**NAS**：友好。

### PR-D 手工确认使用记录 + 使用中心 UI

- **目标**：让剪辑/运营确认/修改/驳回使用引用，并提供使用中心；接入剪辑工程文件解析。
- **输入**：PR-B 的 `final_video_usage`；现有审核体系（`ShotReviewState`/`ReviewEvent`/状态机/乐观锁）。
- **输出**：`usage_review` 并行审核域；使用中心（确认/驳回/改来源 Shot/改时间码/批量确认/查看证据）；工程文件（`.prproj`/`.fcpxml`/`.edl`/剪映）解析 → `confirmed_editor_project`。
- **数据迁移**：`usage_review` 状态行（复用 ShotReviewState 结构）+ `ReviewEvent` 增 `object_type='final_video_usage'`（或并行 `usage_review_event`）。
- **API**：`/usages/{id}/review/*`（镜像 `/shots/{id}/review/*`）；工程文件导入解析。
- **UI**：使用中心（待确认引用队列、证据展示、批量确认、使用次数/被哪些成片使用）。
- **测试**：确认→计入次数+投影重算；驳回→扣除重算；乐观锁 409；append-only 审计；工程文件解析正确性。
- **真实数据验收**：用真实工程文件建高置信引用；度量人工确认工作量（《评测计划》B3）。
- **风险**：多样工程文件格式 → 先支持主流（Premiere/剪映），其余人工。
- **回退**：无工程文件解析时全人工确认；解析失败标 degraded 不静默。
- **GPU**：否。**NAS**：友好。

### PR-E 使用感知检索与排序

- **目标**：在现有 Hybrid Search 上新增 usage 过滤与降权（不重写检索内核）。详见《使用感知检索》。
- **输入**：PR-B 的使用投影；现有 `search_service`/`scoring.py`（RRF + 多因子融合）。
- **输出**：usage 过滤（仅未使用/优先未使用/允许少量/排除高频/最近 N 天未使用）；usage 排序因子（未使用奖励、使用次数惩罚、近期重复惩罚、同源素材重复惩罚）；同一 Asset 数量限制；结果展示使用次数与引用成片。
- **数据迁移**：无（读 PR-B 投影）；可选把 `scoring.py` 硬编码权重重构为可配置 Settings。
- **API**：搜索请求增 usage 过滤/排序参数；结果增 usage 字段。
- **UI**：搜索工作台增 usage 过滤器与使用状态徽标（never_used/used_multiple/overused/...，7 态）。
- **测试**：仅 confirmed 影响降权；严格未使用硬过滤；嵌入降级时 usage 仍生效（正交）；同源去重；锁定镜头不被重排剔除；usage 因子可整体关闭退化为现状。
- **真实数据验收**：《评测计划》B2（同源重复率↓、未使用占比↑、不相关率↓），权重经真实素材调参。
- **风险**：降权压过强命中 → 软降权带上限，默认不绝对排除。
- **回退**：usage 因子开关置 0 即退化为现有 Hybrid Search。
- **GPU**：否。**NAS**：友好。

### PR-F 产品视觉识别实验 Provider

- **目标**：实验性引入视觉产品识别（Grounding DINO 开放词表检测 / OpenCLIP·SigLIP2 图文嵌入），产候选，强制人工确认。
- **输入**：PR-A1 产品层级 + PR-A2 参考图/混淆组；FFmpeg 派生关键帧（只读派生，写 `/app/data`）。
- **输出**：`ShotTag[type=product,source=ai]` / `AssetProduct` 候选（【AI 推断】，needs_human）；confusable（软/硬屏）只给候选不自动断言。
- **数据迁移**：无（写现有候选表）；视觉嵌入若入库作独立向量列（评审，可推迟到 PR-G）。
- **API**：视觉识别 Provider（遵循 `ProviderCapabilities` 降级）；批量识别任务。
- **UI**：产品识别审核队列（复用人工审核）。
- **测试**：候选写入与人工确认流；confusable 不自动生效；Provider 不可用回退名称/目录规则；只读派生核对。
- **真实数据验收**：《评测计划》B1（4 产品含软/硬屏检测召回/精度与人工确认率），先离线在真实关键帧验证。
- **风险**：CPU 上 Grounding DINO 慢（单图秒级）→ 仅离线批；许可证（OpenCLIP 须选商用 checkpoint）。
- **回退**：视觉不可用 → 现有规则/名称匹配候选 + 人工确认，检索不受影响。
- **GPU**：可选（CPU 离线批可行，GPU 加速）。**NAS**：离线批可行。

### PR-G 多路召回与 reranker

- **目标**：填补现有 `AIProvider.rerank_candidates` 空槽（BGE Reranker 对 Top-K 精排），可选接入视觉嵌入召回通道。
- **输入**：PR-E 的候选与融合；现有 Provider 抽象。
- **输出**：本地 Reranker Provider（Top-K 精排，K 受控）；可选视觉图文嵌入召回（OpenCLIP/SigLIP2 独立向量空间）。
- **数据迁移**：可选视觉向量列（独立空间，与 `embedding_status` 正交）；HNSW 参数评审。
- **API**：rerank 启用开关（capabilities 决定）；视觉召回通道开关。
- **UI**：无（排序质量提升，可在搜索结果解释中体现精排理由）。
- **测试**：reranker 缺失回退现有 final_score 排序（不伪造）；K 受控；精排与使用感知降权次序协同；嵌入正交降级。
- **真实数据验收**：《评测计划》B2（重排前后 Top-K 排序增益），先离线验证增益再决定上线。
- **风险**：CPU reranker 偏慢 → 仅 Top-K（如 50~100）；融合权重不冻结。
- **回退**：reranker/视觉嵌入不可用 → 现有多因子排序，检索不退化。
- **GPU**：可选。**NAS**：受控可行（K 受控的 CPU 精排）。

### PR-H 成片反向引用识别

- **目标**：实验性自动反查成片引用的源镜头（产 `suspected_*` 证据，人工确认后才计入）。
- **输入**：PR-B 的血缘模型、PR-D 的审核域；真实成片样本。
- **输出**：`suspected_visual_match`（关键帧 pHash / DINOv2）与 `suspected_audio_match`（Chromaprint）反查候选 → `final_video_usage(confirmed=false)` 进审核队列。
- **数据迁移**：无（写 PR-B 表）；可选反查指纹缓存。
- **API**：成片反查任务；候选进审核。
- **UI**：使用中心待确认引用（带证据与匹配分）。
- **测试**：suspected 绝不自动计入次数；反查候选必须人工确认；时间码误差度量；legacy 不被当确定引用。
- **真实数据验收**：《评测计划》B3（Precision/Recall/时间码误差/错误使用计数率=0）。**前置：公司提供真实成片（当前库疑似成片=0）。**
- **风险**：带货成片常换 BGM/配音 → 音频反查召回有限；视觉反查需控误报。
- **回退**：自动反查不可用 → 全人工/工程文件确认；suspected 缺失不影响 confirmed 链路。
- **GPU**：可选（pHash/Chromaprint 纯 CPU；DINOv2 CPU 可跑）。**NAS**：离线批可行（Chromaprint 须非 GPL 二进制）。

### PR-I 结构化分镜与全局匹配

- **目标**：把现有逐段候选升级为全脚本全局分配 + 同源去重 + 使用感知降权。详见《结构化分镜匹配》。
- **输入**：PR-E 的使用感知因子；现有 `ScriptSegment`/`ScriptShotCandidate`/`editlist.allocate`（已有贪心全局分配雏形）。
- **输出**：使用感知的全局分配（跨段同源预算、未使用优先、高频降权）；缺口/补拍区分"无此镜头"与"合规镜头已高频使用"。
- **数据迁移**：无（逻辑扩展）；可选 `usage_penalty` 落候选可解释字段。
- **API**：分镜匹配请求增使用策略；全局分配结果。
- **UI**：脚本匹配工作台展示全局分配与去重/降权理由、缺口与补拍建议。
- **测试**：不再"每段独立 top-1"；同一镜头不被塞进多段；锁定/选择保护；确定性（同输入同输出）；缺口不强塞。
- **真实数据验收**：《评测计划》B4（重复镜头率↓、未使用采用率↑、缺口识别正确率），真实脚本 + 缺口探针段。
- **风险**：全局优化复杂度 → 默认确定性贪心兜底，允许后续替换更强分配器。
- **回退**：全局分配器失败 → 回退现有 `editlist.allocate` 贪心。
- **GPU**：否。**NAS**：友好。

---

## 2. 评测对照（与《评测计划》一致）

| 评测集 | 主要验收的 PR |
|---|---|
| B1 产品识别 | PR-A1（目录核心）+ PR-A2（混淆组/参考图）、PR-F（视觉识别）、含 A–F 通用化子评测（冷启动/拒识/留出） |
| B2 素材搜索 | PR-E（使用感知检索）、PR-G（reranker/视觉召回） |
| B3 成片引用 | PR-B（血缘模型）、PR-D（人工/工程确认）、PR-H（自动反查） |
| B4 分镜匹配 | PR-I（全局分配）、PR-E（使用降权因子） |
| B0 一致性 | 贯穿所有人工标注 PR（先于定级） |

---

## 3. 硬约束重申（每个 PR 都遵守）

- 绝不生成式视频；"关键帧/缩略图/代理/可剪辑片段"= FFmpeg 从源派生。
- 源素材只读：绝不移动/改名/删除源文件；派生只写 `/app/data`；成片受控存储绝不写源目录。
- 数据库一律 Alembic 新迁移，不改历史迁移、不删库重建。
- 证据分层：自动结论标【事实/规则推断/AI 推断/人工确认】；UI 不伪造"已识别/已匹配/使用次数"。
- 仅 confirmed 计入正式 usage_count；suspected/legacy 只提示。
- 软/硬屏 confusable 默认不自动断言，低置信标"未知/待确认"。
- 权重/阈值不在规格冻结，落地 PR 经真实素材基准调参。
- 每个能力可降级/回退，不破坏已稳定的 PR-01..PR-06。
- 真实素材 + 真实 Provider 验收，CI 合成数据不作达标依据。

---

## 4. 不做（本路线图边界）

- 本阶段不执行任何 PR、不写迁移、不改代码、不接模型、不下权重。
- 不承诺仅凭最终 MP4 全自动精确反查原片（PR-H 是带证据+人工的尽力而为）。
- 不把所有需求塞进一个巨型 PR（强制小步可验收）。
