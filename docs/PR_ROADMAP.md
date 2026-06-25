# ClipMind PR 路线图

> 文档版本：V1.0
> 文档状态：开发执行稿
> 面向对象：研发、测试、代码评审人、项目负责人
> 唯一事实来源：本文件与 `docs/PRODUCT_REQUIREMENTS.md` 共同约束实现，二者冲突时以最新评审结论为准
> 适用范围：ClipMind MVP v0.1（PR-01 ~ PR-05）

---

## 0. 阅读前必须知道的事

ClipMind 是面向公司 NAS 部署的「AI 视频素材管理与智能匹配系统」，核心能力是：

- 只读索引 NAS 现有视频素材，不搬运、不改名、不删除、不覆盖源文件；
- 用 FFmpeg / FFprobe 拆镜头并提取/裁剪/转码派生文件（关键帧、缩略图、代理视频、可下载片段）；
- 通过外部 AI API（小米 MiMo）理解画面并打结构化标签，配合人工审核兜底；
- 支持自然语言检索与画面描述匹配；
- 支持脚本逐段匹配镜头并导出剪辑清单（CSV）。

### 0.1 明确不做（架构与文档中必须始终排除）

ClipMind **不包含**任何生成式视频能力，本路线图所有 PR 均不实现以下内容：

- 文生视频、图生视频；
- 数字人、声音克隆；
- 视频复刻、替换人物 / 产品；
- 自动成片（一键生成完整成片）。

> 重要澄清：文档中出现的「生成关键帧 / 缩略图 / 代理视频 / 片段」一律指**用 FFmpeg 提取、裁剪、转码派生文件**，不是任何生成式 AI 能力。请勿在任何 PR 描述、注释或界面文案中暗示生成式能力。

### 0.2 当前实现真实状态

- 本路线图描述的是**计划与拆分方式**，不代表已经完成。
- **未实现的能力不得在文档、README、界面或日志中宣称已完成。**
- **尚未进行任何真实 NAS 部署**；compose 中的 NAS 挂载为本地 `./sample_media` 演示挂载，正式 NAS 上线属于后续工作，本路线图不宣称已部署到真实 NAS。

---

## 1. PR 拆分总则（强制约束）

以下规则适用于 PR-01 ~ PR-05 的每一个 PR，评审时逐条核对：

1. **从最新 main 开新分支**：每个 PR 必须 `git checkout main && git pull` 后再 `git checkout -b <分支名>`，不得在上一个 feature 分支之上直接续写。
2. **可独立运行测试验收**：每个 PR 合并前必须能独立 `docker compose up` 跑通自身范围内的验收，并能独立运行该 PR 引入 / 涉及的自动化测试（pytest 等），不依赖尚未合并的后续 PR。
3. **禁止单 PR 实现全部 MVP**：任何单个 PR 都不得越界实现其他 PR 的范围。例如 PR-01 不得提前实现拆镜头、AI 分析、搜索或脚本匹配；PR-02 不得提前调用 AI。
4. **范围内闭环、范围外只预留**：当前 PR 只交付本 PR 范围清单内的能力；对后续 PR 的能力只能预留接口骨架 / 字段 / 文档，不得交付半成品功能。
5. **数据库迁移只增不毁**：禁止删库重建。每个 PR 通过新的 Alembic 迁移演进 schema，迁移可 `alembic upgrade head` 也可回退验证。
6. **安全红线不可破**：源目录只读挂载（`:ro`）、白名单根校验、无源文件删除接口、不提交视频 / 密钥、默认仅绑 `127.0.0.1`、无鉴权不公开——任何 PR 都不得削弱这些约束。

> **完整 MVP 的定义**：只有 PR-01、PR-02、PR-03、PR-04、PR-05 **全部合并后**，才构成完整的 **ClipMind MVP v0.1**。任何单独一个 PR 都不是 MVP，也不应被宣称为「MVP 已完成」。

### 1.1 PR 依赖关系（线性递进）

```text
PR-01 基础架构 + 只读素材索引
   │  (Asset / ScanRun 数据与扫描闭环就绪)
   ▼
PR-02 拆镜头 + 派生文件
   │  (Shot 表与派生文件就绪，供 AI 使用)
   ▼
PR-03 AI 理解 + 人工审核
   │  (AIAnalysis / Review / Tag 与镜头描述就绪)
   ▼
PR-04 搜索 + 画面描述匹配
   │  (pgvector + embedding 向量检索就绪)
   ▼
PR-05 脚本匹配 + 剪辑清单 CSV 导出
   │
   ▼
ClipMind MVP v0.1（五个 PR 全部合并）
```

