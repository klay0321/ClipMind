# 现状差距分析（CURRENT_SYSTEM_GAP_ANALYSIS）

> 阶段：Phase 0 Discovery。本文件盘点 **ClipMind 现有实现** 对照新需求（跨境电商产品带货素材的产品身份、使用血缘、使用感知检索、结构化分镜全局分配）的差距。
> 业务事实来源：`ECOMMERCE_MEDIA_ASSET_REQUIREMENTS.md`（§0–§7）；
> 产品身份与使用血缘规格：`PRODUCT_IDENTITY_AND_USAGE_LINEAGE_SPEC.md`（§1–§7）。
> 术语、对象模型、状态机、证据等级与上述两份**完全一致**。
>
> **本阶段只写规格，不创建任何 Alembic 迁移、不改模型、不改搜索排序、不接新模型、不下载模型权重。**
> 字段/表名为设计草案，落地 PR 再评审。
>
> 标注约定（继承上游规格）：
> - **[复用]** 现有模型/服务可直接承载，**不重写**；
> - **[扩展]** 现有上加列/加关系/加配置项；
> - **[新增]** 本批新建表/服务/模块。
> - 证据分层标签：`事实 / 规则推断 / AI 推断 / 人工确认`（UI 不伪造"已识别/已匹配/使用次数"）。

---

## 0. 总结论（先读这一段）

**核心结论：ClipMind 的"理解—审核—检索—匹配—导出"主干已稳定且成熟，本批新需求是在其上"加血缘层 + 加产品身份层级 + 加使用感知排序 + 加全局分配"，绝不推翻已稳定功能。**

差距高度集中在**三个新增环节**，其余几乎全是**复用/扩展**：

1. **使用血缘层（最大缺口，新增）**：缺 `Final Video` / `Final Video Usage` 两表、6 级证据等级、8 级使用状态、使用次数投影、成片反查能力、使用引用审核工作流。引用链 `Final Video →(Final Video Usage)→ Shot → Asset → Product` 在代码中**完全不存在**。
2. **产品身份层级（中等缺口，扩展为主）**：现有 `Product` 是扁平表，缺 `Product Family` / `Product Variant` 分组与 confusable group（软/硬屏混淆组）治理。
3. **使用感知与全局分配（中等缺口，扩展为主）**：Hybrid Search 与脚本逐段匹配已成熟，但缺 usage_count/last_used_at **降权通道**、同源去重、未使用奖励、全脚本全局分配。

下表与后续逐项展开覆盖任务要求的全部维度：**Product 当前模型 / Asset·Shot / AIAnalysis / HumanReview / Search / Script Match / Project / Export / NAS scan / fingerprint / pgvector / 现有 E5 Provider / MiMo Provider**。

| 维度 | 已具备（不重写） | 主要缺口 | 落地动作类型 |
|---|---|---|---|
| Product 模型 | Product/ProductAlias/ProductImage/AssetProduct 多对多 | Family/Variant 层级、confusable group、family 级别名 | [扩展] 为主 + 少量 [新增] |
| Asset | 只读索引、quick/full_hash 预留、ffprobe、primary_product_id | path 历史、usage rollup、稳定 content identity 回填 | [扩展] + [新增]投影 |
| Shot | generation/时间码/派生文件、ready 才可见 | usage 统计列（confirmed/suspected/legacy/last_used_at） | [扩展] 投影表 |
| AIAnalysis | Run/ShotAnalysis/CallLog、fingerprint 缓存、成本台账 | 无血缘缺口（仅被血缘"读"，不改造） | [复用]（基本不动） |
| HumanReview | ShotReviewState+ReviewEvent+状态机+乐观锁 | 使用引用审核（usage review）域 | [复用]架构 + [新增]并行域 |
| Search | Hybrid 召回+RRF+规则解释+稳定排序 | usage_score 通道、同源去重、未使用奖励、可配权重 | [扩展] 新增因子（不改 RRF base） |
| Script Match | 拆段/逐段候选/选择锁定/全局去重分配 | 全局使用感知分配、跨段同源去重、成片反查 | [扩展] allocate 参数 + [新增]反查 |
| Project | active/archived、Favorite、Export 关联 | final_video.project_id 归属 | [复用] + 关联字段 |
| Export | 来源快照不可变、多格式、ZIP | 导出→使用事件回填（clipmap_export 证据来源） | [复用]快照 + [扩展]回填 |
| NAS scan | ScanRun 事实源、advisory lock、缺失检测 | content identity 优先匹配、path 历史 | [复用] + [扩展]扫描策略 |
| fingerprint | quick_hash 头尾、compute_fingerprint 规范化 | full_hash 字节级补齐（按需，非本阶段） | [复用] + [扩展] |
| pgvector | 迁移建表/HNSW/双层正交状态 | 无缺口（嵌入缺失仍可词法召回） | [复用]（不动） |
| E5 Provider | 抽象/工厂/版本控制/L2 归一/E5 前缀 | 无缺口 | [复用]（不动） |
| MiMo Provider | 抽象协议+占位/降级，查询解析已接 | 视觉产品识别实现（留后续 PR） | [复用]抽象 + 后续实现 |

