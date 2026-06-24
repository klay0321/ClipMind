# ClipMind 总体架构

> 本文档描述 ClipMind 的总体架构、目录结构、技术选型、数据模型、API 列表、扫描状态机与异步任务设计。
> 文档以「设计事实」为唯一事实来源，仅描述 PR-01（基础架构 + 只读素材索引）已落地的能力，并为 PR-02~05 标注预留的模块边界。
> 凡标注「预留 / 推迟 / 骨架」的内容，均表示当前 PR 尚未实现，请勿误读为已完成能力。

---

## 1. 产品定位与边界

ClipMind 是面向公司 NAS 部署的「AI 视频素材管理与智能匹配系统」，核心能力是：

- **只读索引**视频素材（不修改源文件）
- 用 **FFmpeg** 拆镜头与生成派生文件（关键帧 / 缩略图 / 代理视频 / 片段裁剪）
- 调用**外部 AI** 对镜头进行理解打标
- **自然语言检索**素材
- **画面 / 脚本匹配**
- 导出**剪辑清单**（CSV）

### 1.1 明确不做（必须强调的排除项）

ClipMind **不包含任何生成式视频能力**，明确排除：

- 文生视频、图生视频
- 数字人、声音克隆
- 视频复刻、替换人物 / 产品
- 自动成片

> 文档中出现的「生成关键帧 / 缩略图 / 代理视频 / 片段」一律指**用 FFmpeg 从既有源视频提取、裁剪、转码出派生文件**，是确定性的媒体处理，**不是生成式 AI 能力**。

### 1.2 MVP 分阶段交付（5 个 PR）

| PR | 分支 | 范围 | 状态 |
| --- | --- | --- | --- |
| PR-01 | `feat/mvp-foundation` | 基础架构 + 只读素材索引 | **当前** |
| PR-02 | `feat/shot-processing` | 拆镜头 + 派生文件（关键帧 / 缩略图 / 代理 / 片段裁剪下载，PySceneDetect） | 预留 |
| PR-03 | `feat/ai-shot-analysis` | AI 理解 + 人工审核（小米 MiMo，AIProvider 抽象，先能力探测） | 预留 |
| PR-04 | `feat/shot-search` | 搜索 + 画面描述匹配（pgvector 在此 PR 用独立迁移启用） | 预留 |
| PR-05 | `feat/script-shot-matching` | 脚本匹配 + 剪辑清单 CSV 导出 | 预留 |

---

## 2. 架构总览

### 2.1 请求与数据流

```
                            浏览器 (用户)
                               │  HTTPS / HTTP（默认仅 127.0.0.1）
                               ▼
                    ┌────────────────────────┐
                    │  web (Next.js next start) │
                    │  服务端 rewrites：          │
                    │  /api/*  ──►  api:8000      │   ← 同源代理，浏览器只看到一个源
                    └───────────┬────────────┘
                                │  容器内网络
                                ▼
                    ┌────────────────────────┐
                    │  api (FastAPI / uvicorn)  │
                    │  - REST 接口               │
                    │  - 事务内建 ScanRun         │
                    │  - 入队 Celery 任务         │
                    └─────┬──────────────┬─────┘
            SQLAlchemy    │              │  Celery broker
            (async)       ▼              ▼
                ┌──────────────┐   ┌──────────────┐
                │  postgres     │   │  redis        │
                │ (pgvector/    │◄──┤ (broker +     │
                │  pg16，事实    │   │  backend)     │
                │  来源)         │   └──────┬───────┘
                └──────▲───────┘          │ 取任务
                       │ DB 写回            ▼
                       │           ┌──────────────────────────┐
                       └───────────┤  worker (Celery)          │
                                   │  -Q default,scan          │
                                   │  - advisory lock          │
                                   │  - 分层变化检测             │
                                   │  - ffprobe 读取元数据       │
                                   └───────────┬──────────────┘
                                               │ open(rb) 只读
                                               ▼
                                   ┌──────────────────────────┐
                                   │  只读源目录                 │
                                   │  ./sample_media → /app/source:ro │
                                   │  （生产：/nas/source:ro）   │
                                   └──────────────────────────┘
```