依赖说明：PR 之间为严格线性依赖，后一个 PR 在功能上依赖前一个 PR 的产物（PR-02 需要 PR-01 的 Asset；PR-03 需要 PR-02 的 Shot 与派生文件；PR-04 需要 PR-03 的镜头描述用于向量化；PR-05 需要 PR-04 的检索能力召回候选镜头）。但每个 PR 仍必须从最新 main 开分支、可独立验收。

---

## 2. PR-01 `feat/mvp-foundation`：基础架构 + 只读素材索引

> 状态：**已合并**。下文为该 PR 的范围与验收基线，保留以供追溯。

### 2.1 分支名

`feat/mvp-foundation`（从最新 `main` 开新分支）

### 2.2 目标

搭建 monorepo 基础架构与 Docker Compose 编排，打通「配置只读源目录 → 扫描 → 增量变化检测 → 入库 Asset → 列表 / 详情查询」的最小闭环。本 PR 是后续所有 PR 的地基，但**不做**拆镜头、不做 AI、不做搜索、不做脚本匹配。

### 2.3 范围清单

- 目录结构（monorepo）：根 `compose.yml`、`apps/web`、`apps/api`、`services/worker`（包名 `clipmind_worker`）、`packages/shared`（包名 `clipmind_shared`）、`infra/`（api / worker / web 三个 Dockerfile）、`docs/`、`scripts/`、`sample_media/`（只读源目录，禁止提交视频）。
- Docker Compose 6 个服务（见 2.7）。
- 后端 FastAPI + Pydantic + SQLAlchemy(async) + Alembic 工程骨架。
- 数据模型与 `0001_initial` 迁移：`SourceDirectory`、`Asset`、`ScanRun`（详见 2.6）。**不建 pgvector 扩展。**
- 扫描流程：以 DB 为事实来源，事务内建 `ScanRun(queued)` + 目录 `queued` → 提交 → 入队 Celery → 写 `celery_task_id`；worker 用 PostgreSQL session 级 advisory lock（绑定单连接、跨多次 commit）执行；分层变化检测（先 size+mtime，未变不读内容不 probe；新增 / 变化才算 quick_hash 与 FFprobe）；缺失检测基于 `last_seen_scan_id`，仅遍历完整成功后用 SQL 批量置 `source_missing`，失败 / 取消不标记。
- PR-01 API（见 2.5）。
- 前端 Next.js + React + TS + Tailwind + TanStack Query 骨架；服务端 rewrites 把 `/api` 代理到 `api:8000`；最小的源目录配置页与素材列表 / 详情页可用。
- `clipmind_shared/ai/provider.py` 仅提供 `AIProvider` 接口骨架与 `ProviderCapabilities`（见 2.8），**本 PR 不做任何真实 AI 调用**。
- 安全基线（见 1 总则第 6 条）、`.env.example`（仅提交示例，`.env` 被忽略）、README、本路线图等文档。

### 2.4 不在本 PR 范围（明确排除）

拆镜头、关键帧 / 缩略图 / 代理 / 片段裁剪、AI 分析、人工审核、搜索 / 向量、脚本匹配、CSV 导出，以及 scheduler/beat、ai/media/export worker 的启动。

### 2.5 PR-01 API 清单

- `GET /health/live`、`GET /health/ready`
- `GET /api/system/status`
- `GET /api/source-directories`、`POST /api/source-directories`
- `GET /api/source-directories/{id}`、`PUT /api/source-directories/{id}`
- `POST /api/source-directories/{id}/scan`
- `GET /api/source-directories/{id}/status`
- `GET /api/assets`（分页 + 文件名搜索 + status 筛选）
- `GET /api/assets/{id}`
- `POST /api/assets/{id}/rescan`

### 2.6 新表 / 新迁移要点