---

## 1. 逐维度差距详表

### 1.1 Product 当前模型（产品身份）

**已具备 [复用]（不重写）**
- `Product`（brand/name/model/sku/`normalized_name`/selling_points JSONB/status）、`ProductAlias`（`normalized_alias` 候选匹配）、`ProductImage`（受控相对路径 `products/{id}/images/`）。
- `AssetProduct` 多对多（`source` ai/human、`confidence`、`match_type`、`match_score`、`active`、`confirmed_by`/`confirmed_at`、`extra` JSONB）——素材↔产品关联与来源标注已充分验证。
- 出处：`packages/shared/clipmind_shared/models/product.py`。

**缺口 → 落地动作**
- **产品族/变体层级缺失**：现有 `Product` 为扁平表，无 family/variant 分组。
  - [新增] `product_family` 表（family_name + `normalized_name` + status + family 级别名/混淆组语义），对照规格 §1.1 倾向方案 A。
  - [扩展] `Product.family_id` 外键；变体名沿用 `Product.model`（如 `软屏`/`硬屏`），每个变体 = 一行 `Product`。
- **混淆组（Confusable Group）缺失**：无"软/硬屏同族易混"治理（规格 §1.2）。
  - [新增] confusable group 标记（family 内分组）；视觉识别对组内变体**默认不自动判定**，强制人工确认；检索/分镜提供"按族过滤 / 按变体过滤"两档。
- **family 级别名缺失**：现有别名挂在 `Product` 行，family 级别名需 `product_family` 也支持别名（[扩展]）。

**不应重写**
- `Product`/`ProductAlias`/`ProductImage`/`AssetProduct` 的多对多与来源标注（PR-03B 标准库）。`normalized_name` 标准化匹配可**复用**到 family/variant 命名规范化（统一大小写/空格/标点）。

**证据分层**：目录名命中 = `规则推断`（仅候选 needs_human=true）；视觉识别 = `AI 推断`（confusable 必人工确认）；运营确认 = `人工确认`（生效）。**绝不只凭目录名最终确认产品身份**（规格 §1.4）。

---

### 1.2 Asset / Shot（源素材与镜头）

**已具备 [复用]（不重写）**
- `Asset`：只读索引；`relative_path`/`normalized_relative_path` + `(source_directory_id, normalized_relative_path)` 唯一约束；`quick_hash`（头尾+大小）/`full_hash`（**预留列**）；ffprobe 字段；`primary_product_id`；`poster_path`；`last_seen_scan_id` 缺失检测；状态机 discovered/indexed/error/source_missing。出处：`models/asset.py`。
- `Shot`：`asset_id`/`generation`/`sequence_no`/时间码约束（start≥0、end>start）；派生文件相对路径（keyframe/thumbnail/proxy/`keyframe_paths` JSONB）；状态 pending/processing/ready/failed，**仅 ready 对外可见**；代次原子替换。出处：`models/shot.py`。

**缺口 → 落地动作**
- **使用统计缺失**：`Shot` 无使用维度。
  - [扩展 / 倾向投影表] 派生只读统计 `confirmed_usage_count`、`suspected_usage_count`、`legacy_used_flag`、`last_used_at`、`distinct_final_video_count`。
  - 选择**投影表/物化**（如 `shot_usage_stat`）而非直接写 `Shot`，与现有 `ShotTag`/`ShotSearchDocument` 投影模式一致，便于"删除/驳回引用后重算"（规格 §2.3）。