### 2.2 关键约束

- **浏览器只看到 web 一个源**：web 通过服务端 rewrites 把 `/api/*` 代理到 `api:8000`，避免跨域，也避免把 api 直接暴露给浏览器。
- **PostgreSQL 是唯一事实来源**：扫描进度、资产状态、扫描运行记录都以 DB 为准，worker 与 api 不靠内存状态通信。
- **源目录只读**：worker 仅以 `open(rb)` 读取源视频，挂载使用 `:ro`，绝不修改源。
- **默认仅绑 127.0.0.1**：api / web 默认本机访问，无鉴权时不对外公开。

---

## 3. Monorepo 目录结构与各包职责

```
clipmind/
├── compose.yml                  # 根：Docker Compose（6 个服务）
├── .env.example                 # 仅提交示例；真实 .env 被 git 忽略
├── apps/
│   ├── web/                     # 前端（Next.js + React + TS + Tailwind + TanStack Query）
│   └── api/                     # 后端 API（FastAPI + Pydantic + SQLAlchemy async + Alembic）
├── services/
│   └── worker/                  # 包名 clipmind_worker：Celery 应用与任务
├── packages/
│   └── shared/                  # 包名 clipmind_shared：跨进程共享（模型 / 枚举 / 配置 / AI 接口骨架）
├── infra/
│   ├── api.Dockerfile
│   ├── worker.Dockerfile
│   └── web.Dockerfile
├── docs/                        # 文档（含本文件）
├── scripts/                     # 运维 / 开发脚本
└── sample_media/                # 只读源目录（开发用）；禁止提交视频
```

### 3.1 各包职责

| 包 / 目录 | 包名 | 职责 | 关键边界 |
| --- | --- | --- | --- |
| `packages/shared` | `clipmind_shared` | 共享层：ORM 模型、枚举、配置、路径白名单校验、`ai/provider.py` 接口骨架 | api 与 worker 都依赖它，保证模型与枚举单一定义 |
| `services/worker` | `clipmind_worker` | Celery 应用 `celery_app`、扫描任务、advisory lock、变化检测、ffprobe | 不直接被 web 调用；只消费队列、读源目录、写 DB |
| `apps/api` | — | FastAPI 应用：REST 接口、健康检查、事务内建 ScanRun、入队 Celery | 不直接读源视频内容（扫描交给 worker） |
| `apps/web` | — | Next.js 前端 + 服务端 `/api` 代理 | 唯一对浏览器暴露的源 |

> **依赖方向**：`apps/api` 与 `services/worker` 都依赖 `packages/shared`；`apps/web` 仅通过 HTTP 调用 api。`shared` 不反向依赖 api / worker。

---

## 4. 技术选型与理由

### 4.1 技术栈一览

| 层 | 选型 |
| --- | --- |
| 前端 | Next.js + React + TypeScript + Tailwind CSS + TanStack Query |
| 后端 | FastAPI + Pydantic + SQLAlchemy(async) + Alembic |
| 数据库 | PostgreSQL（`pgvector/pgvector:pg16` 镜像；pgvector 扩展**推迟到 PR-04** 才启用） |
| 异步 | Redis + Celery |
| 视频 | FFmpeg / FFprobe |
| 部署 | Docker Compose |

### 4.2 选型理由

- **Next.js 服务端 rewrites**：让浏览器只面对单一同源，免 CORS、免把 api 直接暴露；前端可平滑接入 SSR / 路由能力。
- **TanStack Query**：扫描进度、资产列表都是服务端状态，需要轮询、缓存、失效；TanStack Query 天然适配。
- **FastAPI + Pydantic**：类型驱动、请求 / 响应自动校验、OpenAPI 文档自动生成，适合契约清晰的 REST。
- **SQLAlchemy(async) + Alembic**：异步 IO 配合 FastAPI；Alembic 提供可控、可回溯、**禁止删库重建**的迁移演进（PR-04 用独立迁移启用 pgvector）。
- **PostgreSQL**：作为唯一事实来源；选 `pgvector/pgvector:pg16` 镜像是为后续 PR-04 的向量检索预留底座，但 PR-01 **不创建 pgvector 扩展**，避免提前耦合。

