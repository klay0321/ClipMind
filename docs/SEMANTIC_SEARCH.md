# SEMANTIC_SEARCH.md — PR-04 语义检索（自然语言搜索与画面描述匹配）

本文件描述 PR-04 的设计与落地。**最高事实来源仍是 `docs/PRODUCT_REQUIREMENTS.md`**；早期
`docs/PR_ROADMAP.md`/`docs/ARCHITECTURE.md` 对 PR-04 的描述（`Shot.embedding` 列、`0004_pgvector`、
`POST /api/search`）写于 PR-03A/03B 重构之前，已过时，以本文与 `docs/PROJECT_COMPLETION_PLAN.md` 为准。

PR-04 分阶段交付：**Gate A（本阶段，已实现）= 检索文档与嵌入基础**；Gate B = Query Parser +
Hybrid Search API + 画面描述匹配 API；Gate C = UI 参考图 04 + 真实 E2E + 性能验收。

---

## 0. 关键决策（已确认，不再选型）

- **Embedding 架构**：`EmbeddingProvider` 抽象 + 独立 `embedder` 微服务（本地 sentence-transformers，
  OpenAI 兼容 `/embeddings`）；CI/测试用确定性 `FakeEmbeddingProvider`。MiMo **无 embedding 能力**
  （`supports_embeddings=false`，探测 404），故走独立 Embedding 通道，不复用视觉 provider。
- **模型与维度**：`intfloat/multilingual-e5-small`，**384 维**；迁移期向量列固定 `vector(384)`；
  换模型/维度/版本必须**全量重嵌**（嵌入身份参与幂等判定，绝不混用不同模型的向量）。
- **检索文档**：新表 `shot_search_document`（每 `(shot_id, shot_generation)` 一条）。
- **文档/嵌入状态正交**：`document_status`（pending/indexed/excluded）与 `embedding_status`
  （pending/embedding/completed/degraded/failed）分两列承载。
- **降级真实可见且仍可检索**：Embedding 未配置/不可用/revision 未固定时，文档仍
  `document_status=indexed`、`is_searchable=true`，**继续参与词法/pg_trgm/标签/产品/结构化召回**，
  仅 `embedding_status=degraded`、不进向量召回。绝不因 Embedding 缺失让镜头完全无法被搜索，也绝不伪造向量。
- **revision 默认即固定 + fail-closed**：默认 `EMBEDDING_MODEL_REVISION=614241f622f53c4eeff9890bdc4f31cfecc418b3`
  （e5-small 公开 commit，非敏感；单一事实来源 `clipmind_shared.constants.DEFAULT_EMBEDDING_MODEL_REVISION`，
  API/worker/embedder 三处一致，由 `test_revision_consistency` 强制）。可经 env 覆盖；若设为空/main/latest/head
  且 `EMBEDDING_REQUIRE_PINNED_REVISION=true`（默认）→ Provider `health.ok=false`、嵌入拒绝 → 文档降级（词法仍可用）。
- 其余：HNSW + `vector_cosine_ops`；独立 `search` Celery 队列；SearchHistory 暂缓；规则派生理由（Gate B）。

---

## 1. Gate A 范围（已实现）

| 能力 | 落点 |
|---|---|
| pgvector / pg_trgm 扩展 | 迁移 `0007_semantic_search`：`CREATE EXTENSION IF NOT EXISTS vector / pg_trgm` |
| 检索文档表 | `shot_search_document`（见 §3）|
| Embedding 抽象 | `clipmind_shared/ai/embedding.py`（`EmbeddingProvider` 协议、身份、能力、健康、E5 前缀、L2 归一）|
| FakeEmbeddingProvider | `providers/fake_embedding.py`（确定性、内容相关、384 维，CI/降级）|
| OpenAICompatibleEmbeddingProvider | `providers/openai_embedding.py`（E5 前缀 + 维度校验 + L2 归一 + 错误分类）|
| 工厂 | `embedding_factory.py`：`fake` / `openai_compatible` / 未配置占位 |
| 本地 embedder 微服务 | `services/embedder/`（FastAPI + sentence-transformers）+ `infra/embedder.Dockerfile`（profile `embedding`）|
| 检索文档构建器 | `clipmind_shared/search/document.py`（有效结果 → 文本 + 归一化 + 轴 + 哈希）|
| 索引器 | `services/worker/clipmind_worker/search/indexer.py`（幂等重建 + 有效结果解析）|
| search 队列任务 | `search/tasks.py`：单镜头 / 单素材 / sweeper |
| 触发 | AI 分析提交后（worker）、人工审核提交后（API）入队重建；sweeper + 回填兜底 |
| 回填 | `scripts/backfill_search_documents.py`（幂等，多参数）|
| 测试 / E2E / 文档 | shared/worker/api 单测 + `scripts/ci_search_e2e.py` + 本文 |

