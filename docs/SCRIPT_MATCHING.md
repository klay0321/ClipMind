# 脚本匹配与剪辑清单（SCRIPT_MATCHING）— PR-05

> 本文记录 PR-05 的工程方案与 **Gate A（脚本数据模型 + 拆段解析 + 项目/段落 API）** 的落地。
> 最高事实来源为 `docs/PRODUCT_REQUIREMENTS.md`（7.12）。Gate B（候选匹配/选择锁定/剪辑清单/
> CSV 导出）与 Gate C（UI 参考图 03 + 真实页面 E2E）见后续提交。

## 1. Gate 拆分

- **Gate A（本 PR）**：脚本持久化 + 拆段（RuleBased/Fake/MiMo 解析器，失败降级）+ 三表数据基础
  （含 `generation` / `locked_shot_id` / `lock_version`）+ 段落 CRUD/重排 API + Fake CI/Docker E2E
  + 真实 MiMo 拆段本地验收。**不做** 候选匹配写入、CSV 导出、前端 UI。
- **Gate B**：每段画面需求复用 Hybrid Search / `run_description_match` 召回候选并写入
  `script_shot_candidate`；人工选择/锁定执行；单段重匹配（代次原子替换）；剪辑清单 + CSV 导出
  （新增 `export` 队列消费者）。
- **Gate C**：UI 参考图 03（路由 `/script`）+ 真实页面 E2E + 真实产品素材最终业务验收。

## 2. 数据模型（migration `0008_script_matching`，down_revision `0007_semantic_search`）

- **script_project**：`raw_script` / `normalized_script` / `script_hash`（唯一，幂等）/ `status`
  / `parse_status` / `parser_provider` / `parser_model` / `parser_warnings` / `result_schema_version`。
- **script_segment**：`order_index`（项目内唯一）/ `segment_text` / `visual_requirement`
  / `target_duration_min|max` / `product_id`（SET NULL）/ `structured_requirements`(JSONB)
  / `negative_terms` / `excluded_risks` / `allow_similar_scene|action`
  / `current_generation` / `locked_shot_id`（SET NULL）/ `lock_version` / `candidates_stale`。
- **script_shot_candidate**：`generation` / `shot_id` / `rank` / 各分项评分 / `matched_reasons`
  / `unmatched_requirements` / `risk_warnings`；`(segment_id, generation, shot_id)` 唯一。
  **Gate A 仅建表，不写入候选**。

### 语义

- **generation**：候选随代次替换的基础——Gate B 单段重匹配生成新代次候选，旧代次在新代次完整
  成功前可用（原子代次替换）。`generation >= 1`。
- **locked_shot_id**：人工锁定的镜头。重新拆段（`/parse`）默认**拒绝**丢弃已锁定段落（须 `force=true`，
  且 force 会在 `parser_warnings` 追加 `forced_reparse_cleared_N_locked_segments`）。删候选不触碰它。
- **lock_version**：段落乐观锁版本。编辑经 **DB 层条件更新**（`WHERE lock_version=expected`，rowcount=0 → 409）
  原子递增，消除读后写竞态。编辑影响需求字段时置 `candidates_stale=true`（提示 Gate B 重匹配；Gate A 不自动重匹配）。

## 3. 解析器架构（`clipmind_shared/script/`）

- `schema.py`：`ParsedScript` / `ParsedScriptSegment` 严格校验（段数/单段长度/列表去重限量/时长 clamp）。
- `parser.py`：`RuleBasedScriptParser`（确定性拆段：空行 + 句末标点，剔除纯标点/空白段，保守抽取
  时长/否定/风险，受控词表留给 LLM）、`FakeScriptParser`（CI 替身，复用规则、绝不联网）、
  工厂 `get_script_parser` + `split_segments`。
- `parser_mimo.py`：`MiMoScriptParser`（复用 MiMo OpenAI 兼容调用；纯文本端点；System Prompt 禁止
  执行指令、只输出 JSON、**绝不输出 shot_id**；超时/鉴权/非法 JSON/校验失败/空段/未配置 → 降级
  RuleBased 并标 `parser_status=degraded` + 告警；不记录脚本原文/密钥）。

安全红线：LLM 只产出受控字段值（绑定参数），绝不进 SQL；绝不返回/决定 `shot_id`；绝不修改 `locked_shot_id`。

## 4. API 契约（前缀 `/api`）

- `POST /scripts`（创建，按内容哈希幂等）、`GET /scripts`（分页）、`GET /scripts/{id}`（含段落）、
  `PATCH /scripts/{id}`（改名）；
- `POST /scripts/{id}/parse?force=`（拆段，事务替换段落；锁定段保护）；
- `PATCH /scripts/{id}/segments/{sid}`（乐观锁编辑，`extra="forbid"`，`structured_requirements` 键白名单）；
- `POST /scripts/{id}/segments/reorder`（整项目段落重排，两阶段防唯一冲突）。

本阶段 API 不返回伪造候选、不自动匹配、不自动写 `locked_shot_id`、不接受任意字段/任意 task 名。

## 5. 测试与验收

- 自动化回归（无密钥）：parser 单测、API 生命周期、迁移往返、Fake Docker Gate A E2E
  （`SCRIPT_GATE_A_E2E_OK` / `SCRIPT_GATE_A_PERSIST_OK`）。
- 真实业务验收（本地、不入库）：真实 MiMo 拆段对真实产品脚本 `provider=mimo / status=ok / 非降级`、
  不同脚本不同结构、产品/场景/动作/时长准确；见 `docs/REAL_MEDIA_ACCEPTANCE.md` 与
  `.local/real-media-acceptance/`（Git 忽略）。

## 6. 已知历史脏数据：空检索文档（shot58）

历史上存在 1 条空 `shot_search_document`（`search_document` 为空但 `is_searchable=true` 且嵌入了空串），
空串向量对任意查询给出近似恒定相似度，污染混合检索排序。

- **根因**：旧索引在“有效结果产出空文档”（如人工确认但内容为空且无 AI 结果）时仍标 indexed+searchable。
- **本 PR 防护**：`search/indexer.py` 增最小防护——空文档标 `document_status=excluded`、`is_searchable=false`、
  不嵌入；`test_search_indexer` 增回归用例。
- **历史行清理（后续，非本 PR）**：不在本 PR 自动改业务数据。后续用显式 **dry-run + 限定 shot/document id +
  事务 + 确认参数** 的 sweeper/backfill 清理该历史行（防护已确保不再新增）。
</content>