- **Asset 汇总缺失**：`Asset` 无 `usage_rollup`（由其全部 Shot 汇总，物化或视图）；Asset"被用过" = 任一 Shot 被用，次数按去重成片数（规则见规格 §4）。
- **稳定身份与 path 历史缺失**：应对"已使用靠移动而非复制"（审计：0 字节级重复）。
  - [新增] `asset_path_history`（记录每次扫描观察到的路径与时间）；
  - 身份策略：入库/重扫描先按 content identity（`full_hash`→命中视为同一 Asset，仅更新当前路径并追加历史），再回退 `(source_directory_id, normalized_relative_path)`（规格 §6）。
  - **本阶段不启用 full_hash 回填、不新增 path history 表、不写迁移**——仅冻结策略。

**不应重写**
- `Asset`（PR-01 稳定）的指纹/ffprobe/缺失检测、`Shot`（PR-02 稳定）的派生路径相对化与代次原子替换皆为来之不易的稳定设计。usage 字段以**投影/冗余缓存**形式追加，不改 Shot 主结构。

---

### 1.3 AIAnalysis（AI 镜头分析）

**已具备 [复用]（不重写）**
- `AIAnalysisRun`（素材级运行 status/progress/analyzed_shots/skipped_cached/degraded）、`AIShotAnalysis`（`parsed_result` JSONB / `input_fingerprint` / confidence / status / projection_status）、`AICallLog`（脱敏成本台账 tokens/cost/duration/error_code，**无密钥**）。出处：`models/ai_analysis.py`。
- `compute_fingerprint()` 缓存去重（SHA256 规范化 JSON：provider/model/prompt_version/schema_version/params/frame_hashes），版本切换强制重算。出处：`ai/fingerprint.py`。

**缺口 → 落地动作**
- **本维度对新需求基本无结构缺口**：血缘层只**读取** AI 分析结果，不改造 `AIShotAnalysis`。
- 仅一处可选 [扩展]：若需在分析层显式标注证据级别，可在投影/标签侧体现 `事实 / 规则推断 / AI 推断 / 人工确认`，**不在 AI 表内冻结使用语义**。

**不应重写**
- 成本台账与 `input_fingerprint` 缓存去重已稳定，修改需考虑已有数据迁移。**`compute_fingerprint()` 框架可复用到成片反查**（避免重复成片识别），无需改动现有指纹设计。

---

### 1.4 HumanReview（人工审核）

**已具备 [复用]（不重写）**
- `ShotReviewState`（per `(shot_id, shot_generation)`、`lock_version` 乐观锁、`stale_*` 失效标记、`confirmed_result` JSONB、`confirmed_product_id`）、`ReviewEvent`（append-only 审计 action/before_data/after_data/comment）。出处：`models/review.py`。
- `ReviewStatus`（unreviewed/pending_review/confirmed/modified/rejected/unable）、`ReviewAction`（confirm/modify/reject/unable/reopen）+ 显式状态机（`review/state_machine.py`，`InvalidReviewTransition`/`can_transition`）。
- `effective_result()`（人工优先合并 + stale 判定）、`projected_tags()`（confirmed_result→标签投影）、`apply_review()`（事务化：乐观锁冲突检测 + 状态更新 + 标签投影刷新 + 审计事件 + 409/422 异常映射，AI 结果不被覆盖）。

**缺口 → 落地动作（80%+ 可复用架构）**
- **使用引用审核域缺失**：无对 `final_video_usage` 的人工复核/修改/驳回工作流。
  - [新增（并行域，不改造 Shot 审核）] `usage_review` 状态：`(usage_id, generation)` ↔ `(shot_id, generation)` 同构；`lock_version`/`stale_*`/`confirmed_result` 复用。
  - [扩展] `ReviewEvent` 增加 `object_type='final_video_usage'` 支持使用审核审计（保持 append-only），或新增并行 `usage_review_event`（规格 §5）。
  - [扩展] 审核动作：确认（suspected→confirmed，计入正式次数触发重算）/ 驳回（扣除重算）/ 修改来源 Shot / 修改时间码 / 批量确认 / 查看证据。
  - [扩展] `apply_review()` 可**泛型化** `apply_domain_review(db, domain_object, payload)`：参数化 object_type / state_row_type / event_type，减少重复。
  - [扩展] `/usages/{usage_id}/review/*` 端点镜像 `/shots/{shot_id}/review/*`。