**Gate A 不实现**（留 Gate B/C）：自然语言 Query Parser、Hybrid Search API、画面描述匹配 API、
综合排序公式、匹配理由 API、UI 参考图 04、PR-05 脚本匹配。

---

## 2. 服务拓扑

默认 9 服务（`docker compose up -d`）：postgres / redis / migrate / api / worker / media-worker /
ai-worker / **search-worker** / web。`search-worker` 消费 `search` 队列，仅访问 DB/redis/embedder，
**不挂载源目录或派生数据**。

可选 `embedder`（profile `embedding`，含 torch + 多语模型，体积大）：
```bash
docker compose --profile embedding up -d embedder   # 本地真实语义检索
```
默认 `docker compose up`（含 CI）**不构建/启动** embedder，避免下载 torch 与模型；CI 用
`EMBEDDING_PROVIDER=fake` 验证索引链路水密。

---

## 3. 数据模型 `shot_search_document`

每个 `(shot_id, shot_generation)` 至多一条（唯一约束 `uq_search_doc_shot_gen`）；shot 被重检测删除
则文档随之级联清理（与 `ai_shot_analysis`/`shot_tag` 一致）。

要点列：`effective_source`(human/ai)、`source_ai_analysis_id`/`source_review_state_id`（溯源）、
`source_review_lock_version`（人工来源时记审核行版本，供 sweeper 检测内容漂移）、
`review_status`、`search_document`（自然语言，供嵌入）、`normalized_document`（供 pg_trgm）、
`search_document_hash`、`document_template_version`、`embedding vector(384)`、嵌入身份
（`embedding_provider/model/model_revision/dimension/version/normalization_version`）、
**`document_status`**（pending/indexed/excluded）、**`embedding_status`**（pending/embedding/
completed/degraded/failed）、`is_searchable`（= document_status==indexed）、`retry_count`、
`error_message`、`indexed_at`/`embedded_at`。

索引：B-tree（asset_id / document_status / embedding_status / is_searchable / doc_hash /
embedding_version / 两个 source）、GIN(pg_trgm) on `normalized_document`、
HNSW(`vector_cosine_ops`, m=16, ef_construction=64) on `embedding`。

**召回门控（Gate B 契约）**：非向量召回（词法/pg_trgm/标签/产品/结构化）= `is_searchable=true`；
向量召回 = `is_searchable=true AND embedding_status='completed' AND embedding IS NOT NULL AND
embedding_version = <当前 Provider>`；默认排除 = `is_searchable=false`（document_status=excluded）。

> 时长/画幅/审核状态/来源目录等**结构化过滤维度不进嵌入文本**（避免噪声），Gate B 经列与对
> `shot`/`asset`/`shot_review_state` 的联接承载。

---

## 4. 有效结果规则（与 PR-03B 一致，不另起一套）

索引器 `resolve_effective` 对齐 `review_service.compute_effective`：
1. confirmed/modified 且未 stale → 人工结果（`effective_source=human`，记 `source_review_state_id`）；
2. unreviewed/pending → 最新成功 AI（`effective_source=ai`，记 `source_ai_analysis_id`）；
3. 人工 stale（generation 变或被标 stale）→ 回退最新 AI；
4. rejected/unable/无结果 → 保留记录、`is_searchable=false`、`index_status=excluded`、不嵌入；
5. 新 generation → 旧文档随旧 shot 级联删除，不继承。

文档内容覆盖：有效描述、产品（名/品牌/型号/SKU/别名）、场景、动作、镜头类型、人物、营销用途、
卖点、可见文字、Logo/品牌、推荐场景、搜索关键词。模板顺序固定、section 内去重保序 → 相同数据
必得相同哈希。