- 迁移文件：`0001_initial`（禁止删库重建；**不建 pgvector 扩展**）。
- 新表：
  - **SourceDirectory**：`id, name, mount_path`（容器逻辑路径，须在白名单根下）`, enabled, recursive, include_extensions(JSONB), exclude_patterns(JSONB), read_only`（强制 `true`）`, scan_status, last_scanned_at, created_at, updated_at`。
  - **Asset**：`id, source_directory_id, relative_path, normalized_relative_path`（POSIX + NFC，用于唯一约束）`, filename, extension, file_size, modified_at, quick_hash, full_hash`（后续 PR 预留）`, duration, width, height, fps, video_codec, audio_codec, orientation, has_audio, status, error_message, last_seen_scan_id, metadata_version, first_seen_at, last_seen_at, created_at, updated_at`；唯一约束 `(source_directory_id, normalized_relative_path)`。
  - **ScanRun**：`id, source_directory_id, status, celery_task_id, queued_at, started_at, heartbeat_at, finished_at, worker_name, files_discovered/new/modified/missing/errored, error_message`；部分唯一索引 `(source_directory_id) WHERE status IN ('queued','running')`。
- 枚举：
  - `AssetStatus`：`discovered / indexed / error / source_missing` + 预留 `pending / processing / shot_split / ai_analyzing / pending_review / searchable / paused / archived`。
  - `ScanStatus`：`never_scanned / queued / scanning / completed / failed / cancelled`。
  - `ScanRunStatus`：`queued / running / completed / failed / cancelled`。
- 时间统一 UTC、timezone-aware。

### 2.7 Docker Compose（6 个服务）

| 服务 | 镜像 / 命令 | 要点 |
| --- | --- | --- |
| postgres | `pgvector/pgvector:pg16` | 命名卷 `pgdata` 持久化；本 PR 不建 pgvector 扩展 |
| redis | `7-alpine` | Celery broker |
| migrate | 一次性 `alembic upgrade head` | 启动顺序前置 |
| api | `uvicorn` | 绑 `127.0.0.1`，healthcheck = `/health/live` |
| worker | `celery -A clipmind_worker.celery_app worker -Q default,scan` | 仅 default、scan 两个队列 |
| web | `next start` | 服务端 rewrites 把 `/api` 代理到 `api:8000` |

- **不启动** scheduler/beat、ai/media/export worker。
- 挂载 `./sample_media:/app/source:ro` 与命名卷 `clipmind-data:/app/data`。

### 2.8 新依赖要点

- 后端：FastAPI、Pydantic、SQLAlchemy(async)、Alembic、Celery、redis 客户端、FFprobe（探测，本 PR 仅在变化检测中用于读基础元数据）。
- 前端：Next.js、React、TypeScript、Tailwind、TanStack Query。
- `clipmind_shared/ai/provider.py`：`AIProvider` 接口骨架，含 `health_check / analyze_frames / analyze_video_clip / parse_search_query / parse_script / generate_embedding / rerank_candidates`；`ProviderCapabilities`（`supports_images / supports_video / supports_structured_output / supports_embeddings / max_images_per_call / context_window`）。预留环境键 `AI_*` / `EMBEDDING_*`，本 PR 不做真实调用。

### 2.9 验收要点

- `docker compose up` 后 6 个服务健康；`migrate` 成功 `upgrade head`。
- `GET /health/live`、`GET /health/ready`、`GET /api/system/status` 正常返回。
- 能创建只读源目录（`read_only` 强制 `true`），`POST .../scan` 后 `ScanRun` 状态从 `queued` 走到 `completed`，`Asset` 正确入库；`GET /api/assets` 分页 / 文件名搜索 / status 筛选可用。
- 增量验证：第二次扫描中未变文件不重算 quick_hash、不 FFprobe；新增 / 修改文件被正确识别；删除文件在整次扫描成功后被批量置 `source_missing`，扫描失败 / 取消时不标记缺失。
- 安全验证：源目录为 `:ro`；无任何修改 / 删除 / 移动 / 改名源文件的代码路径；白名单根（`ALLOWED_SOURCE_ROOTS=/app/source`）+ `realpath` 包含检查 + 软链逃逸防护生效；仓库未提交视频 / 密钥，`.env` 被忽略，仅有 `.env.example`。
- 自动化测试：本 PR 范围内的 pytest 全部通过（扫描状态机、变化检测、路径白名单等）。

---

## 3. PR-02 `feat/shot-processing`：拆镜头 + 派生文件

> 状态：**当前阶段，已实现**。本 PR 仅实现拆镜头与 FFmpeg 派生文件，**不调用 AI、不做搜索 / 脚本匹配**（那是 PR-03~05）。下文范围 / 依赖 / 验收约束仍然有效，作为已实现要点的核对清单。

