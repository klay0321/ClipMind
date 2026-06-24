# PR-03A：AI 镜头理解分析基础（SHOT_AI_ANALYSIS）

> 分支：`feat/ai-analysis-foundation`（从最新 main）。迁移：`0005_ai_analysis`。新增 worker：`ai-worker`（队列 `ai`）。
> 关联：`docs/AI_PROVIDER_PLAN.md`（接入抽象/探测/降级/成本/密钥）、`docs/PROJECT_COMPLETION_PLAN.md`（路线）、`docs/PRODUCT_REQUIREMENTS.md`（7.6 结构化输出、12.8 调用记录）。

## 1. 范围

在 PR-02 的镜头与关键帧之上，接入外部 AI（小米 MiMo / OpenAI 兼容）对镜头**多关键帧**做结构化画面理解，落库可审核的原始结果，并在素材页/镜头页展示**真实 AI 状态**。

**本 PR 做**：Provider 抽象 + 工厂 + FakeProvider + MiMoProvider；能力探测脚本；结构化 JSON Schema（Pydantic 权威）；输入指纹与缓存去重（不重复计费）；`ai-worker` 与单镜头/单素材批量分析；调用状态机、超时/限流/重试、降级（无图不伪造）；调用与 Token/成本台账；素材页/镜头页真实 AI 状态 UI；FakeProvider 驱动的确定性 e2e。

**本 PR 不做（留后续）**：产品库、标签拆解入库、人工审核 UI（确认/修改/驳回/无法判断）、Shot 的 AI 列、pgvector 向量、搜索/匹配/脚本 —— 见第 9 节边界。

## 2. 数据模型（迁移 `0005_ai_analysis`，down_revision=`0004_asset_poster`）

- **`ai_analysis_run`**（素材级运行，仿 `MediaProcessingRun`）：`run_uuid, asset_id, celery_task_id, status(AIRunStatus), progress, current_step, total_shots/analyzed_shots/failed_shots/skipped_cached, degraded, provider, model, prompt_version, schema_version, capabilities_snapshot(JSONB), error_message, queued/started/heartbeat/finished_at, worker_name`。**部分唯一索引 `uq_active_ai_run`**：同素材至多一个活动运行（queued/running）。
- **`ai_shot_analysis`**（每镜头当前结果，唯一 `shot_id`）：`shot_id, run_id, asset_id, provider, model, prompt_version, schema_version, input_fingerprint(idx), input_summary(JSONB), parsed_result(JSONB), raw_response_excerpt(脱敏截断), confidence, status(AIShotAnalysisStatus), degraded_reason, duration_ms`。镜头被重检测删除时随之级联删除。
- **`ai_call_log`**（每次调用脱敏台账）：`run_id?/shot_id?/asset_id?(SET NULL 保留), provider, model, method, attempt_no, input_images, input_tokens, output_tokens, est_cost, duration_ms, status(AICallStatus), http_status, error_code`。**无密钥、无敏感原文。**

枚举：`AIRunStatus(queued/running/completed/partial/failed/cancelled)`、`AIShotAnalysisStatus(pending/completed/degraded/failed/skipped)`、`AICallStatus(success/retry/failed/timeout/rate_limited/degraded)`。迁移可正反向、`alembic check` 无漂移。

## 3. Provider 抽象与实现（`packages/shared/clipmind_shared/ai`）

- `providers/base.py`：`VisualAnalysisProvider` 协议（`capabilities()/health()/analyze_frames(frames, *, prompt, schema, timeout)`）、`FrameRef/Usage/AnalyzeOutcome`、异常分类 `ProviderAuthError/Timeout/RateLimited/BadResponse/Unavailable/NotConfigured`。
- `providers/fake.py`：`FakeProvider`，确定性产出 Schema 合规结果（测试/CI/`AI_PROVIDER=fake`）；`supports_images=False` 时返回 degraded（绝不伪造视觉）。
- `providers/mimo.py`：`MiMoProvider`，OpenAI 兼容 `/chat/completions`，多关键帧 Base64 内联图 + `response_format=json_object`；错误按 HTTP 分类；**密钥仅置请求头**。
- `factory.py`：`get_provider(name, …)` → `fake | mimo | NotConfiguredVisualProvider`（未配置显式报错，不返回假数据；mimo 惰性导入）。
- `schema.py`：`ShotAnalysisResult`（Pydantic 权威 Schema，对齐 PRD 7.6.2 ~20 字段，缺字段留空不编造）+ `shot_analysis_json_schema()` 导出 + `validate_shot_analysis()`。
- `fingerprint.py`：`compute_fingerprint(frame_hashes, provider, model, prompt_version, schema_version, params)`；`hash_file()` 读关键帧内容。
- `prompt.py`：`PROMPT_VERSION` + 仅输出 JSON、不编造、不确定标人工的系统提示词。

