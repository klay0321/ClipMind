# CLAUDE.md — ClipMind 项目工作约定

本文件供 Claude Code 在本仓库工作时遵循。**最高事实来源是 `docs/PRODUCT_REQUIREMENTS.md`**，本文件是其工程化约定。

## 0. 协作与文档约定

- **默认全程使用中文汇报**（过程说明、计划、状态、总结都用中文；代码与英文专有名词保留英文）。
- **UI 参考图位置**：`docs/ui-reference/`（`01-shot-splitting-and-tagging.jpg` 拆镜头打标、`02-asset-management.jpg` 素材管理、`03-script-matching.jpg` 脚本匹配、`04-description-matching.jpg` 画面匹配），仅作产品/交互设计参考，**不作为运行时前端资源**。
- 不实现的功能在前端不显示假状态、不伪造 AI 结果。
- 不把本机绝对路径、个人环境或真实凭据写入文档与代码。

## 1. 产品定位

ClipMind 是面向公司 NAS 部署的 **AI 视频素材管理与智能匹配系统**：只读索引视频素材、FFmpeg 拆镜头与派生文件、外部 AI 理解打标、自然语言检索、画面/脚本匹配、剪辑清单导出。它把 NAS 中无法理解、难检索的原始视频，转换为结构化、可搜索、可匹配、可审核、可下载的镜头资产。

## 2. 明确排除（绝不实现）

ClipMind **不做**任何生成式视频能力：
- 文生视频、图生视频、数字人、声音克隆、视频复刻、替换视频中的人物/产品、自动生成完整成片。

需求中"生成关键帧/缩略图/代理视频/可剪辑片段"一律指 **用 FFmpeg 从原始视频提取、裁剪或转码派生文件**，不是生成式能力。不得把其他视频生成项目的代码或概念引入本仓库。

## 3. 技术架构

- 前端：Next.js + React + TypeScript + Tailwind CSS + TanStack Query
- 后端：FastAPI + Pydantic + SQLAlchemy(async) + Alembic
- 数据库：PostgreSQL（pgvector 为语义检索预留，PR-04 启用；禁止用 SQLite 代替）
- 异步任务：Redis + **Celery**（broker/result backend 用 Redis）。worker 消费 `default,scan`；media-worker 消费 `media`（PR-02 拆镜头/派生/导出）
- 视频处理：FFmpeg / FFprobe；PySceneDetect（`opencv-python-headless` 后端）场景检测，PR-02 引入
- 部署：Docker + Docker Compose（PR-02 起 7 服务），后续部署到公司 NAS

## 4. 目录结构

```
compose.yml          项目根 Docker Compose（docker compose up -d 直接启动）
apps/web/            Next.js 前端
apps/api/            FastAPI 后端 + Alembic 迁移
services/worker/     Celery worker
packages/shared/     共享：SQLAlchemy 模型 / ffprobe / 路径安全 / AI Provider 接口
infra/               api/worker/web 三个 Dockerfile
docs/                需求、架构、路线、部署、AI 方案等文档
scripts/             辅助脚本（如 NAS 预检模板）
sample_media/        本地只读源目录（模拟 NAS，禁止提交视频）
```

## 5. 开发命令

```bash
# 启动全栈（项目根目录执行）
docker compose up -d
docker compose ps           # 查看 7 个服务健康状态（含 media-worker）
docker compose logs -f api  # 查看日志
docker compose down         # 停止

# 后端（apps/api、services/worker，容器内或本地虚拟环境）
alembic upgrade head        # 应用数据库迁移
pytest                      # 运行后端测试
ruff check .                # 静态检查

# 前端（apps/web）
npm run dev                 # 本地开发
npm run lint                # ESLint
npm run typecheck           # tsc --noEmit
npm test                    # 前端测试
```

## 6. 测试命令

- 后端：`pytest`（仓库根运行；DB/ffmpeg 测试需 `TEST_DATABASE_URL`（指向 pgvector/pg16）+ 本机 ffmpeg，否则自动跳过）
  - 并行：`pytest -n 4 --dist loadfile`（pytest-xdist；根 conftest 会给每个 worker 建独立测试库 `<db>_gwN`，互不 TRUNCATE）。串行共库跑多个 pytest 进程会互清数据，禁止。
  - rootdir 坑：**带路径参数**（如 `pytest apps/api/tests/xxx.py`）会让 `apps/api/pyproject.toml` 抢走 rootdir，根 conftest（建表/清库/per-worker 库）整个不加载，测试因残留数据假失败——必须加 `-c pytest.ini` 锚定仓库根。