### 4.3 为什么选 Celery（队列方案选型理由）

任务子系统是 ClipMind 的骨架（扫描、拆镜头、AI、导出都是任务），队列选型直接对应 PRD 的任务子系统需求。选择 **Celery** 的核心理由：

1. **原生队列优先级**：`default / scan / media / ai / export` 可按队列拆分与优先级调度，匹配「不同任务重要度不同、资源消耗不同」的现实。
2. **原生 beat 定时调度**：支持周期性扫描 / 巡检（PR 后续按需启用 beat），无需额外造轮子。
3. **原生重试机制**：任务失败可按策略重试，扫描 / 媒体处理这类长任务尤其需要。
4. **`acks_late` 断点恢复**：任务在完成后才确认（late-ack），worker 崩溃时任务可被重新投递，配合「DB 为事实来源 + advisory lock」实现断点恢复，避免任务丢失或重复执行。

> 结论：Celery 的优先级、beat、重试、`acks_late` 四项原生能力共同构成了最贴合 PRD 任务子系统的方案，因此作为异步骨架的首选。

---

## 5. Docker Compose 服务拓扑

Compose 共 **6 个服务**（仅启用 PR-01 必需的部分，不启动 scheduler/beat 与 ai/media/export worker）：

| 服务 | 镜像 / 命令 | 职责 | 关键配置 |
| --- | --- | --- | --- |
| `postgres` | `pgvector/pgvector:pg16` | 数据库（事实来源） | 命名卷 `pgdata` 持久化 |
| `redis` | `redis:7-alpine` | Celery broker + result backend | — |
| `migrate` | 一次性 `alembic upgrade head` | 启动时执行迁移后退出 | 不创建 pgvector 扩展 |
| `api` | `uvicorn` | FastAPI 服务 | 绑 `127.0.0.1`；healthcheck = `/health/live` |
| `worker` | `celery -A clipmind_worker.celery_app worker -Q default,scan` | 消费扫描任务 | 仅监听 `default,scan` |
| `web` | `next start` | 前端；服务端 rewrites 把 `/api` 代理到 `api:8000` | 浏览器唯一入口 |

### 5.1 挂载与卷

- `./sample_media:/app/source:ro` —— 开发期只读源目录。
- 命名卷 `clipmind-data:/app/data` —— 派生文件 / 工作数据（供后续 PR 使用）。
- 命名卷 `pgdata` —— PostgreSQL 数据持久化。

### 5.2 未启用项（明确说明）

- 不启动 `scheduler / beat`。
- 不启动 `ai / media / export` worker。
- 不创建 pgvector 扩展。

> 这些都是为后续 PR 预留的边界，当前 Compose 文件不包含其启用配置。

---

## 6. 数据模型（PR-01，Alembic `0001_initial`）

> 约束：**禁止删库重建**，模型演进只能通过新增 Alembic 迁移。PR-01 迁移**不建 pgvector 扩展**。
> 所有时间字段统一使用 **UTC + timezone-aware**。

### 6.1 三张表

#### SourceDirectory（源目录）

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `name` | 显示名 |
| `mount_path` | **容器逻辑路径**，必须在白名单根（`ALLOWED_SOURCE_ROOTS`）之下 |
| `enabled` | 是否启用 |
| `recursive` | 是否递归扫描 |
| `include_extensions` | JSONB，包含扩展名白名单 |
| `exclude_patterns` | JSONB，排除模式 |
| `read_only` | **强制 `true`** |
| `scan_status` | `ScanStatus` 枚举 |
| `last_scanned_at` | 最近扫描完成时间（UTC） |
| `created_at` / `updated_at` | UTC |