### 3.1 分支名

`feat/shot-processing`（从最新 `main` 开新分支）

### 3.2 目标

在已索引的 Asset 之上，用 PySceneDetect 进行镜头边界检测，落库 `Shot`，并用 FFmpeg **提取 / 裁剪 / 转码**派生文件：关键帧、缩略图、代理视频、可下载片段（按需裁剪下载）。**本 PR 不调用 AI**。

> 再次强调：此处「生成」全部为 FFmpeg 派生处理，非生成式能力。

### 3.3 范围清单

- 引入 `media-worker`（专用 `media` 队列，默认并发 1，env `MEDIA_WORKER_CONCURRENCY`），承担拆镜头 / 派生 / 导出任务。
- 可替换的 `ShotDetector` 接口：PySceneDetect ContentDetector 主（opencv-python-headless 后端）+ 固定时长切分兜底 + 纯函数后处理（短合并 / 长拆分 / 首尾余量 / clamp，遵循 PRD 7.4）。
- FFmpeg 派生：每镜头主关键帧 + 可选辅助关键帧、缩略图（统一尺寸、保持比例、WebP/JPEG）、代理视频（H.264 + yuv420p + faststart + ≤720P、可配置音频）、按需裁剪可下载片段。
- 派生文件统一写入命名卷 `clipmind-data:/app/data`（按 `assets/{asset_id}/active/shots/...`、`runs/{run_uuid}/staging/`、`exports/{export_uuid}/...` 布局），不写入源目录。
- `Shot` / `MediaProcessingRun` / `Export` 表与 `0002_shot_processing` 迁移（见 3.6）。
- 镜头分析 / 镜头 / 导出 API：`POST /api/assets/{id}/analyze-shots`、`GET /api/assets/{id}/shot-analysis`、`POST /api/assets/{id}/shot-analysis/retry`、`GET /api/assets/{id}/shots`、`GET /api/shots`、`GET /api/shots/{id}`、`GET /api/shots/{id}/thumbnail|keyframe|preview`（preview 支持 HTTP Range 206/Content-Range/416）、`POST /api/shots/{id}/export`、`GET /api/exports/{id}`、`GET /api/exports/{id}/download`（Content-Disposition RFC5987 编码，支持中文名）。
- 前端：镜头库页 `/shots`（网格 + 详情主从布局）、`/shots/[id]` 深链详情；TopNav 增加「素材库 / 镜头库」导航；素材表增加镜头数 / 分析状态 / 开始分析 / 查看镜头 / 重试。**不显示伪造 AI 状态**，用占位文案「AI 内容分析将在 PR-03 提供」。

### 3.4 不在本 PR 范围（明确排除）

任何 AI 调用与打标、人工审核、向量与搜索、脚本匹配、CSV 导出。镜头的 AI 描述 / 标签 / 风险 / 审核字段不在本 PR 的 `Shot` 表中，由 PR-03 的迁移新增并填充。

### 3.5 依赖关系

依赖 PR-01：需要 `Asset` 与扫描闭环作为输入。被 PR-03 依赖：PR-03 需要 `Shot` 与关键帧 / 代理派生文件作为 AI 输入。

### 3.6 新依赖 / 新表 / 新迁移要点

- **新依赖**：`scenedetect`（PySceneDetect 镜头检测）、`opencv-python-headless`（检测后端；worker.Dockerfile 固定 `python:3.13-slim-bookworm` 并显式安装 `ffmpeg libglib2.0-0 libgl1`，构建期 `import cv2, scenedetect` 硬校验）+ media-worker（新增 `media` 队列与专用 worker 进程）+ FFmpeg（派生处理，PR-01 已具备运行时）。
- **新表**：
  - `Shot`（`id, asset_id`(FK CASCADE)`, processing_run_id, generation, sequence_no, start_time, end_time, duration, detector_type, detector_confidence, status, error_message, keyframe_path, thumbnail_path, proxy_path, created_at, updated_at`；唯一约束 `(asset_id, generation, sequence_no)`）。AI 字段（描述 / 标签 / 风险 / 审核）**不在本 PR**，留待 PR-03；`embedding` 列留待 PR-04。
  - `MediaProcessingRun`（仿 `ScanRun`：`run_uuid, asset_id, celery_task_id, status, progress, current_step, total_shots, completed_shots, error_message, generation, config_snapshot, queued_at/started_at/heartbeat_at/finished_at, worker_name`；部分唯一索引 `uq_active_media_run` 保证同一素材至多一个活动运行 `queued/running`）。
  - `Export`（`id, export_uuid, asset_id, shot_id`(SET NULL)`, status, mode, output_path, filename, ...` + **来源快照**`source_shot_id, source_generation, source_sequence_no, source_start_time, source_end_time, source_filename, source_relative_path`，均不为空，永久可追溯，旧 Shot 被重分析删除后导出仍可下载与追溯）。
