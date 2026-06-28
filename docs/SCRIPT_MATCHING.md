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

---

## 7. Gate B：候选匹配 / 选择锁定 / 剪辑清单 / CSV 导出

> 实现于 `feat/script-shot-matching-gate-b`。不做 `/script` UI（Gate C）、XLSX/JSON/Markdown/ZIP、SearchHistory、鉴权。

### 7.1 数据模型（migration `0009_script_matching_selection`，down_revision `0008`）

- `script_segment` 增列：
  - `selected_shot_id`（FK shot SET NULL）：**人工选择**（区别于 `locked_shot_id` **锁定**）；
  - `match_status`：`pending`（从未匹配）/ `matched` / `gap`（匹配后真实无结果）/ `degraded`；
  - `match_summary`(JSONB)：`best_score` / `candidate_count` / `gap_reasons` / `reshoot_recommendation`
    / `requires_human_confirmation` / `degraded` / `generation` / `match_token`（幂等）；
  - `matched_at`：上次匹配完成时刻（NULL=从未匹配，用于区分 pending 与真实 gap）。
- 新建 `script_export`（脚本剪辑清单 CSV 导出记录，复用 `export_status` 枚举与 `export` 队列；与片段视频
  导出 `export` 表**分离**，语义不同）。时长建议**动态计算不持久化**（候选表无需新列）。

### 7.2 候选生成：复用 Hybrid Search（绝不另写搜索）

每段候选生成调用 `search_service.run_description_match`（→ 向量/词法/标签/产品**库内召回** + RRF 融合
+ 规则解释）。段落需求经 `build_match_request` 装配为 `DescriptionMatchRequest`：

- **硬约束（不静默放宽）**：`product_id`（产品关联硬过滤）、`excluded_risks`（风险标签硬排除）、
  `negative_terms`（否定词词法硬排除）、`allow_similar_scene|action=False` 时场景/动作升格为硬过滤。
- **软信号（精确注入软通道，不依赖文本解析）**：`scenes` / `actions` / `shot_types` / `marketing_uses`
  / `quality_levels`（`DescriptionMatchRequest` 新增显式字段，默认空 → 兼容既有 PR-04 行为）。
- LLM 绝不返回/决定 `shot_id`；候选评分/理由全部来自 SQL 召回事实，绝不编造；时长**不作硬过滤**（软偏好）。

候选行直接落 `DescriptionMatchItem` 的全部分项分与 `matched_reasons`/`unmatched_requirements`/`risk_warnings`。

### 7.3 代次原子替换 / 幂等

- 首次匹配 → `generation = current_generation`（拆段后=1）；重匹配 → 已有最大代次 +1（旧代次保留）。
- 同次匹配在**一次事务**写入（候选 + 段落摘要 + `current_generation` 切换）：失败回滚 → 不留半代候选、
  不切换当前代次。并发同段同代次由唯一约束兜底 → 409 重试。
- 幂等：`match_token` 与段落上次匹配 token 相同 → 直接返回，不产生新代次。全脚本匹配派生 per-segment token。
- 当前代次为空即**真实无匹配**（`match_status=gap`），不回退旧代次冒充。历史代次可经 `?generation=` 查询。

### 7.4 人工选择 / 锁定 / 解锁（乐观锁）

- **选择**(`selected_shot_id`)：当前人工选中；**锁定**(`locked_shot_id`)：后续自动匹配不得覆盖；
  **解锁**：清锁定（保留选择记录），允许重匹配。三者经 `lock_version` **DB 条件 UPDATE** 原子递增
  （rowcount=0 → 409）。
- 校验：镜头存在且 READY、未被审核排除（rejected/unable 即便 override 也拒）、属于当前候选（否则需
  `allow_override`）。替换已存在的不同锁定须显式 `force`。**绝不反向修改镜头审核状态**。
- 锁定/选择镜头被删除（SET NULL）或 excluded 后在剪辑清单显示**失效**，不静默换片。
- 全脚本重匹配默认 `skip_locked=true` → 锁定段跳过、不覆盖。

### 7.5 全局分配（`clipmind_shared.script.editlist`，确定性纯逻辑）