#### Asset（资产 / 视频文件）

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `source_directory_id` | 外键 → SourceDirectory |
| `relative_path` | 相对源目录的原始路径 |
| `normalized_relative_path` | **POSIX + NFC 归一化**，用于唯一约束 |
| `filename` / `extension` | 文件名 / 扩展名 |
| `file_size` | 字节 |
| `modified_at` | 文件 mtime（UTC） |
| `quick_hash` | 快速哈希（见 §8.2） |
| `full_hash` | **PR-02 预留**（当前不计算，仅留列） |
| `duration` / `width` / `height` / `fps` | FFprobe 元数据 |
| `video_codec` / `audio_codec` | 编解码 |
| `orientation` / `has_audio` | 方向 / 是否有音轨 |
| `status` | `AssetStatus` 枚举 |
| `error_message` | 错误信息 |
| `last_seen_scan_id` | 最近一次「见到」它的 ScanRun（缺失检测用） |
| `metadata_version` | 元数据版本 |
| `first_seen_at` / `last_seen_at` | UTC |
| `created_at` / `updated_at` | UTC |

**唯一约束**：`(source_directory_id, normalized_relative_path)`。

#### ScanRun（扫描运行记录）

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `source_directory_id` | 外键 |
| `status` | `ScanRunStatus` 枚举 |
| `celery_task_id` | 入队后写回 |
| `queued_at` / `started_at` / `heartbeat_at` / `finished_at` | 生命周期时间戳（UTC） |
| `worker_name` | 执行 worker |
| `files_discovered` / `files_new` / `files_modified` / `files_missing` / `files_errored` | 统计计数 |
| `error_message` | 错误信息 |

**部分唯一索引**：`(source_directory_id) WHERE status IN ('queued','running')`
—— 保证同一源目录同一时刻最多只有一个进行中的扫描。

### 6.2 枚举

| 枚举 | 取值 |
| --- | --- |
| `AssetStatus` | `discovered` / `indexed` / `error` / `source_missing` + **预留** `pending` / `processing` / `shot_split` / `ai_analyzing` / `pending_review` / `searchable` / `paused` / `archived` |
| `ScanStatus` | `never_scanned` / `queued` / `scanning` / `completed` / `failed` / `cancelled` |
| `ScanRunStatus` | `queued` / `running` / `completed` / `failed` / `cancelled` |

> `AssetStatus` 中的预留取值是为 PR-02~05（拆镜头 / AI 分析 / 审核 / 检索）预留的状态位，PR-01 不会写入这些值。

---

## 7. API 列表（PR-01）

### 7.1 健康检查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health/live` | 存活探针（api healthcheck 使用） |
| GET | `/health/ready` | 就绪探针（依赖 DB / Redis 可用性） |

### 7.2 系统

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/system/status` | 系统整体状态 |

### 7.3 源目录

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/source-directories` | 列表 |
| POST | `/api/source-directories` | 新建（`mount_path` 须通过白名单校验） |
| GET | `/api/source-directories/{id}` | 详情 |
| PUT | `/api/source-directories/{id}` | 更新 |
| POST | `/api/source-directories/{id}/scan` | 触发扫描（事务内建 ScanRun + 入队） |
| GET | `/api/source-directories/{id}/status` | 扫描状态 |

### 7.4 资产

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/assets` | 列表（分页 + 文件名搜索 + status 筛选） |
| GET | `/api/assets/{id}` | 详情 |
| POST | `/api/assets/{id}/rescan` | 重新扫描单个资产 |

---

## 8. 扫描状态机与流程（以 DB 为事实来源）

### 8.1 触发与状态流转

```
POST /api/source-directories/{id}/scan
        │
        ▼  （单事务）
  建 ScanRun(status=queued)  +  目录 scan_status=queued
        │
        ▼  事务提交
  入队 Celery 任务（队列 scan）
        │
        ▼
  写回 ScanRun.celery_task_id
        │
        ▼  worker 取任务
  获取 PostgreSQL 会话级 advisory lock（绑定单连接，跨多次 commit）
        │
        ▼  ScanRun running / 目录 scanning（周期更新 heartbeat_at）
  分层变化检测 → 缺失检测
        │
        ▼  完整成功
  ScanRun completed / 目录 completed / last_scanned_at 更新