- **新枚举**：`ShotStatus` / `MediaRunStatus` / `ExportStatus`；`AssetStatus` 复用已有的 `processing` / `shot_split`（无需枚举迁移）。
- **新迁移**：`0002_shot_processing`（`down_revision='0001_initial'`；新增上述三表；**不改动 0001、不建 pgvector 扩展**）。只增不毁，可 `upgrade head` 与回退验证。`Asset.full_hash` 仍为预留列，PR-02 不使用。
- **新增 env**（已在 `.env.example`）：`FFMPEG_TIMEOUT, MEDIA_WORKER_CONCURRENCY, DISK_MIN_FREE_MB, SHOT_DETECTOR_TYPE, SCENE_THRESHOLD, MIN_SHOT_DURATION, MAX_SHOT_DURATION, FALLBACK_SEGMENT_DURATION, HEAD_PADDING, TAIL_PADDING, PROXY_MAX_HEIGHT, PROXY_CRF, PROXY_PRESET, PROXY_KEEP_AUDIO, PROXY_AUDIO_BITRATE, KEYFRAME_MAX_WIDTH, THUMBNAIL_MAX_WIDTH, AUX_KEYFRAMES`。
- **派生文件布局**（命名卷 `clipmind-data:/app/data`，不写源）：`assets/{asset_id}/active/shots/{shot_id}/{keyframe.webp,thumbnail.webp,proxy.mp4}`、`assets/{asset_id}/runs/{run_uuid}/staging/`、`exports/{export_uuid}/clip.mp4`。
- **重新分析原子代次替换**：旧镜头在新分析完整成功前持续可用；以 PostgreSQL 为事实来源；素材级 advisory lock（命名空间 `0x4D44`）+ `uq_active_media_run` 部分唯一索引防重；`acks_late` 断点恢复。
- 详见 `docs/SHOT_PROCESSING.md`。

### 3.7 验收要点（已实现，作为核对清单）

- 对 `sample_media` 中样例视频执行处理后，`Shot` 记录的 `start_time / end_time / duration / sequence_no` 与实际镜头一致，时间码正确。
- 关键帧、缩略图、代理视频正确生成于 `clipmind-data`，浏览器可直接播放代理视频（preview 接口支持 Range 拖动 seek）。
- 按需裁剪的片段可下载（默认 reencode 精确边界），入点 / 出点正确，源文件保持只读、未被改动。
- 处理失败可重试，不影响其他任务；`media-worker`（`media` 队列）可独立运行；重新分析采用原子代次替换，旧镜头在新分析完整成功前持续可用。
- 本 PR 范围内 pytest 通过（镜头边界、派生路径、时间码计算等）。

---

## 4. PR-03 `feat/ai-shot-analysis`：AI 理解 + 人工审核

### 4.1 分支名

`feat/ai-shot-analysis`（从最新 `main` 开新分支）

### 4.2 目标

接入外部 AI（小米 MiMo），对镜头关键帧（必要时短代理片段）做结构化理解打标，并提供人工审核兜底。通过 `AIProvider` 抽象统一调用，先执行**能力探测**再决定调用与降级策略。

### 4.3 范围清单