---

## 5. 幂等与重嵌（§8）

仅当**全部**满足才跳过重嵌：`search_document_hash` 同 + 嵌入身份全同
（provider/model/model_revision/dimension/embedding_version）+ `document_template_version` 同 +
`embedding_status=completed` + 向量非空。任一不符或 `--force-reembed` → 重建。

→ 内容变更、模型/维度/版本变更、模板版本变更都会触发重嵌；模型升级用回填全量重建，查询期不混用
旧版本向量（`embedding_version` 区分）。

---

## 6. 任务触发与事务边界（§10）

- **上游提交后才入队**（绝不在 flush 后 commit 前发任务）：
  - AI：`analyze_asset_ai`/`analyze_shot_ai` 在 `run_asset_analysis` 提交后入队 `search` 重建；
  - 人工审核：`review` 路由在 `apply_review` 提交后入队单镜头重建。
- **入队失败不影响上游**（try/except + 日志），由 **sweeper** 与 **回填脚本** 兜底恢复。
- **sweeper 过期识别**（`shots_needing_index`，纯 SQL）：缺当前代次文档、嵌入 pending/embedding/
  failed/**degraded**（Provider 恢复后重嵌）、`document_template_version` 漂移、`embedding_version`
  漂移（completed 但版本 != 当前 Provider，即模型/维度/revision 变更）、**审核内容漂移**（当前代次审核行的
  `id` / `review_status` / **`lock_version`** 任一与文档记录不一致 —— `lock_version` 在 confirm/modify/reject/
  unable/reopen 后均自增，故能捕获同一审核行内 `confirmed_result`/`confirmed_product`/状态/stale 的变化，
  即使审核钩子丢失）。注：AI 同行内容变化（同 id、`parsed_result` 变 → 文档哈希变）
  由 AI 完成钩子入队 + 周期性全量 backfill 覆盖（纯 SQL 无法在不重算文档的情况下检测内容哈希）。
- 索引器**幂等**；同 `(shot,generation)` 唯一约束下并发触发 → IntegrityError 重试一次（改走更新路径）。
- 瞬时 provider 故障（timeout/unavailable/rate-limited）→ Celery 退避重试（≤3 次）；永久错误记 `failed`，不无限重试。

**旧 generation 退出检索（已核实）**：重拆镜头时 `media._finalize` 在 T2 事务**新建新代次 Shot 行 +
删除旧代次 Shot 行**（shot_id 永不就地改 generation）；`shot_search_document.shot_id` FK `ON DELETE
CASCADE` → 旧代次文档随旧 Shot 级联删除，绝不残留为 searchable。新 Shot 由 AI 完成钩子触发建新文档。

---

## 7. 本地 embedder 微服务

OpenAI 兼容：`POST /embeddings`（`{model, input}` → `{object,data:[{index,embedding}],model,usage}`）、
`GET /health`（进程存活，**不代表模型已加载**）、`GET /ready`（模型加载成功才 200）。模型后台线程加载；
不加 E5 前缀（由调用端 provider 负责）、不归一化（由 provider L2 归一）；不记录业务文本与密钥；
限制批量/单条长度；OOM/缺模型/非法输入返回明确错误。

**模型选择固定**：服务端只加载 `EMBEDDER_MODEL`（启动时），请求体的 `model` 字段仅回显、**绝不**
用于选择/下载模型——客户端无法借此触发任意模型下载。

**网络暴露**：内部服务，容器间以 `embedder:8100` 互访；仅 `127.0.0.1:${EMBEDDER_PORT:-8100}` 绑定
供本地验收，**不对公网开放**；NAS 生产可移除 `ports`。请求体/批量/文本长度有上限。

**模型缓存与离线**：模型缓存于独立卷 `embedder-models`（`HF_HOME=/models`）。**首次部署需联网下载**
（multilingual-e5-small 约 470MB）；之后停止/重启 **从缓存加载、不重新下载**，断网亦可启动。
NAS 离线部署须先在有网环境预热该卷。模型源码目录只读，仅缓存卷可写。

**revision 升级流程**：固定 `EMBEDDING_MODEL_REVISION`/`EMBEDDER_MODEL_REVISION` 为不可变 commit SHA；
升级 = 改 revision → `embedding_version` 变 → sweeper/`backfill --force-reembed` 全量重嵌 → 查询期不混用旧向量。

---

## 8. 配置（`.env`）

`EMBEDDING_PROVIDER`（""=未配置→degraded | `fake` | `openai_compatible`）、`EMBEDDING_BASE_URL`
（容器内 `http://embedder:8100`）、`EMBEDDING_API_KEY`、`EMBEDDING_MODEL`（默认 `intfloat/multilingual-e5-small`）、
`EMBEDDING_MODEL_REVISION`（默认即不可变 commit `614241f6…`，可覆盖；空/main/latest/head 时 fail-closed）、
`EMBEDDING_REQUIRE_PINNED_REVISION=true`、`EMBEDDING_DIMENSION=384`（须与 vector 列一致）、
`EMBEDDING_PREFIX_SCHEME=e5`、`SEARCH_WORKER_CONCURRENCY`、`EMBEDDER_*`（embedder 服务，revision 须同值）。
密钥仅置 `.env` 与请求头，绝不入库/日志/前端。

---

## 9. 测试与验证

- 单元（shared，无需 DB）：FakeEmbedding 确定性/非恒定/维度/批序/内容相关/身份；OpenAI 兼容
  provider（E5 前缀/归一/维度校验/批序/错误分类）；工厂；检索文档（覆盖/稳定哈希/空/产品词/版本）。
- DB（worker，需 `TEST_DATABASE_URL`+pgvector）：索引器 AI/人工来源、幂等跳过、内容/模型变更重嵌、
  **degraded 仍可词法检索（不进向量）**、**provider 恢复后经 sweeper 重嵌**、**未固定 revision fail-closed**、
  rejected 排除、向量入库往返、**sweeper 过期识别（degraded/版本漂移/审核漂移）**、**旧 generation 级联退出检索**。
- API（需 DB）：审核动作提交后入队检索文档重建。
- 迁移 roundtrip：`test_migrations.py` 自动 upgrade→downgrade→upgrade（CI 验证 0007）；`alembic check`
  确认模型↔迁移无漂移。
- 现有数据迁移（本地）：复制本机 0006 数据库 → upgrade 0007（业务数据不变）→ backfill（幂等）→
  downgrade 0006（保留 vector/pg_trgm 扩展、业务表完好）→ 再 upgrade。
- pg_trgm/HNSW：`EXPLAIN` 确认 `ix_ssd_embedding_hnsw`(KNN) 与 `ix_ssd_norm_trgm`(ILIKE) 实际可用。
- Docker E2E：`scripts/ci_search_e2e.py`（`EMBEDDING_PROVIDER=fake`，断言 AI/审核后自动生成
  completed 文档、向量 384 维、确认切 human、驳回转 excluded、重启持久化；输出 `SEARCH_E2E_OK`/`SEARCH_E2E_PERSIST_OK`）。
- 真实模型最低验收（本地，非 CI）：`scripts/verify_embedder.py`（中/英/混合近义高于无关、维度、
  批序稳定、可复现）；先 `docker compose --profile embedding up -d embedder`。

---

## 10. Gate B（已实现）= Query Parser + Hybrid Search API + 画面描述匹配

### 10.1 查询解析（`clipmind_shared/search/parser*.py`）

统一契约 `SearchQueryParser.parse(query) -> ParsedSearchQuery`（同步；API 在 threadpool 调用）。三实现：

- `RuleBasedQueryParser`：确定性规则抽取（画幅/时长/否定/排除风险/confirmed-only/关键词），
  是所有 LLM 解析失败时的**降级兜底**与无 AI 配置时的默认。
- `FakeQueryParser`：确定性，CI 替身 LLM（`parser_provider="fake"`）。
- `MiMoQueryParser`：复用 PR-03A MiMo `/chat/completions`（纯文本端点），输出**严格结构化 JSON**。

`ParsedSearchQuery` 严格校验：枚举白名单（`aspect_ratios`/`review_statuses`）、数值 clamp、未知字段忽略。
**Prompt Injection 防护**：LLM 只能填充已知字段，枚举白名单预过滤，未知字段丢弃；解析器不产出
字段名/表名/排序表达式，所有值仅作绑定参数。失败（超时/鉴权/非法 JSON/校验）→ 回退规则解析，
`parser_status=degraded` + 告警，**不阻断词法检索、不假装语义解析成功**。

### 10.2 召回与融合（`apps/api/app/services/search_service.py`）

四召回通道（均在 DB 内完成，候选池有界 `SEARCH_CANDIDATE_POOL`）：

| 通道 | 机制 | 门控 |
|---|---|---|
| Vector | pgvector `<=>` cosine + HNSW | `is_searchable AND embedding_status='completed' AND embedding IS NOT NULL AND embedding_version=<当前 provider>` |
| Lexical | pg_trgm `%` / ILIKE + `similarity()` 排序 | `is_searchable` |
| Tag | `shot_tag` EXISTS（**有效来源**：human/ai，镜像 `shot_filter`） | `is_searchable` |
| Product | product/alias/asset_product/confirmed_product，**七档优先级** | `is_searchable` |

产品打分阶梯（`match_kind`）：SKU 精确 1.0 > 型号 0.95 > 产品名 0.85 > 别名 0.75 > 品牌 0.65；
**人工确认的 shot-level 产品**（`confirmed_product_id`）较仅素材级关联 **+0.05** 加成（未到上限时体现），
即"confirmed 优先于 asset"。`exact`（SKU/型号）另享 `EXACT_PRODUCT_BONUS`。产品候选**只读，绝不写回绑定**。

融合：**RRF（名次鲁棒）+ 在场通道加权均值（量纲感知、缺失不判 0）**，叠加精确产品加权 / 审核加权 /
质量加权 / 风险软惩罚。稳定 tie-breaker：`final↓ quality↓ human优先 created_at↑ shot_id↑` → 全序、
分页不重不丢。各分项分 [0,1]（缺失为 null，绝不伪造 0），对外匹配度展示一位小数。

**结构化硬过滤**（WHERE，作用于所有通道基查询）：review 状态排除/筛选、confirmed_only、stale、时长、
画幅（width/height±容差）、source_directory、时间范围、`excluded_risks`（NOT EXISTS）/`required_risks`
（EXISTS）、显式 product_ids、**显式 request 传入的 scenes/actions/shot_types/marketing_uses**（标签 EXISTS，
按有效来源；解析得到的同名字段仅作软召回+解释，不硬过滤）、**negative_terms**（归一文档 NOT ILIKE 硬排除）。
`required_risks` 与 `exclude_risks` 冲突 → **HTTP 422**（不静默二选一）。`include_excluded` 仅显式生效。
> 说明：画质 `quality_levels` 为软信号（参与词法召回、质量评分与解释），不做硬过滤（质量标签语义为
> "质量问题"，硬过滤会语义反转）。

### 10.3 规则派生解释（`clipmind_shared/search/explain.py`）

匹配理由/不匹配项/风险提示**全部来自真实命中事实**：产品精确/别名、场景/动作/镜头类型/营销命中、
语义相似（**仅当真实进入向量召回且未降级**）、已人工确认、风险已排除；不匹配项含产品不一致、
场景仅相似、动作不完整、质量不足、缺人工确认、**embedding 降级**；风险提示来自真实 risk 标签。
绝不由 LLM 自由生成、绝不编造画面对象、绝不写营销文案。

### 10.4 API 契约（Gate C 可直接消费）

- `POST /api/search/shots` → `ShotSearchResponse`：`items / total / filtered_total / truncated /
  page / page_size / search_mode_used / parser_status / parser_provider /
  embedding_status(ok|degraded|unavailable) / degraded / degradation_reasons / elapsed_ms /
  query_plan_summary / parsed_query`；每个 item 含 shot 基础信息、asset、preview/thumbnail/keyframe/
  download_url、product、`score`/`match_percent`、分项分、`matched_reasons`/`unmatched_requirements`/
  `risk_warnings`、`review_status`/`review_is_stale`/`embedding_degraded`。
  - **total 语义**（关键）：`total` = 进入融合排序、**可分页**的候选数；`truncated=false` 时即满足召回的
    精确匹配数，`truncated=true` 时为候选池上限下的**下界**（存在更多匹配未进池）。`filtered_total` =
    满足**硬结构化过滤**的精确总数（"可检索宇宙"，独立于软召回，供"共 N 条可检索"展示）。
    分页基于 `total`（融合后的稳定有界候选集）。绝不返回"看似精确实则封顶约 200"的 total。
  - `search_mode`：hybrid|semantic|lexical|structured；`sort`：relevance|latest|duration|quality
    （固定方向：relevance/quality/latest 降序、duration 升序；latest 兼容旧名 newest）。
- `POST /api/match/description` → `DescriptionMatchResponse`：复用候选，响应含 `total/filtered_total/
  truncated/minimum_score/target_requirements`，每个 item 叠加 `target_requirements /
  matched_requirements / unmatched_requirements（与搜索 item 同名）/ requires_human_confirmation /
  recommendation_level`（规则派生、阈值稳定）。`allow_similar_scene/action` 控制场景/动作是否硬过滤；
  `minimum_score` 仅过滤返回项，不影响 total 计数。
- `GET /api/search/suggestions`：产品/别名/品牌/有效标签（不实现 SearchHistory）。
- `GET /api/search/index/status`：文档/嵌入计数、版本一致性、stale、provider 健康。
- `POST /api/search/index/rebuild/shot/{id}`、`/rebuild/asset/{id}`、`/sweep`、`/backfill`
  （`force_reembed`/`only_failed` 显式参数；危险操作不静默全量重嵌）。**当前无鉴权体系，
  管理端不伪造用户权限，PR-07 接入前为本地管理端限制。**

### 10.5 降级矩阵（真实可见，绝不伪造）

| 失败点 | 行为 |
|---|---|
| Query Parser 失败/超时 | 规则解析；`parser_status=degraded`；词法/结构化不受影响 |
| Embedding 不可用 | 跳过向量；`embedding_status=degraded` + 原因；词法/标签/产品/结构化继续 |
| 索引降级文档 | 词法/标签命中、`embedding_degraded=true`、不出现“语义相似”理由 |
| 召回为空 | 真实空结果（不伪造） |

### 10.6 配置（新增）

`SEARCH_QUERY_PARSER`（""/auto|fake|rulebased|mimo）、`SEARCH_PARSER_MODEL`（默认 mimo-v2.5-pro）、
`SEARCH_PARSER_TIMEOUT`、`SEARCH_CANDIDATE_POOL`、`AI_API_KEY_HEADER`（API 侧 mimo 解析鉴权头）。

### 10.7 测试与 E2E

- 单元（shared，无 DB）：解析器（中/英/混/否定/排除风险/时长/画幅/confirmed/注入/非法 JSON/超时/
  降级/Fake 确定性）、融合（RRF/缺失向量不判 0/精确产品加权/稳定排序/稳定分页）、规则解释。
- API（需 DB）：hybrid/lexical/structured、degraded 词法命中不进向量、精确 SKU、场景过滤、风险排除、
  画幅/时长、confirmed、include_excluded、稳定分页、页大小上限、非法枚举、描述匹配、建议、索引状态、重建；
  **Gate B.1 增**：negative_terms 硬排除、required/excluded 冲突 422、latest/duration/quality 排序、
  300+ 文档下 total/filtered_total/truncated 与稳定分页、产品七档优先级（SKU>型号、confirmed>asset）、
  显式 request 场景硬过滤、显式 product_id 不被语义越过、lexical/structured 不触碰向量、描述匹配
  minimum_score 回显与字段、写操作不可经 GET（405）。
- worker：回填选取（全量/仅失败/有界）。
- Docker E2E：`scripts/ci_hybrid_search_e2e.py`（`HYBRID_SEARCH_E2E_OK` / `DESCRIPTION_MATCH_E2E_OK` /
  `SEARCH_API_PERSIST_OK`）。

## 11. 留待 Gate C / PR-05

UI 参考图 04（搜索页/匹配页）、SearchHistory、真实 MiMo Parser 大规模验收、性能 ≤3s 首屏专项压测、
脚本段落匹配与剪辑清单（PR-05）、鉴权（PR-07）。
