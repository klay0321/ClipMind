# ClipMind 完整项目完成计划（PROJECT_COMPLETION_PLAN）

> 文档状态：开发执行稿（living document，每个 PR 落地后回填状态）
> 最高事实来源：`docs/PRODUCT_REQUIREMENTS.md`（需求）。本文是把完整需求拆成可交付、可验收阶段的工程化路线。
> 关联文档：`docs/UI_REFERENCE_MAP.md`（4 张参考图→功能映射）、`docs/ACCEPTANCE_MATRIX.md`（需求→PR→验收）、`docs/AI_PROVIDER_PLAN.md`（AI 接入与探测）、`docs/PR_ROADMAP.md`（早期 MVP 路线，迁移命名已被本文修订）。

---

## 0. 目的

把 ClipMind 从当前基线一步步开发到**可正式部署与验收的完整版本**。范围以《完整需求规格说明书》为准，而非"代码文件存在"。判定"完成"以第 6 节的完成定义为闸。

ClipMind 是面向公司 NAS 部署的 **AI 视频素材管理与智能匹配系统**：只读索引素材、FFmpeg 拆镜头与派生文件、外部 AI 理解打标、自然语言检索、画面/脚本匹配、剪辑清单导出。**绝不实现任何生成式视频能力**（文生/图生视频、数字人、声音克隆、视频复刻、替换人物/产品、自动成片）。文档中"生成关键帧/缩略图/代理/片段"一律指 FFmpeg 提取/裁剪/转码派生文件。

---

## 1. 当前真实基线（截至本文撰写）

- `main` = `cd92b0b`（PR-01 基础 + PR-02 拆镜头派生 + 封面/上传/关键帧条 已合并）。
- **Gate 0 发现**：`main` 曾遗漏"素材海报"合并；已由 `fix/land-asset-poster-on-main`（Draft PR）补回，落地迁移 `0004_asset_poster`。该 PR 合并前不开始 PR-03A。
- 真实迁移链：`0001_initial → 0002_shot_processing → 0003_shot_keyframes → 0004_asset_poster`。
- 现有自动化测试（海报分支实跑）：后端 `pytest` **113 passed**（pg16 测试库 + ffmpeg），前端 `npm test` **35 passed**；`ruff` / `tsc` / `next build` / `docker compose config` 全过；`alembic upgrade/downgrade/upgrade + check` 无漂移。
- 已具备：AI Provider 接口骨架（`packages/shared/clipmind_shared/ai/provider.py`，7 方法 + `ProviderCapabilities` + `NotConfiguredProvider`）、为 AI 预留的 `ai` 队列与空包 `clipmind_worker/ai/`、`.env.example` 中的 `AI_*` / `EMBEDDING_*` 键。

> 重要修正：早期 `docs/PR_ROADMAP.md` 把 PR-03 迁移命名为 `0003_ai_review`、PR-04 为 `0004_pgvector`。现实迁移链已演进到 `0004_asset_poster`，故后续迁移编号顺延（见第 4 节）。以本文为准。

---

## 2. Git 工作总规则（所有后续 PR 强制遵守）

1. 先拉取最新 `main`；
2. 从最新 `main` 创建全新功能分支；
3. 始终明确当前应在哪个分支工作；
4. 禁止直接修改 `main`；
5. 默认禁止 stacked PR（仅用户明确批准时允许）；
6. 每个 PR 的 base 必须是 `main`；
7. 前一个功能 PR 未合并前，不开始下一个功能 PR；
8. CI 未全绿不得合并；
9. 不得 force push；
10. 不得删除或覆盖未知 worktree；
11. 不得把多个阶段塞入一个巨型 PR；
12. 未经用户确认不 commit/push/建 PR、不使用真实 API Key、不连接真实 NAS。

---

## 3. 阶段路线

> 状态枚举：未开始 / 计划中 / 开发中 / 已实现 / 已验证 / 后续阶段。每阶段"退出标准"= 该 PR 合并的充分条件。

### Gate 0.5 — 落地素材海报（分支 `fix/land-asset-poster-on-main`）— 开发中
- 范围：仅补入 `feat/asset-poster` 的 4 提交（`0004_asset_poster`、`Asset.poster_path`、海报 API/worker、前端封面兜底、6 测试）。
- 退出标准：CI 全绿、独立 Draft PR 审核通过并合并。合并前**不得**开始 PR-03A。

### PR-03A — AI 分析基础（分支 `feat/ai-analysis-foundation`，迁移 `0005_ai_analysis`，新增 `ai-worker`/队列 `ai`）— 计划中
- 范围：AI Provider 抽象与工厂、MiMo 能力探测脚本、`VisualAnalysisProvider`/`TextReasoningProvider`（实现）+ `EmbeddingProvider`（接口预留）、镜头多关键帧输入、结构化 JSON Schema、输入指纹与缓存去重、AI 专用 worker、单镜头/单素材批量分析、调用状态机、超时/限流/重试、调用与 Token/成本记录、FakeProvider、真实 Provider 配置、素材页/镜头页**真实 AI 状态**。
- **不做**：完整产品库、人工审核 UI、标签拆解入库、pgvector、搜索/匹配/脚本。
- 退出标准：探测脚本可独立出报告；样例镜头产出 Schema 合规 JSON（缺字段留空不编造）；缓存命中不重复计费；无图能力时降级标注、日志不伪造视觉；密钥不入日志/代码；迁移可逆；CI 全绿（含 `AI_PROVIDER=fake` 的确定性 e2e）。