- 落地 `AIProvider` 的 MiMo 实现（PR-01 已有接口骨架），实现 `health_check / analyze_frames / analyze_video_clip / parse_search_query / parse_script / generate_embedding / rerank_candidates`（本 PR 至少落地画面理解相关方法；查询 / 脚本解析在后续 PR 真正消费）。
- **能力探测**（本 PR 才执行真实调用）：连通性 / 鉴权 / OpenAI 兼容 / 文本 / 严格 JSON / JSON Schema / 单图 / 多图 / Base64 图 / URL 图 / Embedding / 上下文 / 并发 / 超时 / 限流 / 错误码 / 数据是否被保留。
- AI 结构化输出（遵循 PRD 7.6）：一句话描述、详细描述、产品 / 场景 / 动作 / 镜头类型 / 风险 / 质量 / 置信度 / 是否需人工确认等；JSON Schema 校验，失败自动重试，多次失败入人工队列；保留脱敏原始响应日志。
- **降级策略**：不支持图片 → 仅文本角色，视觉镜头降级为待人工确认，**绝不伪造视觉成功**；不支持 Embedding → 走独立 `EMBEDDING_PROVIDER`（embedding 真正写库在 PR-04）。
- 人工审核：审核状态机、审核记录（审核人 / 时间 / 修改前后 / 意见）、**人工结果优先于 AI 结果**，AI 重新分析不得覆盖人工确认结果（除非管理员显式覆盖）。
- AI / 审核 / 标签相关 API（PRD 13.3 / 13.4 范围，如 `POST /api/assets/{id}/analyze`、`PUT /api/shots/{id}`、`POST /api/shots/{id}/review`、标签查询等）。

### 4.4 不在本 PR 范围（明确排除）

向量检索与自然语言搜索的对外能力、画面描述匹配、脚本匹配、CSV 导出。本 PR 不启用 pgvector、不写 embedding 向量列。

### 4.5 依赖关系

依赖 PR-02：需要 `Shot` 与关键帧 / 代理派生文件作为 AI 输入。被 PR-04 依赖：PR-04 需要镜头的结构化描述用于向量化检索。

### 4.6 新依赖 / 新表 / 新迁移要点

- **新依赖**：AIProvider 的 MiMo 实现（OpenAI 兼容客户端 / HTTP 客户端）+ JSON Schema 校验库 + ai worker（AI 调用队列）。
- **新表 / 字段**：`AIAnalysis`（`id, shot_id, provider, model, prompt_version, input_summary, raw_response, parsed_result, confidence, status, cost, duration_ms, created_at`，遵循 PRD 12.8）；`Review`（`id, object_type, object_id, reviewer_id, before_data, after_data, action, comment, created_at`，遵循 PRD 12.9）；`Tag / ShotTag`（`tag_id, tag_type, tag_name, source, confidence, confirmed_by, confirmed_at`，遵循 PRD 12.6）；填充 `Shot` 的 `description / quality_score / risk_level / review_status`。
- **新迁移**：`0003_ai_review`（新增 `AIAnalysis / Review / Tag / ShotTag`，并补充 `Shot` 相关字段）。只增不毁；**仍不建 pgvector 扩展**。
- 环境键：消费 PR-01 预留的 `AI_*`；`EMBEDDING_*` 在不支持 Embedding 时指向独立 provider。

### 4.7 验收要点

- `AIProvider.health_check` 与能力探测可独立运行，输出探测报告；按探测结果决定调用与降级。
- 对样例镜头产生结构化 JSON，通过 JSON Schema 校验；缺字段返回空值不编造；低置信度 / 风险命中进入待审核。
- 人工修改后再次触发 AI 分析，人工结果不被自动覆盖（除非显式覆盖）。
- 不支持图片时视觉镜头降级为待人工确认，且日志 / 状态不伪造视觉成功。
- 原始响应有脱敏日志；密钥不出现在日志与代码中。
- 本 PR 范围内 pytest 通过（Schema 校验、重试、降级、审核优先级、覆盖保护等，AI 网络调用以可控方式 mock 或在探测开关下运行）。

---

## 5. PR-04 `feat/shot-search`：搜索 + 画面描述匹配

> ⚠️ **已过时，仅作追溯**。本节写于 PR-03A/03B 重构之前，下述 `Shot.embedding` 列、`0004_pgvector`
> 迁移、`ivfflat`、`POST /api/search`/`/search/similar`/`/search/history` 均已被新设计取代。
> **实际实现以 `docs/SEMANTIC_SEARCH.md` 与 `docs/PROJECT_COMPLETION_PLAN.md` 为准**：
> 分支 `feat/semantic-shot-search`；迁移 `0007_semantic_search`（down_revision `0006_ai_review_products`）；
> 新表 `shot_search_document`（非在 `Shot` 上加列）；**HNSW**（非 ivfflat）；独立 `EmbeddingProvider`
> 抽象 + 本地 embedder 微服务（e5-small/384）；API 为 `POST /api/search/shots`、`POST /api/match/description`、
> `GET /api/search/suggestions`、`GET /api/search/index/status`；SearchHistory 暂缓。

