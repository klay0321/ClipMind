# CLAUDE.md — ClipMind 项目工作约定

本文件供 Claude Code 在本仓库工作时遵循。**最高事实来源是 `docs/PRODUCT_REQUIREMENTS.md`**，本文件是其工程化约定。

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
- 异步任务：Redis + **Celery**（broker/result backend 用 Redis）
- 视频处理：FFmpeg / FFprobe（PySceneDetect 等场景检测在 PR-02 引入）
- 部署：Docker + Docker Compose，后续部署到公司 NAS

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
docker compose ps           # 查看 6 个服务健康状态
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

- 后端：`pytest`（apps/api、services/worker）
- 前端：`npm run lint && npm run typecheck && npm test`
- 集成：`docker compose config` 校验；`docker compose up` 后端到端扫描合成夹具

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

- PR-01 `feat/mvp-foundation`：基础架构 + 只读素材索引（**当前阶段**）
- PR-02 `feat/shot-processing`：拆镜头 + 派生文件
- PR-03 `feat/ai-shot-analysis`：AI 理解 + 人工审核
- PR-04 `feat/shot-search`：搜索 + 画面描述匹配
- PR-05 `feat/script-shot-matching`：脚本匹配 + 剪辑清单

详见 `docs/PR_ROADMAP.md`。

## 12. 当前阶段范围（PR-01）

实现：Monorepo 骨架、Docker Compose（6 服务）、PostgreSQL、Redis、Celery worker（仅扫描）、只读源目录挂载、目录递归扫描、FFprobe 基础信息、分层变化检测/幂等/缺失检测、素材数据库、素材统一管理页面、CI、测试、文档。

不实现（仅预留接缝）：拆镜头、关键帧、缩略图、代理视频、AI 标签、搜索、画面/脚本匹配、剪辑清单、鉴权、pgvector 向量、scheduler/额外 worker。

## 13. 每次开发后的检查项

- [ ] 当前在正确分支（非 main）
- [ ] 未提交视频、密钥、NAS 凭据
- [ ] 数据库变更走 Alembic 迁移
- [ ] 源目录访问只读、经白名单校验
- [ ] 后端 `pytest` 通过、`ruff` 干净
- [ ] 前端 `lint` + `typecheck` + 测试通过
- [ ] `docker compose config` 有效
- [ ] 未实现功能在前端不显示假状态
- [ ] 给出验证命令与结果，不只说"已完成"
