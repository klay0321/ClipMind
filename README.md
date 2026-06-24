# ClipMind

> AI 视频素材管理与智能匹配系统 · AI Video Asset Management & Shot Matching Tool

ClipMind 把 NAS 中分散、难以检索的原始视频，转换为**结构化、可搜索、可匹配、可审核、可下载**的镜头资产库：只读索引素材、自动拆镜头与派生文件、调用外部 AI 理解打标、自然语言检索、画面/脚本匹配、生成剪辑清单。

**ClipMind 不做**生成式视频（文生视频、图生视频、数字人、声音克隆、视频复刻、自动成片）。"生成关键帧/缩略图/代理视频/片段"指用 FFmpeg 提取/裁剪/转码**派生文件**。

完整需求见 [docs/PRODUCT_REQUIREMENTS.md](docs/PRODUCT_REQUIREMENTS.md)。

---

## 当前进度：PR-02（拆镜头 + 派生文件）

已合并 PR-01（基础架构 + 只读素材索引）。PR-02 交付：
- 可替换 `ShotDetector` 拆镜头（PySceneDetect 主 + 固定切分兜底）
- FFmpeg 派生：主关键帧 / 缩略图 / 代理视频；按时间码导出可下载片段
- `Shot` / `MediaProcessingRun` / `Export` 三表（Alembic `0002`，以 DB 为事实来源）
- 专用 `media-worker`（media 队列，默认并发 1）；Docker Compose 升至 7 服务
- 镜头库前端：网格 + 详情 + 代理播放（HTTP Range）+ 导出下载
- 重新分析采用原子代次替换（旧镜头在新分析完整成功前持续可用）

详见 [docs/SHOT_PROCESSING.md](docs/SHOT_PROCESSING.md)。

PR-02 **不含**：任何 AI 调用 / 画面描述 / 标签 / 产品识别 / 风险 / 人工审核、搜索、脚本匹配、剪辑清单、鉴权（均在后续 PR，见 [docs/PR_ROADMAP.md](docs/PR_ROADMAP.md)）。界面不伪造 AI 状态。

---

## 架构

```
浏览器 ──同源 /api──> Next.js(web) ──代理──> FastAPI(api) ──> PostgreSQL
                                              │                      ▲ 派生路径/状态
                                              └─入队─> Redis ──┬─> worker（scan）──> FFprobe ──> 只读源(/app/source:ro)
                                                               └─> media-worker（拆镜头/派生/导出）──> FFmpeg ──> /app/data(rw)
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