优先级：人工锁定 > 人工选择 > 候选综合分（已含产品/风险/审核/质量）。在不明显降质（≤`DEDUP_MAX_SCORE_DROP`）
前提下减少同一 shot 重复（`script_match_max_reuse` 默认 1）、避免相邻段使用高度相似镜头（同 shot 或同素材+
相同场景动作标签）。候选不足允许缺口并 `allocation_warnings`。**无随机**（同输入同输出）。

### 7.6 时长建议 / 缺口 / 补拍

- 时长：`fit` / `too_long`（建议裁切，建议出点不超原范围）/ `too_short`（保留整段 + 补画面提示）/
  `no_target`；本阶段**只建议不转码**，绝不生成超出原 shot 范围的时间码。
- 缺口/补拍：规则派生（缺产品特写 / 缺场景 / 缺动作 / 风险排除后空 / 检索降级），**绝不由 LLM 编造素材事实**。

### 7.7 剪辑清单 / CSV

- 剪辑清单是**结构化编辑计划**（一行一段，含选用状态/时间码/建议入出点/匹配理由/缺口/补拍/重复/失效），
  非视频。系统推荐第一名标 `selection_status=recommended`，**绝不写成人工已确认**。
- CSV（仅 Gate B）：UTF-8 BOM、RFC4180 转义、固定列、无匹配段也成行、**CSV 公式注入防护**（用户文本以
  `= + - @` 开头加前导单引号）、不含本机路径/Key/Endpoint、安全文件名。
- export-worker（新增，消费 `export` 队列）同步重建段落视图 → 剪辑清单 → CSV 落 `script_exports/{uuid}/`，
  与 API `GET /edit-list` **共用 `editlist` 纯逻辑**，对同一数据产出一致结果。

### 7.8 API 契约（前缀 `/api`）

```
POST /scripts/{id}/match                          全脚本匹配（同步逐段；锁定段默认跳过）
POST /scripts/{id}/segments/{sid}/match           单段匹配/重匹配（新代次）
GET  /scripts/{id}/segments/{sid}/candidates       候选（默认当前代次；?generation= 查历史）
POST /scripts/{id}/segments/{sid}/select|lock|unlock  人工选择/锁定/解锁（lock_version 乐观锁）
GET  /scripts/{id}/match-status                    逐段 + 整体匹配状态
GET  /scripts/{id}/edit-list                       剪辑清单（行 + 摘要）
POST /scripts/{id}/exports/csv                     创建 CSV 导出（202 入队 export 队列）
GET  /scripts/{id}/exports/{eid}[/download]         导出状态 / 下载（未完成 409）
```

### 7.9 部署升级（重要）

Gate B 新增迁移 `0009`。升级**已有数据库**必须显式运行 `bash scripts/db_upgrade.sh`
（Windows `pwsh scripts/db_upgrade.ps1`）——`docker compose up -d` 不会重跑已成功退出的一次性
`migrate` 容器，会跳过已有库的迁移，导致 API 以旧 schema 启动并对 Gate B 接口 `500`。
`/health/ready` 在 revision 落后时返回 503 + `migration_ok=false` 供部署门禁识别。详见
`docs/DATABASE_UPGRADE.md`（新部署 / 已有库升级 / 查看 revision / 失败恢复 / 禁止 `down -v`）。

### 7.10 测试与验收

- 纯逻辑回归：`packages/shared/tests/test_script_editlist.py`（分配/时长/缺口/CSV，23 例）。
- API 回归：`apps/api/tests/test_script_match_api.py`（匹配/代次/产品硬约束/风险/缺口/选择锁定/乐观锁/
  全局分配/剪辑清单/CSV，16 例）+ `test_search_empty_doc_defense.py`（空文档防御 + 描述匹配软信号，4 例）。
- Fake Docker E2E：`scripts/ci_script_gate_b_e2e.py`（`SCRIPT_MATCH_E2E_OK` / `SCRIPT_LOCK_E2E_OK` /
  `SCRIPT_EDIT_LIST_E2E_OK` / `SCRIPT_CSV_E2E_OK` / `SCRIPT_GATE_B_PERSIST_OK`）。
- 真实业务验收（本地、不入库）：真实 MiMo + 真实 E5 + 真实产品脚本，人工核对候选排序/产品/场景/动作/缺口；
  见 `docs/REAL_MEDIA_ACCEPTANCE.md` 与 `.local/real-media-acceptance/`（Git 忽略）。
</content>