**不应重写**
- `ShotReviewState` 核心结构、`ReviewEvent` append-only、`state_machine` 显式转换、乐观锁 UPDATE 语义、`effective_result()` 状态优先级（被搜索/推荐/脚本匹配多处依赖）、`projected_tags()` 标准化。使用域**并行设计**，不反向改造 Shot 表。

---

### 1.5 Search（语义/混合检索）

**已具备 [复用]（不重写）**
- Hybrid 召回 + RRF 融合：lexical/pg_trgm、tag（scene/action/shot_type/marketing）、product（SKU>model>name>alias>brand 六档）、semantic（pgvector HNSW cosine）；候选池有界；mode-aware（HYBRID/SEMANTIC/LEXICAL/STRUCTURED）；truncation 标志。出处：`apps/api/app/services/search_service.py`。
- `_apply_filters()` 库级硬过滤（review status、stale、时长、画幅比、负向词 ILIKE 转义、风险包含/排除、显式产品 ID，均绑定参数防注入）；`_resolve_products()`/`_channel_product()` 六档产品打分 + confirmed 关联 bonus。
- `scoring.py`：RRF（K=60）+ 通道内信号均值（SIGNAL_WEIGHT=0.5/RRF_WEIGHT=0.5）；通道权重 product=1.1/semantic=1.0/lexical=0.85/tag=0.8；`final_score = base + exact_product_bonus + review_bonus + quality_weight − risk_penalty`，clip[0,1]，稳定全序排序。
- `explain.py` 规则派生 `matched_reasons`/`unmatched_requirements`/`risk_warnings`（全部源自 `MatchFacts` 真实 DB 事实，无 LLM 生成、无幻觉）。
- `run_description_match()`（复用 Hybrid，软→硬过滤开关、min_score、推荐级别）；索引状态聚合与重建入队（`search_index_service.py`）；搜索建议。

**缺口 → 落地动作（新增因子，不改 RRF base）**
- **使用感知排序缺失**：无 usage_count/last_used_at 降权，无 used_multiple/overused 评分因子。
  - [扩展] `Candidate`（`scoring.py`）增加 `usage_count`/`last_used_at`/`asset_usage_tier`；`score_candidates()` 增加 `usage_score`，与其他通道同 [0,1] 归一。
  - [扩展] `_joined()` enrich pass 纳入 `Shot/Asset` 使用统计（JOIN 投影表），同绑定参数安全。
- **未使用奖励缺失**：无 unused/rarely_used 提权以浮起沉底素材（《业务需求》痛点第 8 条）。
- **同源去重缺失**：无对"与已选 Shot 同 Asset 候选"的降权（属脚本匹配协同，见 §1.6）。
- **权重不可配缺失**：CHANNEL_WEIGHTS 与 bonus/penalty 常量硬编码。
  - [扩展] 重构为 Settings 注入；增加可选 `usage` 通道权重与开关（`include_overused`/`exclude_rarely_used`/`min_usage_count`/`usage_sort_order`）。
  - **权重不在本规格冻结**：仅列可配置因子（usage 降权系数、未使用奖励、同源去重 penalty、近期重复阈值）与默认倾向（未使用优先、高频降权），具体值落地 PR 评审与评测调参。

**不应重写**
- `_channel_*` 召回机制、RRF + signal_avg 融合公式、`explain.py` 事实溯源、Embedding/pgvector HNSW、document/embedding **双层正交状态**、稳定排序与分页 tie-breaker。usage-aware 是**融合后新评分因子**，作用于候选池而非向量距离本身。新增 `usage-confirmation` 必须源自真实 DB 列/事件，**绝不 LLM 幻觉**。

---

### 1.6 Script Match（结构化分镜匹配）

**已具备 [复用]（不重写）**
- `ScriptProject`/`ScriptSegment`/`ScriptShotCandidate`（产品硬约束 `product_id`、`structured_requirements` JSONB、目标时长、`selected_shot_id`/`locked_shot_id`、`lock_version`、`match_status` pending/matched/gap/degraded、reshoot 建议；候选评分因子 final/semantic/lexical/tag/product/quality/review_bonus/risk_penalty + matched_reasons/unmatched_requirements/risk_warnings）。出处：`models/script.py`。
- `match_segment`/`match_script`（复用 `run_description_match`、代次原子替换、幂等 `match_token`、skip_locked、部分失败处理）；`build_match_request`（从 structured_requirements 显式装配，**绝不依赖脆弱文本解析**，`suppress_parsed_duration` 抑制时长硬过滤）；`select_shot`/`lock_shot`/`unlock_segment`（乐观锁 + 条件 UPDATE 消 TOCTOU）；`build_segment_views`（批量装配防 N+1）。
- 剪辑清单纯逻辑 `allocate`/`build_edit_list`（确定性全局分配：Pass1 锁定>选择，Pass2 按综合分去重 + 相邻差异避免 + `max_reuse` 复用上限，标注重复/gap/风险）。出处：`script/editlist.py`。