## 4. Worker 与任务（`services/worker/clipmind_worker/ai`）

- `runner.py`（纯逻辑，可单测）：取素材 READY 镜头 → 逐镜头解析多关键帧+算指纹 → 命中缓存(已 completed 同指纹)则跳过、不计费 → 否则调用 provider（超时/限流/坏响应按 `AI_RETRIES` 指数退避；鉴权/未配置致命不重试）→ Schema 校验 → upsert `ai_shot_analysis` + 写 `ai_call_log` → 进度/心跳。无图能力 → degraded（不伪造）。run 状态机：`completed`（无失败）/`partial`（部分失败）/`failed`（致命或全失败）。
- `tasks.py`：`analyze_asset_ai(run_id)`、`analyze_shot_ai(run_id, shot_id)`；素材级 advisory lock `0x4149` + `acks_late` 断点恢复 + 失败恢复 asset 状态。
- `ai-worker`：`celery -A clipmind_worker.celery_app worker -Q ai -c ${AI_WORKER_CONCURRENCY:-2}`（compose 第 8 个服务）。

## 5. API（`apps/api/app/routers/ai.py`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/assets/{id}/analyze` | 入队素材级 AI 分析（202） |
| POST | `/api/assets/{id}/ai-analysis/retry` | 重试（活动运行幂等） |
| GET | `/api/assets/{id}/ai-analysis` | 轮询运行状态/进度/已分析数 |
| POST | `/api/shots/{id}/analyze` | 单镜头 AI 分析（202） |
| GET | `/api/shots/{id}/ai` | 镜头当前 AI 结果（只读，标注待人工审核） |
| GET | `/api/ai/provider/health` | provider 健康/配置回显（不联网、不回显密钥） |

入队沿用 `建行→flush(部分唯一索引兜底)→commit→send_task(ai 队列)→回写 celery_task_id`。素材列表富化 `ai_analysis_status` + `ai_analyzed_total`。

## 6. 前端

- `ShotDetail`：真实 AI 面板（状态/一句话描述/置信度/待人工确认/风险黄红/降级说明），可发起单镜头分析并轮询；移除"将在 PR-03 提供"占位。
- `AssetTable`：显示真实 AI 运行状态与已分析镜头数；可发起素材级 AI 分析（`onAnalyzeAi`）。**不显示伪造标签**；AI 原始结果明确标注"待人工审核"（与 PR-03B 人工结果区分）。

## 7. 环境变量（`.env.example`，密钥仅本地）

`AI_PROVIDER`（空=未配置 / `fake` / `mimo`）、`AI_BASE_URL`、`AI_API_KEY`、`AI_MODEL`、`AI_MAX_IMAGES`、`AI_TIMEOUT`、`AI_RETRIES`、`AI_PROMPT_VERSION`、`AI_WORKER_CONCURRENCY`、`AI_PRICE_INPUT_PER_1K`、`AI_PRICE_OUTPUT_PER_1K`。**密钥绝不入代码/库/日志/前端/Git。**

## 8. 能力探测（`scripts/probe_ai_provider.py`）

只读 `.env` 取配置，输出**脱敏**报告；覆盖 AI_PROVIDER_PLAN 第 2 节 17 项（连通/鉴权/兼容/文本/JSON/Schema/单图/多图/Base64/Embedding/时延自动；URL图/上下文/并发/限流/数据保留标 manual）。**真实 Provider 接入前先跑探测，据 `ProviderCapabilities` 决定调用与降级；任一关键项失败则相关能力默认不支持。** 未配置时优雅退出。

## 9. 与 PR-03B 边界

PR-03A 仅交付**引擎 + 原始结构化结果 + 调用/成本台账 + 真实状态 UI**。PR-03B 才做：产品主数据/参考图/别名/候选识别、标签体系（场景/动作/镜头类型/营销/卖点/可见文字/Logo/质量/风险）入库、审核状态机（待审/确认/修改/驳回/无法判断）、审核日志、**人工结果优先且重新分析不覆盖人工确认**、UI 参考图 01/02 完整功能。

## 10. 测试

- 共享层：Schema 校验、指纹、FakeProvider、工厂、MiMoProvider（httpx MockTransport，无网络）。
- worker：runner 完成/缓存/降级/全失败/致命鉴权（FakeProvider + 桩 provider）。
- API：入队/幂等/404/409/状态/单镜头/结果/健康。
- 前端：AI 面板真实结果展示 + 触发（vitest）。
- CI：`AI_PROVIDER=fake` 让 `docker-e2e` 全栈确定性验证 AI 链路并校验 `ai-worker` 运行。
