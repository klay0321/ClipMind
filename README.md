# ClipMind

> AI 视频素材管理与智能匹配系统 · AI Video Asset Management & Shot Matching Tool

ClipMind 把 NAS 中分散、难以检索的原始视频，转换为**结构化、可搜索、可匹配、可审核、可下载**的镜头资产库：只读索引素材、自动拆镜头与派生文件、调用外部 AI 理解打标、自然语言检索、画面/脚本匹配、生成剪辑清单。

**ClipMind 不做**生成式视频（文生视频、图生视频、数字人、声音克隆、视频复刻、自动成片）。"生成关键帧/缩略图/代理视频/片段"指用 FFmpeg 提取/裁剪/转码**派生文件**。

完整需求见 [docs/PRODUCT_REQUIREMENTS.md](docs/PRODUCT_REQUIREMENTS.md)。

---

## 当前进度：PR-01（基础架构 + 只读素材索引）

PR-01 交付：
- Monorepo 骨架 + Docker Compose（6 服务一键启动）
- 只读源目录挂载、目录递归扫描、FFprobe 基础信息索引
- 分层变化检测、幂等重扫、缺失文件标记（以数据库为事实来源）
- 素材统一管理页面（仅展示 PR-01 真实数据，不伪造后续状态）

PR-01 **不含**：拆镜头、关键帧、缩略图、代理视频、AI 标签、搜索、脚本匹配、剪辑清单、鉴权（均在后续 PR，见 [docs/PR_ROADMAP.md](docs/PR_ROADMAP.md)）。

---

## 架构

```
浏览器 ──同源 /api──> Next.js(web) ──代理──> FastAPI(api) ──> PostgreSQL
                                              │
                                              └─入队─> Redis ──> Celery worker ──> FFprobe ──> 只读源目录(/app/source:ro)
```

- 前端：Next.js + React + TS + Tailwind + TanStack Query
- 后端：FastAPI + Pydantic + SQLAlchemy(async) + Alembic
- 数据库：PostgreSQL（pgvector 预留至 PR-04）
- 异步：Redis + Celery
- 视频：FFmpeg / FFprobe

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 快速开始（本地开发）

前置：Docker + Docker Compose。

```bash
# 1. 准备环境变量
cp .env.example .env

# 2. 把若干测试视频放入只读源目录（sample_media 模拟 NAS，视频不会被提交）
#    例如 sample_media/demo.mp4

# 3. 启动全栈
docker compose up -d
docker compose ps          # 等待 6 个服务 healthy

# 4. 打开前端
#    http://localhost:3000

# 5. 在页面创建素材目录（mount_path = /app/source）并点击“扫描”
```

源目录在容器内为**只读**，ClipMind 绝不修改/删除/移动源视频。

更多见 [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md)。NAS 部署见 [docs/NAS_DEPLOYMENT_CHECKLIST.md](docs/NAS_DEPLOYMENT_CHECKLIST.md)。

---

## 目录结构

```
compose.yml          根 Docker Compose
apps/web/            Next.js 前端
apps/api/            FastAPI 后端 + Alembic 迁移
services/worker/     Celery worker（扫描）
packages/shared/     共享模型 / ffprobe / 路径安全 / AI 接口
infra/               Dockerfile
docs/                文档
scripts/             辅助脚本
sample_media/        本地只读源目录（不提交视频）
```

---

## 安全约束（最高优先级）

- 原始素材目录只读挂载，绝不修改/删除/移动/改名/覆盖源视频，不提供源删除 API
- 路径白名单 + `realpath` 包含检查 + 软链逃逸防护，防止目录穿越
- 不提交视频、密钥、NAS 凭据；`.env` 已被 git 忽略

---

## 开发与测试

见 [CLAUDE.md](CLAUDE.md) 的命令清单与检查项。