### 5.1 分支名

`feat/shot-search`（从最新 `main` 开新分支）

### 5.2 目标

在本 PR 启用 pgvector，对镜头描述 / 标签生成 embedding 并建立向量索引，提供自然语言搜索与画面描述匹配，结合结构化标签 / 人工确认状态 / 风险 / 质量 / 时长等进行重排。

### 5.3 范围清单

- **在本 PR 用独立迁移启用 pgvector**（PR-01~03 一直未建扩展）。
- 为 `Shot` 增加 embedding 向量列并建 ivfflat 索引。
- embedding 生成流程：消费 PR-03 的镜头描述，调用 `generate_embedding`（或独立 `EMBEDDING_PROVIDER`）写入向量列。
- 自然语言查询解析（`parse_search_query`）→ 文本向量 → 向量召回 → 结合结构化条件重排（`rerank_candidates`，遵循 PRD 7.10.4）。
- 画面描述匹配（PRD 7.11）：输入一句目标画面描述，返回候选镜头 + 匹配度 + 匹配 / 不匹配项 + 风险提示。
- 搜索 API（PRD 13.5，如 `POST /api/search`、`POST /api/search/similar`、`GET /api/search/history`）与多条件筛选 / 排序。

### 5.4 不在本 PR 范围（明确排除）

脚本拆分、脚本段落匹配、剪辑清单与 CSV 导出（属 PR-05）。

### 5.5 依赖关系

依赖 PR-03：需要镜头结构化描述用于向量化。被 PR-05 依赖：PR-05 用本 PR 的检索能力为脚本段落召回候选镜头。

### 5.6 新依赖 / 新表 / 新迁移要点

- **新依赖**：pgvector 扩展能力（postgres 镜像已具备，需在迁移中 `CREATE EXTENSION`）；embedding provider 客户端。
- **新迁移**：`0004_pgvector`（`CREATE EXTENSION IF NOT EXISTS vector`；为 `Shot` 增加 embedding 向量列；创建 ivfflat 索引）。这是 pgvector **首次启用**的迁移，独立成一个 PR 的独立迁移，只增不毁。
- 无新业务实体表（搜索历史 `SearchHistory` 可按 PRD 12.10 在本 PR 引入用于记录查询）。

### 5.7 验收要点

- `0004_pgvector` 迁移成功，pgvector 扩展启用，embedding 向量列与 ivfflat 索引建立。
- 镜头描述能生成 embedding 并写入；自然语言查询能召回相关镜头，返回匹配度与匹配理由。
- 重排考虑标签 / 人工确认 / 风险 / 质量 / 时长等；可按多条件筛选与排序。
- 画面描述匹配返回候选镜头与匹配 / 不匹配 / 风险提示。
- 搜索首屏响应符合 PRD 8.1 性能预期（局域网环境）。
- 本 PR 范围内 pytest 通过（向量召回、重排、筛选、降级到关键词等）。

---

## 6. PR-05 `feat/script-shot-matching`：脚本匹配 + 剪辑清单 CSV 导出

### 6.1 分支名

`feat/script-shot-matching`（从最新 `main` 开新分支）

### 6.2 目标

打通脚本到剪辑准备的闭环：粘贴 / 上传脚本 → AI 拆分段落并提取画面需求 → 为每段召回候选镜头 → 人工选择 / 替换 → 导出剪辑清单 CSV。

### 6.3 范围清单

- 脚本输入与拆分（`parse_script`，遵循 PRD 7.12.1 / 7.12.2），每段生成画面需求 / 推荐场景 / 动作 / 镜头类型 / 产品 / 卖点 / 预计时长 / 必须与禁止出现内容。
- 镜头推荐：每段默认 3 个（可配 1~10）候选，复用 PR-04 检索召回 + 重排；附匹配度 / 推荐理由 / 命中项 / 时长是否合适 / 是否已用于其他段落 / 风险 / 审核状态。
- 自动约束（PRD 7.12.4）：避免同镜头重复、连续高相似、时长不足、产品 / 场景冲突、风险镜头自动入选等。
- 无匹配处理（PRD 7.12.5）：明确「无合适素材」+ 缺失画面描述 + 补拍建议。
- 剪辑清单（PRD 7.12.6）字段落库与 **CSV 导出**（本 PR 仅交付 CSV；XLSX/JSON/Markdown/ZIP 不在本 PR）。
- 脚本相关 API（PRD 13.6，如 `POST /api/scripts`、`POST /api/scripts/{id}/parse`、`POST /api/scripts/{id}/match`、`PUT /api/scripts/{id}/segments/{segment_id}`、`POST /api/scripts/{id}/export`）。