**缺口 → 落地动作**
- **使用感知降权缺失**：`allocate()` 仅 `max_reuse` 去重，无 usage_count/last_used_at 降权。
  - [扩展] `allocate()` 传入 `shot_usage_count` 字典：Pass2 先按未使用优先排序，再按 `综合分 − usage_count*系数` 排序，相邻去重逻辑保持（系数可配，不冻结）。
- **跨段全局分配 / 同源去重缺失**：当前逐段独立候选池，无跨段约束。
  - [扩展] `run_description_match` 返回候选后，按前段 `locked_shot_id`/`selected_shot_id` 上下文做"per-segment 同源去重 penalty"（如同 Asset 已选则降权），避免同一镜头塞进多段（《业务需求》痛点第 9 条）。
- **成片反查缺失**：无源镜头→引用成片能力（引用链完全缺失）。
  - [新增] 反查复用 `DescriptionMatchRequest` 模式：虚拟 SegmentView 从源镜头特征 → `build_match_request` → 搜索同族可用镜头。
- **CSV 导出无使用信息**：导出无 use_count/last_used_at/usage_state 列（见 §1.8 Export）。

**不应重写**
- `allocate()` Pass1/Pass2 结构（已验证正确，改动需全量回归）、`match_segment` 代次原子替换 + 幂等 token（依赖 DB 唯一约束）、`DescriptionMatchRequest` 显式结构化软信号（脚本匹配设计红线）、`suppress_parsed_duration`、viewbuild 行转换（API/export-worker 共享）。使用感知是**新评分因子**，不替换分配基线。

---

### 1.7 Project（业务项目）

**已具备 [复用]（不重写）**
- `Project`（PR-06A，active/archived）、`Favorite`（多态收藏）、`Export`/`ScriptExport`/`BundleExport`（多格式 csv/xlsx/json/markdown/printable + ZIP）。

**缺口 → 落地动作**
- [扩展] `final_video.project_id` FK（SET NULL）将成片归属到现有业务项目，与 `Project` 一致（规格 §2.2）。
- 使用统计可按 project 聚合（主管视角：复用率/未使用占比，对应《业务需求》§2 目标用户中的主管关注点），属投影/查询层，无需改 `Project` 结构。

**不应重写**
- `Project`/`Favorite`/`Export` 关联（PR-06）稳定。新增血缘对象通过 FK 关联，不改造 Project。

---

### 1.8 Export（片段导出）

**已具备 [复用]（不重写）**
- `Export` 来源**不可变快照**（`source_asset_id`/`source_shot_id`/`source_generation`/`source_sequence_no`/`source_start_time`/`source_end_time`/`source_filename`/`source_relative_path`）+ DB 关联（asset_id/shot_id **SET NULL**，资产删后仍可追溯）。出处：`models/export.py`。
- 多格式导出 + ZIP 束（PR-06）。

**缺口 → 落地动作**
- **导出→使用事件回填缺失**：ClipMind 自身导出的剪辑清单回填是 `confirmed_clipmap_export` 证据来源，但当前导出不产生使用事件。
  - [扩展] 导出后可生成/回填 `final_video_usage`（evidence_level=`confirmed_clipmap_export`，计入正式次数），触发 Shot/Asset usage 投影重算。
  - [扩展（可选）] `Export` 增 `final_video_id` FK + `used_at` + `usage_status`，标记本导出是否被某成片使用。
- **CSV 导出无使用列**：[扩展] 导出行增加 use_count/last_used_at/usage_state（派生展示，标注证据分层）。

**不应重写**
- `Export` 源快照机制（`source_*` 不可变字段）已支撑多场景追溯。**血缘 Final Video 可直接复用此快照模式**（记录 first_used_shot_id/导出时刻），建立不可逆使用溯源，而非仅存当前 FK 引用。

---

### 1.9 NAS scan（只读扫描）