```

状态映射：

- `ScanStatus`（目录）：`never_scanned → queued → scanning → completed | failed | cancelled`
- `ScanRunStatus`（运行）：`queued → running → completed | failed | cancelled`

> 部分唯一索引保证：同一目录处于 `queued / running` 时，不会再建出第二条进行中的 ScanRun。

### 8.2 分层变化检测

为避免每次都读文件内容、跑 ffprobe，采用分层策略：

1. **第一层（廉价）**：比对 `file_size + mtime`。
   - 未变 → 不读内容、不 probe，仅更新 `last_seen_scan_id` 与 `last_seen_at`。
2. **第二层（昂贵）**：新增或第一层判定有变化的文件才执行：
   - 计算 **`quick_hash = sha256(size + 头 64 KiB + 尾 64 KiB)`**
   - 执行 **FFprobe** 读取时长 / 分辨率 / 编解码等元数据。

> `full_hash`（全文件哈希）是 **PR-02 预留**，PR-01 不计算。

### 8.3 缺失检测

- 基于 `last_seen_scan_id`：本次扫描没有「见到」的资产即为候选缺失。
- **仅在整次扫描完整成功后**，用 SQL **批量**把这些资产置为 `source_missing`。
- **失败 / 取消的扫描不做缺失标记**，避免因中断误判文件丢失。

### 8.4 advisory lock 设计

- 使用 PostgreSQL **会话级 advisory lock**，按 `source_directory_id` 加锁。
- 锁**绑定到单个数据库连接**，并在该连接上跨多次 `commit` 持有，确保扫描期间互斥，且即便分多个事务提交也不会丢锁。
- 与 `acks_late` 配合：worker 崩溃后任务可重投，advisory lock 随连接释放，新 worker 可安全重入。

---

## 9. 异步任务与队列

### 9.1 队列规划

| 队列 | 状态 | 用途 |
| --- | --- | --- |
| `default` | **已启用** | 通用任务 |
| `scan` | **已启用** | 扫描任务 |
| `media` | 预留 | 拆镜头 / 派生文件（PR-02） |
| `ai` | 预留 | AI 理解 / 打标（PR-03） |
| `export` | 预留 | 剪辑清单导出（PR-05） |

worker 当前启动命令：

```
celery -A clipmind_worker.celery_app worker -Q default,scan
```

### 9.2 当前不启用

- **beat / scheduler**：定时调度为后续预留，当前不启动。
- **media / ai / export worker**：对应队列与 worker 进程为后续 PR 预留。

---

## 10. 源目录抽象：本地目录与未来 NAS 的统一模型

ClipMind 用「**白名单根 + 容器逻辑路径**」统一抽象本地开发目录与未来的 NAS：

- **白名单根**：`ALLOWED_SOURCE_ROOTS=/app/source`。所有源目录的 `mount_path` 必须落在白名单根之下。
- **容器逻辑路径**：数据库里存的是**容器内的逻辑路径**（如 `/app/source/...`），与宿主机的物理挂载点解耦。

| 环境 | 宿主 / 存储 | 容器内逻辑路径 | 挂载方式 |
| --- | --- | --- | --- |
| 开发 | `./sample_media` | `/app/source` | `:ro` |
| 生产（规划） | `/nas/source` | `/app/source`（同一逻辑根） | `:ro` |

> 说明：生产 NAS 部署目前**仅为规划**，尚未实际落地；本文不宣称已完成真实 NAS 部署。统一抽象的好处是：业务代码只认 `/app/source` 这一逻辑根，开发与生产仅在 Compose 挂载层切换物理来源，代码无需改动。

### 10.1 安全约束（最高优先级）

- 源目录一律 **只读挂载（`:ro`）**。
- **绝不**修改 / 删除 / 移动 / 改名 / 覆盖源视频；**无源删除 API**。
- 路径校验：**白名单根 + `os.path.realpath` 包含检查 + 软链逃逸防护**，防止越权访问白名单外路径。
- 源文件只 `open(rb)` 读取。
- 不提交视频与密钥；`.env` 被 git 忽略，仅提交 `.env.example`。
- api / web 默认仅绑 `127.0.0.1`，无鉴权时不对外公开。

---

## 11. 为 PR-02~05 预留的模块边界

为避免后续 PR 大改结构，PR-01 已预先划好边界：

| 预留项 | 位置 / 形式 | 服务于 |
| --- | --- | --- |
| `media` 空包 | 媒体处理模块占位（拆镜头 / 派生文件） | PR-02 |
| `ai` 空包 | AI 模块占位 | PR-03 |
| `full_hash` 列 | Asset 表已留列，PR-01 不计算 | PR-02 |
| pgvector 推迟启用 | 用 `pgvector/pg16` 镜像但 PR-01 不建扩展 | PR-04（独立迁移启用） |
| `AIProvider` 接口骨架 | `clipmind_shared/ai/provider.py`（见 §12） | PR-03 |
| beat 调度 | Compose / Celery 预留，当前不启动 | 后续按需 |
| 任务中心 | `media / ai / export` 队列与 worker 预留 | PR-02 / PR-03 / PR-05 |
| `AssetStatus` 预留状态 | 枚举已含 `processing / shot_split / ai_analyzing / pending_review / searchable` 等 | PR-02~04 |

---

## 12. AIProvider 接口骨架（PR-01 仅骨架，PR-03 才真实调用）

> PR-01 **只提供文档 + 接口骨架** `clipmind_shared/ai/provider.py`，**不做任何真实模型调用**。真实的能力探测与调用在 PR-03（小米 MiMo）执行。

### 12.1 接口方法

`AIProvider` 接口包含：

- `health_check`
- `analyze_frames`
- `analyze_video_clip`
- `parse_search_query`
- `parse_script`
- `generate_embedding`
- `rerank_candidates`

### 12.2 能力声明 `ProviderCapabilities`

- `supports_images`
- `supports_video`
- `supports_structured_output`
- `supports_embeddings`
- `max_images_per_call`
- `context_window`

### 12.3 PR-03 能力探测项（仅文档约定）

连通性 / 鉴权 / OpenAI 兼容 / 文本 / 严格 JSON / JSON Schema / 单图 / 多图 / Base64 图 / URL 图 / Embedding / 上下文 / 并发 / 超时 / 限流 / 错误码 / 数据是否被保留。

### 12.4 降级策略

- **不支持图片** → 仅用文本角色；视觉镜头**降级为待人工确认**，**绝不伪造视觉成功**。
- **不支持 Embedding** → 使用独立的 `EMBEDDING_PROVIDER`。

### 12.5 预留环境键

`AI_*` 与 `EMBEDDING_*` 系列环境变量为 PR-03 预留。

---

## 13. 开发环境基线

- 开发机：Windows 11；所有服务跑在 **Linux 容器**内。
- 工具版本：git 2.53、Docker 29.4.3、Compose v5.1.3、Node 24、Python 3.13.2、FFmpeg / FFprobe 8.1.1。

> 跨平台一致性由容器保证：开发者在 Windows 上编辑，运行时统一为 Linux 容器，避免路径 / 编解码差异。

---

## 14. 设计原则小结

1. **DB 为唯一事实来源**：状态、进度、缺失判定都以 PostgreSQL 为准。
2. **源只读、不可变**：只读挂载 + 白名单 + 软链防护 + 无删除 API。
3. **任务子系统优先**：Celery 的优先级 / beat / 重试 / `acks_late` 是骨架基石。
4. **逻辑路径解耦物理存储**：开发 `sample_media` 与未来 NAS 共用 `/app/source` 逻辑根。
5. **边界先行**：PR-01 预留空包、列、接口与队列，后续 PR 增量启用，禁止删库重建。
6. **不做生成式视频**：所有「生成」均为 FFmpeg 派生，明确排除文生 / 图生 / 数字人 / 复刻 / 自动成片。