### 6.4 不在本 PR 范围（明确排除）

XLSX / JSON / Markdown / 可打印页面 / 片段 ZIP 等其他导出格式；自动成片等任何生成式能力（始终排除）。

### 6.5 依赖关系

依赖 PR-04：用其检索能力为脚本段落召回候选镜头。本 PR 是 MVP v0.1 的最后一块拼图，合并后五个 PR 共同构成完整 MVP v0.1。

### 6.6 新依赖 / 新表 / 新迁移要点

- **新依赖**：export worker（CSV 导出任务队列）；CSV 序列化（标准库即可，无重型新依赖）。
- **新表**：`ScriptProject`（`id, name, script_text, owner_id, status, created_at, updated_at`，PRD 12.11）；`ScriptSegment`（`id, script_project_id, sequence_no, text, visual_requirement, expected_duration, product_id, scene, action, shot_type`，PRD 12.12）；`ShotRecommendation`（`id, script_segment_id, shot_id, score, reason, risk, selected, created_at`，PRD 12.13）。
- **新迁移**：`0005_script_matching`（新增上述三表）。只增不毁。

### 6.7 验收要点

- 能粘贴 / 上传脚本，自动拆段并提取画面需求。
- 每段能召回多个候选镜头并显示匹配度 / 理由 / 风险 / 审核状态；可人工替换。
- 自动约束生效（去重 / 时长 / 冲突过滤）；无合适镜头时输出补拍建议，不强行推荐低质量镜头。
- 能导出剪辑清单 CSV，字段完整、入点 / 出点 / 时长正确。
- 本 PR 范围内 pytest 通过（拆段、推荐、约束、CSV 导出等）。

---

## 7. MVP v0.1 合并完成判定

当 PR-01 ~ PR-05 全部合并到 `main` 后，系统应整体满足：

- 配置只读源目录 → 扫描索引 Asset（PR-01）；
- 拆镜头并生成关键帧 / 缩略图 / 代理 / 可下载片段（PR-02）；
- AI 结构化打标 + 人工审核兜底，人工结果优先（PR-03）；
- 自然语言搜索与画面描述匹配，pgvector 向量检索（PR-04）；
- 脚本逐段匹配镜头并导出剪辑清单 CSV（PR-05）。

此时方可称为 **ClipMind MVP v0.1**。在此之前，任何单 PR 都不得被宣称为「MVP 完成」。

> 提醒：MVP v0.1 的验收均在本地 `sample_media` 与本地 Docker Compose 环境进行；**正式 NAS 部署属于后续工作，本路线图不宣称已完成真实 NAS 部署。**

---

## 8. 迁移序列与队列演进速查

| PR | 分支 | Alembic 迁移 | 新增 worker / 队列 | pgvector |
| --- | --- | --- | --- | --- |
| PR-01 | `feat/mvp-foundation` | `0001_initial`（SourceDirectory / Asset / ScanRun） | worker（default, scan） | 不启用 |
| PR-02 | `feat/shot-processing` | `0002_shot_processing`（Shot / MediaProcessingRun / Export） | media-worker（queue `media`） | 不启用 |
| PR-03 | `feat/ai-shot-analysis` | `0003_ai_review`（AIAnalysis / Review / Tag / ShotTag） | ai worker | 不启用 |
| PR-04 | `feat/shot-search` | `0004_pgvector`（CREATE EXTENSION + embedding 向量列 + ivfflat） | （检索 / embedding） | **本 PR 启用** |
| PR-05 | `feat/script-shot-matching` | `0005_script_matching`（ScriptProject / ScriptSegment / ShotRecommendation） | export worker | 已启用 |

> 所有迁移只增不毁；每个 PR 从最新 main 开分支、可独立运行测试验收；任何单 PR 都不得实现全部 MVP；五个 PR 全部合并后才构成完整 MVP v0.1。