**已具备 [复用]（不重写）**
- `ScanRun`（DB 单一事实源、status queued→running→completed/failed、并发防重部分唯一索引 `uq_active_scan_run`、discovered/new/modified/missing/errored 计数）；`SourceDirectory`（容器挂载路径、include/exclude JSONB、scan_status）。出处：`models/scan_run.py`/`source_directory.py`。
- `scan_dispatch.request_scan()` 事务创建 + 入队 + 幂等防重；`scan_source_directory()` Celery 任务（会话级 advisory lock、分层变化检测 needs_probe、缺失检测 last_seen_scan_id、`rescan_asset()` 单素材重扫）。

**缺口 → 落地动作**
- **稳定身份匹配缺失**：现有扫描按 `(source_directory_id, normalized_relative_path)` 识别，文件移动到"已使用/"后路径变化会被当作"缺失 + 新增"，丢失既有镜头/标签/使用记录。
  - [扩展] 扫描策略：先按 content identity（full_hash 命中→同一 Asset，更新位置 + 追加 path history），再回退路径唯一约束（规格 §6）。
  - [扩展] "已使用"目录/后缀命中 → 写 `legacy_path_rule` 级证据（"可能用过"，不改正式次数）。
- **本阶段不实现**：不启用 full_hash 回填、不新增 path history 表、不写迁移、不改扫描代码——仅冻结策略。

**不应重写**
- `ScanRun` advisory lock + 部分唯一索引双层并发防护、`FFprobe` 安全模式与错误分类（无 shell=True、`--` 注入防护、旋转校正、`ProbeError` 分类）已实战验证。`ScanRun + advisory lock` 模式**可复用**到 `final_video_usage` 写入并发控制。

---

### 1.10 fingerprint（指纹）

**已具备 [复用]（不重写）**
- `Asset.quick_hash`（头尾 + 大小快速指纹，已用于变化检测）；`Asset.full_hash`（**预留列**，字节级未启用）。
- `compute_fingerprint()`（规范化 JSON SHA256，AI 分析缓存去重）；`hash_file()` 帧内容 hash。出处：`ai/fingerprint.py`。

**缺口 → 落地动作**
- **full_hash 字节级补齐（按需）**：稳定 content identity 需要 full_hash，但成本高。
  - [扩展] 遵循审计脚本**分级策略**（先 size/quick_hash 候选，再 full_hash），避免对全部大视频无条件全量哈希；何时计算（入库/按需）落地 PR 决定。
- **suspected_visual_match / suspected_audio_match 指纹缺失**：成片反查的 pHash/帧匹配、Chromaprint 音频指纹属后续 PR（仅产生 suspected 证据，不计入正式次数）。

**不应重写**
- `compute_fingerprint()` 规范化与版本语义、`quick_hash` 头尾实现。**成片反查复用 fingerprint 框架避免重复识别**。

---

### 1.11 pgvector（向量索引）

**已具备 [复用]（不重写）**
- 迁移 `0007_semantic_search`（vector/pg_trgm 扩展幂等、`ShotSearchDocument` 表、词法 GIN + 向量 HNSW 索引）；`ShotSearchDocument`（384 维、`document_status` 与 `embedding_status` **双层正交**、嵌入身份版本控制、`is_searchable` 去规范化）。出处：`models/search.py`、`apps/api/migrations/versions/0007_semantic_search.py`。
- 幂等索引（document_hash + 嵌入身份 + template_version + status + 非空向量全匹配才跳过重嵌）；sweeper 检测 stale；**降级嵌入仍 is_searchable=true**（向量缺失绝不导致无法搜索）。

**缺口 → 落地动作**
- **本维度对新需求无结构缺口**：usage_count/last_used_at 是 Asset/Shot 元数据，**不**进 `ShotSearchDocument` 索引状态（保持双层正交契约纯净）；使用感知作用于融合后候选池，与向量距离正交。
- 仅 [扩展（可选）] 审核确认/修改使用后，可入队重建影响展示字段（usage_status/usage_count）的搜索文档，复用现有重建队列。

**不应重写**
- HNSW 参数与 E5 前缀规范（基于向量检索文献配置）、双层正交状态设计（PR-04 核心契约）。**绝不混用不同维度/模型向量**（embedding_version 切换强制重嵌）。

---

### 1.12 现有 E5 Provider（本地嵌入）