### PR-03B — AI 标签·产品库·人工审核（分支 `feat/ai-review-product-library`，迁移 `0006_ai_review_products`）— 计划中
- 范围：产品主数据/参考图/别名/候选识别；场景/动作/镜头类型/营销用途/卖点/可见文字/Logo品牌/质量/风险/置信度标签；待审核/修改/确认/驳回/无法判断状态机；审核日志；**人工结果优先、重新分析不覆盖人工确认结果**（除管理员显式覆盖）；UI 参考图 01/02 真实功能完成。
- 退出标准：标签/产品/审核闭环可用；人工修改后再分析不被覆盖；UI 无伪造状态；CI 全绿。

### PR-04 — 搜索·画面描述匹配（分支 `feat/semantic-shot-search`，迁移 `0007_semantic_search`）— Gate A 已实现，Gate B/C 进行中
- 详见 `docs/SEMANTIC_SEARCH.md`。**Gate A（已实现）**：pgvector/pg_trgm 启用、`shot_search_document` 表、`EmbeddingProvider` 抽象 + FakeEmbedding + 本地 embedder 微服务（profile `embedding`，e5-small/384）、检索文档构建器、`search` 队列索引器 + AI/审核触发 + sweeper/回填。
- **Gate B/C（进行中）**：Query Parser、Hybrid 召回/重排/稳定排序、规则派生匹配理由、`POST /api/search/shots`、`POST /api/match/description`、`GET /api/search/suggestions`、`GET /api/search/index/status`、UI 参考图 04、性能 ≤3s 首屏。
- 退出标准：向量召回与重排可用、返回匹配度与理由；性能符合 PRD 8.1（局域网首屏 ≤3s）；CI 全绿。

### PR-05 — 脚本匹配·剪辑清单（分支 `feat/script-shot-matching`，迁移 `0008_script_matching`，新增 `export-worker`/队列 `export`）— 计划中
- 范围：粘贴脚本 + TXT/Markdown/Word 导入；段落拆分；画面需求/产品/动作/场景/卖点提取；每段候选镜头 + 匹配度 + 推荐理由；时长适配；同镜头去重 + 相邻差异化；风险过滤；无素材提示 + 补拍建议；人工选择 + 入点/出点；剪辑清单（CSV 起）；UI 参考图 03 完整。
- 退出标准：脚本→剪辑清单闭环可用、入/出点与时长正确；CI 全绿。

### PR-06 — 项目·收藏·导出闭环 — 计划中（已拆分为 PR-06A / PR-06B）
> 编号修正：真实迁移链已用到 `0009_script_matching_selection`（PR-05 Gate B），故 PR-06 迁移顺延为
> **`0010_projects_collections`**（早期本表误标 `0009`）。整体范围过大，拆分为两个独立分支/PR：

- **PR-06A — 项目与静态镜头集合（分支 `feat/projects-collections-foundation`，迁移 `0010_projects_collections`）**
  - 范围：Project；Project↔Asset/Shot/Product 业务关联；静态 Shot Collection；`ScriptProject.project_id`（可空 SET NULL）；项目统计；后端 API；Fake 测试；真实本地素材 API 验收；后续 Gate C 项目/集合 UI。
  - **不含**：Saved Search、Favorite、动态 Collection、统一 Export Center、多格式导出、ZIP 打包、下载历史、Export/ScriptExport 项目关联、bundle_export、Project 删除（删除留待 PR-07）。
- **PR-06B — 保存搜索·收藏·导出中心（独立分支/PR，迁移顺延）**
  - 范围：Saved Search；Favorite；动态 Collection；统一 Export Center（只读聚合）；多格式导出（XLSX/JSON/Markdown）；ZIP 片段+清单打包；下载历史；Export/ScriptExport 项目关联；bundle export。
- 退出标准：项目/收藏/多格式导出可用、导出可追溯；CI 全绿。

### PR-07 — 用户·权限·后台管理（分支 `feat/auth-admin-audit`，迁移 `0011_auth_admin_audit`）— 计划中
- 范围：登录 + 密码哈希 + Session/JWT；用户/角色/权限矩阵（管理员/素材管理员/运营/剪辑/只读）；API/下载/审核/配置权限；登录日志 + 操作审计；任务中心；AI 配置/NAS 目录配置/标签管理/风险规则/系统设置。
- 退出标准：权限生效、审计有效、后台可配置；CI 全绿。