- 前端：`cd apps/web && npm run lint && npm run typecheck && npm test && npm run build`
- 集成：`docker compose config` 校验；`docker compose up` 后端到端拆镜头合成夹具（不提交真实视频）

## 7. Git 分支规则

- **禁止直接在 `main` 修改代码**。
- 每个 PR 从最新 `main` 开新分支：PR-01 用 `feat/mvp-foundation`，后续见 `docs/PR_ROADMAP.md`。
- 开始任务前确认当前分支正确再动代码。
- 未经用户确认不 commit / push / 建 PR。

## 8. 原始素材只读规则（最高优先级安全约束）

- 原始素材目录只能**只读挂载**（Docker `:ro`）。
- **绝不**移动、改名、覆盖、删除源视频；**不提供**源文件删除 API。
- 删除操作只删系统索引和派生文件（`/app/data`），不碰源文件。
- 所有源目录访问必须经白名单根校验 + `realpath` 包含检查，防止路径穿越与软链逃逸。
- 源目录下只能以只读模式 `open(..., "rb")`，禁止任何写模式打开。

## 9. 禁止提交

- **禁止提交任何视频**（测试/业务素材都不行）。
- **禁止提交密钥 / 密码 / Cookie / Token / NAS 凭据**。`.env` 已被 git 忽略，仅提交 `.env.example`。
- 日志不得输出完整密钥。

## 10. 数据库迁移规则

- 一律使用 **Alembic 迁移**；**禁止删库重建**代替迁移。
- 每次模型变更生成新迁移并人工审查。
- 新增表/列用新迁移，不改动历史迁移。

## 11. PR 路线（完整 MVP v0.1 = PR-01..PR-05）

- PR-01 `feat/mvp-foundation`：基础架构 + 只读素材索引（已合并）
- PR-02 `feat/shot-processing`：拆镜头 + 派生文件（**当前阶段**）
- PR-03 `feat/ai-shot-analysis`：AI 理解 + 人工审核
- PR-04 `feat/shot-search`：搜索 + 画面描述匹配
- PR-05 `feat/script-shot-matching`：脚本匹配 + 剪辑清单

详见 `docs/PR_ROADMAP.md`。

## 12. 当前阶段范围（PR-02）

**实现**：可替换 `ShotDetector`（PySceneDetect 主 + 固定切分兜底）拆镜头；FFmpeg 派生关键帧/缩略图/代理视频；按时间码导出可下载片段（默认 reencode）；`Shot`/`MediaProcessingRun`/`Export` 三表与 `0002_shot_processing` 迁移；media-worker（专用 media 队列，默认并发 1）；镜头分析/镜头/导出 API 与安全文件服务（含 HTTP Range）；镜头库前端（网格 + 详情 + 代理播放 + 导出下载）；测试、CI、文档。详见 `docs/SHOT_PROCESSING.md`。

**不实现（仅预留/留待后续 PR）**：任何 AI 调用与打标、画面描述、产品/场景/动作识别、风险判断、人工审核、自然语言搜索、画面/脚本匹配、剪辑清单、鉴权、pgvector 向量、scheduler/ai/export worker。UI 不得伪造"AI 已打标/产品已识别/匹配度"等状态。

镜头分析以 PostgreSQL 为事实来源；重新分析用**原子代次替换**（旧镜头在新分析完整成功前持续可用）；同一素材同一时刻至多一个活动分析运行（部分唯一索引 + 素材级 advisory lock）。

## 13. 每次开发后的检查项

- [ ] 当前在正确分支（非 main）
- [ ] 未提交视频、密钥、NAS 凭据、运行时数据（`data/`、`.env`）
- [ ] 数据库变更走 Alembic 新迁移（不改历史迁移、不删库重建）
- [ ] 源目录访问只读、经白名单校验；派生文件只写 `/app/data` 且经路径包含校验
- [ ] 后端 `pytest` 通过（设 `TEST_DATABASE_URL` + ffmpeg）、`ruff` 干净
- [ ] 前端 `lint` + `typecheck` + 测试 + `build` 通过
- [ ] `docker compose config` 有效（新增 env 必须进 `.env.example`）
- [ ] 未实现功能在前端不显示假状态、不伪造 AI 结果
- [ ] 给出验证命令与结果，不只说"已完成"