**已具备 [复用]（不重写）**
- `EmbeddingProvider` 协议（identity/capabilities/health/embed_query/embed_documents）；工厂支持 fake/openai/openai_compatible/http 别名；E5 前缀（query:/passage:）、L2 归一化、维度校验；版本合成（`provider:model@revision:d384:normalization:prefix`）；异常分类；`NotConfiguredEmbeddingProvider` 占位（**绝不伪造向量**）。本地 sentence-transformers embedder 微服务（FastAPI、revision-pinned multilingual-e5-small、HNSW queryable）。出处：`ai/embedding.py`、`ai/embedding_factory.py`、`services/embedder/`。

**缺口 → 落地动作**
- **本维度对新需求无缺口**。使用感知排序作用于候选池后处理，与嵌入提供方正交，无需改动 E5 Provider。
- **本阶段不接新模型、不下载模型权重**。

**不应重写**
- Embedding Provider 抽象与工厂、版本控制（`make_embedding_version()` 模式可复用到未来视觉/产品识别向量，但非本阶段）。

---

### 1.13 MiMo Provider（外部 AI）

**已具备 [复用]（不重写）**
- AI Provider Protocol（health_check/analyze_frames/analyze_video_clip/parse_search_query/parse_script/generate_embedding/rerank_candidates）+ `ProviderCapabilities` 能力探测 + `NotConfiguredProvider` 占位（health ok=false）。出处：`ai/provider.py`。
- 查询解析已接 MiMo：`MiMoQueryParser`（OpenAI-compatible，失败内部降级 rulebased，`ParserStatus.DEGRADED` 可见）；工厂 fake/rulebased/mimo/auto。出处：`apps/api/app/services/search_providers.py`。
- MiMo 端点能力（参考记忆）：`mimo-v2.5-pro` 纯文本、视觉用 `mimo-v2.5`、鉴权 api-key 头、无 embeddings。

**缺口 → 落地动作**
- **视觉产品识别实现缺失**：MiMo 视觉识别（family/variant 判定）为后续 PR；confusable 组（软/硬屏）**默认不自动判定，强制人工确认**（规格 §1.2/§1.4）。
- **本阶段不接新模型**：仅冻结"AI 推断需人工确认、低置信标未知/待确认"的证据分层约束。

**不应重写**
- AI Provider 抽象协议与占位（PR-01 边界清晰，不逆向改为混合实现）。`health_check()` + capabilities_snapshot 优雅降级框架可复用到成片反查/视觉识别 Provider。

---

## 2. 新增对象清单（汇总，与规格一致）

> 全部为**草案**，与 《业务需求》/《身份血缘》 复用映射表一致。本阶段**不创建迁移**。

| 对象 | 状态 | 承载/复用要点 |
|---|---|---|
| `product_family` | [新增] | family_name + normalized_name + status + family 别名/混淆组；`Product.family_id` 外键 |
| confusable group | [新增概念] | family 内易混变体分组（软/硬屏），强制人工确认 |
| `final_video` | [新增] | 成片索引（source_type uploaded_mp4/editor_project/external_link/manual、project_id SET NULL、storage_path 受控、status imported/linked/archived） |
| `final_video_usage` | [新增] | 成片↔镜头引用（shot_id/asset_id SET NULL、evidence_level、时间码、confirmed、evidence JSONB），核心使用记录 |
| `shot_usage_stat` | [新增投影] | Shot 使用统计（confirmed/suspected_usage_count、legacy_used_flag、last_used_at、distinct_final_video_count） |
| Asset `usage_rollup` | [扩展/视图] | 由 Shot 汇总，物化或视图 |
| `asset_path_history` | [新增] | 应对"移动到已使用"的路径历史（content identity 优先匹配） |
| `usage_review`（域） | [新增并行] | 复用 ShotReviewState 架构到使用引用审核（不改造 Shot 审核） |
| EvidenceLevel / UsageStatus 枚举 | [新增] | 6 级证据 + 8 级使用状态（见下） |

**6 级使用证据等级**（强→弱，仅 confirmed_* 计入正式次数）：
`confirmed_editor_project` / `confirmed_manual` / `confirmed_clipmap_export`（计入）；`suspected_visual_match` / `suspected_audio_match`（待确认，不计入）；`legacy_path_rule`（"可能用过"，不计入）。