### PR-08 — NAS 生产部署与运维（分支 `feat/nas-production-operations`，新增 `beat`/scheduler）— 计划中
- 范围：真实 NAS 预检；多素材目录；定时增量扫描；任务优先级/失败重试/卡死恢复；磁盘/队列/AI 健康告警；PostgreSQL 备份 + 恢复脚本 + 配置备份；日志轮转/临时文件清理/派生清理/数据保留；Docker 自动重启 + NAS 开机自启；反向代理 + HTTPS/内网说明；运维手册。
- 退出标准：备份可恢复、NAS 重启可恢复、运维项可用且有文档；CI 全绿。

### PR-09 — 全量验收·正式交付（分支 `release/v1-hardening`）— 计划中
- 范围：全需求回归 + UI 对照验收；大规模素材/4K/中文路径/并发/百万镜头可扩展性；查询性能/索引/慢查询；安全扫描（依赖漏洞、路径穿越、权限绕过、下载安全）；备份恢复演练 + NAS 重启恢复；测试报告/验收报告/用户手册/管理员手册/运维手册/已知问题/升级说明；v1.0 发布准备。
- 退出标准：第 6 节"项目完成定义"20 条全部满足。

---

## 4. 迁移序列与队列演进速查（修订版，取代旧路线图同名表）

| 阶段 | 分支 | Alembic 迁移 | 新增 worker / 队列 | pgvector |
| --- | --- | --- | --- | --- |
| PR-01 | `feat/mvp-foundation` | `0001_initial` | worker(`default,scan`) | 否 |
| PR-02 | `feat/shot-processing` | `0002_shot_processing` | media-worker(`media`) | 否 |
| （封面/关键帧条/上传） | `feat/asset-cover-upload-shot-ui` | `0003_shot_keyframes` | — | 否 |
| Gate 0.5 | `fix/land-asset-poster-on-main` | `0004_asset_poster` | — | 否 |
| PR-03A | `feat/ai-analysis-foundation` | `0005_ai_analysis` | **ai-worker(`ai`)** | 否 |
| PR-03B | `feat/ai-review-product-library` | `0006_ai_review_products` | — | 否 |
| PR-04 | `feat/semantic-shot-search` | `0007_semantic_search` | **search-worker(`search`)** + 可选 embedder | **启用** |
| PR-05 | `feat/script-shot-matching` | `0008_script_matching` (+`0009_script_matching_selection` Gate B) | export-worker(`export`) | 已启用 |
| PR-06A | `feat/projects-collections-foundation` | `0010_projects_collections` | — | 已启用 |
| PR-06B | （独立分支，待定） | （顺延，如 `0011_export_center`） | — | 已启用 |
| PR-07 | `feat/auth-admin-audit` | `0012_auth_admin_audit` | — | 已启用 |
| PR-08 | `feat/nas-production-operations` | `0013_ops_retention`（如需） | **beat/scheduler** | 已启用 |
| PR-09 | `release/v1-hardening` | —（仅加固/索引优化迁移如需） | — | 已启用 |

> 所有迁移只增不毁、可正向与回退；每个 PR 从最新 main 开分支、可独立验收。

---

## 5. AI Provider 总原则（详见 `docs/AI_PROVIDER_PLAN.md`）

- 适配器模式：业务层只依赖 `AIProvider`；未配置时 `NotConfiguredProvider` 显式报错，绝不返回假数据。
- PR-03A 先跑 `scripts/probe_ai_provider.py`（17 项探测、脱敏），据 `ProviderCapabilities` 决定调用与降级。
- 不支持图片 → 仅文本降级 + 视觉镜头标"待人工确认"，**绝不伪造视觉成功**；不支持 Embedding → 不影响 PR-03，PR-04 用独立 `EMBEDDING_*` Provider。
- 真实 API Key 仅放 `.env`，不入代码/前端/日志/Git。

---

## 6. 项目完成定义（全部满足才算"开发完成"）

1. PRODUCT_REQUIREMENTS 必须功能均有真实实现；
2. 所有数据库迁移可正向与回退；
3. 所有页面使用真实 API（不 Mock 伪造完成状态）；
4. 4 张参考图对应模块均已实现；
5. 原始 NAS 素材始终只读；
6. AI 结果可审核；
7. 人工结果不会被 AI 覆盖；
8. 搜索可返回匹配度与理由；
9. 脚本可生成剪辑清单；
10. 镜头可预览与下载；
11. 权限生效；
12. 审计日志有效；
13. 任务失败可重试；
14. 备份可恢复；
15. Docker Compose 可启动；
16. NAS 重启后可恢复；
17. 全部 CI 通过；
18. 有真实 E2E；
19. 有测试报告；
20. 有部署/使用/管理/运维文档。

---

## 7. 与既有文档关系

- `docs/PR_ROADMAP.md`：早期 MVP（PR-01~05）路线，保留作追溯；其迁移命名（`0003_ai_review/0004_pgvector/0005_script_matching`）**以本文修订为准**。
- 本文是全量交付路线（PR-03A~PR-09），覆盖并扩展 MVP 范围到正式发布。