**使用频次状态（7 态，canonical）**（由 usage_count + last_used_at 派生，阈值可配、可按 Category 差异化）：
`never_used` / `legacy_used_unknown` / `used_once` / `used_multiple` / `recently_used` / `overused` / `usage_unknown`；
**正交确认轴**：`usage_pending_review` / `usage_confirmed`（见《业务需求》§5、《身份血缘》§4）。

---

## 3. 复用 vs 新增 一句话映射（对照 《业务需求》/《身份血缘》）

| 现有 X（复用/扩展） | → | 新需求 Y |
|---|---|---|
| `AssetProduct` 多对多 + source/confidence/active | → | `final_video_usage` 多源证据（evidence_level + confirmed） |
| `Export` 源不可变快照 | → | `final_video` 使用溯源快照（first_used_shot_id 等） |
| `ShotReviewState` + 状态机 + 乐观锁 | → | `usage_review` 并行域（泛型化 apply_domain_review） |
| `ReviewEvent` append-only | → | object_type='final_video_usage' 使用审核审计 |
| `Tag`/`ShotTag` source+active 分离 | → | 使用证据标注（active 仅有效证据计入统计） |
| `ScriptSegment` current_generation + locked_shot_id 原子代次 | → | `final_video` 多版本管理（旧版锁定不自动替换） |
| `compute_fingerprint()` 缓存去重 | → | 成片反查去重（避免重复识别） |
| `ScanRun` advisory lock + 部分唯一索引 | → | `final_video_usage` 写入并发控制 |
| Search `Candidate` + score_candidates | → | usage_score 新通道（不改 RRF base） |
| `allocate()` 全局分配 | → | 传入 shot_usage_count，未使用优先 + 高频降权 |
| `Product.normalized_name` 标准化 | → | `product_family`/`variant` 命名规范化 |
| `ShotSearchDocument` 双层正交状态 | → | Asset 使用状态正交（频次维度 vs 确认维度） |

---

## 4. 本阶段边界与硬约束重申

- **只写规格**：不创建 Alembic 迁移、不改模型、不改搜索排序、不接新模型、不下载模型权重。
- **不推翻已稳定功能**：上表所列"不应重写"项均为来之不易的稳定设计（PR-01..PR-06）；新需求一律**扩展/新增/投影**，不反向改造主结构。
- **绝不生成视频**：所有"关键帧/缩略图/代理/可剪辑片段"= FFmpeg 从源派生。
- **源素材只读**：绝不移动/改名/删除源文件；`final_video.storage_path` 受控、绝不写源目录。
- **证据分层**：自动结论标注 `事实 / 规则推断 / AI 推断 / 人工确认`；UI 不伪造"已识别/已匹配/使用次数"。
- **不自动计入疑似**：suspected/legacy 只提示，仅 confirmed 计入 `usage_count`。
- **不对软/硬屏自动断言**：低置信标"未知/待确认"。
- **权重不冻结**：本文件只列可配置因子（usage 降权系数、未使用奖励、同源去重 penalty、近期重复阈值、变体区分阈值、通道权重）与默认倾向（未使用优先、高频降权、confusable 必人工），具体值落地 PR 评审 + 评测调参。
- **嵌入缺失仍可搜**：pgvector 不可用回退词法/标签召回（`is_searchable` 不因 embedding 失效）。

---

## 5. 落地先后顺序（规格→实现，仅建议，非本阶段执行）

1. **Phase 0（本批文档）**：冻结产品身份层级、6 级证据 + 8 级使用状态、引用链、API 契约、使用感知/全局分配可配置因子。
2. **Phase 1（数据层 PR）**：新增 `product_family` / `final_video` / `final_video_usage` / `shot_usage_stat` / `asset_path_history`；Asset/Shot usage 投影；backfill 初值（legacy 证据导入只标"可能用过"）。
3. **Phase 2（检索扩展 PR）**：`search_service` 增 usage_score 通道、未使用奖励、同源去重；scoring 增 usage_weight；配置化权重。
4. **Phase 3（脚本/导出扩展 PR）**：`allocate()` 使用感知全局分配 + 跨段同源去重；导出回填 `confirmed_clipmap_export`；成片反查（带证据 + 人工确认的尽力而为）。
5. **后续 PR**：MiMo 视觉产品识别（confusable 强制人工）；suspected_visual/audio 反查指纹（pHash/Chromaprint）。

> 强调：以上顺序为路线建议，本阶段**不执行任何代码/迁移**。
