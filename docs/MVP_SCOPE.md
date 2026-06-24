# ClipMind MVP 范围

> 本文件是 ClipMind 完整 MVP（v0.1）的范围说明，是产品定位、功能边界与各 PR 拆分的「唯一事实来源」之一。
> 阅读对象：开发、评审、产品。任何与本文件冲突的口头约定一律以本文件为准。

---

## 1. 产品定位与价值

ClipMind 是一套**面向公司 NAS 部署**的「**AI 视频素材管理与智能匹配系统**」。

它解决的核心问题是：公司 NAS 上积累了大量历史视频素材，但「找素材」依赖人脑记忆和手动翻文件夹，效率低、复用率低。ClipMind 让素材**可被检索、可被理解、可被快速匹配到具体剪辑需求**。

核心能力（完整 MVP 闭环）：

1. **只读索引**：扫描 NAS 上的视频素材目录，建立可检索的元数据索引（绝不改动源文件）。
2. **拆镜头与派生文件**：用 FFmpeg / PySceneDetect 把整段视频拆成镜头，提取关键帧、缩略图、代理视频、片段裁剪等派生文件。
3. **外部 AI 理解打标**：调用外部 AI 模型（小米 MiMo 等）对镜头进行画面描述、标签生成。
4. **人工确认**：AI 结果进入人工审核环节，确认或修正后才进入可检索状态。
5. **自然语言检索**：用一句话（自然语言）查找素材。
6. **画面描述匹配**：根据「画面描述」匹配到符合视觉内容的镜头。
7. **脚本逐段匹配**：把一段剪辑脚本逐段拆解，为每一段匹配候选镜头。
8. **剪辑清单导出**：把匹配结果导出为剪辑清单（CSV）与对应片段，供剪辑师直接使用。

价值定位一句话：**让剪辑师用一句话或一段脚本，就能从海量 NAS 素材里精准捞出能用的镜头，并直接拿到一份可执行的剪辑清单。**

> 部署现状声明：本项目以「面向公司 NAS 部署」为**设计目标**。截至本文件，尚未完成任何真实 NAS 生产环境部署；当前阶段以本地 Docker Compose 开发环境为准。

---

## 2. 明确排除的能力（不做项）

ClipMind 是「**素材管理与匹配**」工具，**不是内容生成工具**。以下生成式能力**明确不做**，任何阶段都不在范围内：

- **文生视频**（text-to-video）
- **图生视频**（image-to-video）
- **数字人** / 虚拟主播
- **声音克隆** / 语音合成换声
- **视频复刻**（对已有视频做风格化再生成）
- **替换人物 / 替换产品**（在画面中换脸、换物）
- **自动成片**（自动拼接生成成品视频）

### 关于「生成关键帧 / 缩略图 / 代理视频 / 片段」的澄清

文档与代码中出现的「生成关键帧」「生成缩略图」「生成代理视频」「生成片段」等说法，指的是：

> 用 **FFmpeg / FFprobe 对源视频做提取、裁剪、转码，产出派生文件**。

这是**确定性的转码 / 抽帧操作，不是生成式 AI 能力**。源视频本身始终只读、不被改动，派生文件单独写入数据卷。请勿将其理解为「AI 生成画面」。

---

## 3. 完整 MVP v0.1 的功能闭环

完整 MVP 是一条端到端的闭环，从「素材在 NAS 上」到「剪辑师拿到剪辑清单」：

```
素材目录扫描（只读索引）
      ↓
视频信息提取（FFprobe：时长/分辨率/编码/帧率/音轨等）
      ↓
拆镜头（PySceneDetect 场景切分）
      ↓
关键帧 / 缩略图 / 代理视频 / 片段（FFmpeg 提取与裁剪派生文件）
      ↓
AI 描述与标签（外部 AI 理解：画面描述 + 标签）
      ↓
人工确认（审核 / 修正 AI 结果，确认后才可检索）
      ↓
自然语言查找（一句话检索素材）
      ↓
画面描述匹配（按视觉画面内容匹配镜头）
      ↓
脚本逐段匹配（脚本分段 → 每段匹配候选镜头）
      ↓
导出剪辑清单与片段（CSV 清单 + 片段文件）
```

这条闭环由 5 个 PR 分阶段交付（见第 5 节）。

---

## 4. 完整 MVP 功能分组（A~E）

下面按 A~E 分组列出完整 MVP（v0.1）的全部功能。**分组是功能视角，不是交付顺序**；交付顺序见第 5 节 PR 拆分。

### A. 素材索引与目录管理

- A1 配置源目录（只读、白名单根下、可设递归 / 扩展名过滤 / 排除模式）。
- A2 扫描源目录，建立素材索引（DB 为事实来源）。
- A3 分层变化检测（先 size + mtime，未变不读内容；新增 / 变化才算 quick_hash + FFprobe）。
- A4 缺失检测（扫描完整成功后批量标记 `source_missing`）。
- A5 素材列表（分页 + 文件名搜索 + 状态筛选）与素材详情。
- A6 提取视频信息（时长 / 分辨率 / 编码 / 帧率 / 朝向 / 音轨等）。

### B. 拆镜头与派生文件（**已实现，PR-02**）

- B1 场景切分拆镜头（PySceneDetect ContentDetector 主 + 固定时长切分兜底 + 纯函数后处理）。
- B2 关键帧提取（FFmpeg）。
- B3 缩略图生成（FFmpeg）。
- B4 代理视频生成（FFmpeg 转码低码率预览，H.264 + yuv420p + faststart + ≤720P，浏览器可播）。
- B5 片段裁剪与下载（FFmpeg 按镜头时间区间裁剪源片段，默认 reencode 精确边界，可选 stream copy）。

### C. AI 理解与人工审核

- C1 AI 画面描述（外部 AI 模型，AIProvider 抽象）。
- C2 AI 标签生成。
- C3 能力探测（先探测外部 AI 的图片 / 视频 / 结构化输出 / Embedding 等能力，再决定调用方式与降级策略）。
- C4 人工审核（确认 / 修正 AI 结果，确认后镜头才进入可检索状态）。
- C5 降级策略（不支持图片 → 仅文本角色，视觉镜头降级待人工确认，绝不伪造视觉成功）。

### D. 检索与画面匹配

- D1 自然语言查询解析（把一句话拆成可检索条件）。
- D2 关键词 / 标签检索。
- D3 画面描述匹配（按视觉画面内容匹配镜头）。
- D4 向量语义检索（pgvector 在 PR-04 用独立迁移启用）。

### E. 脚本匹配与导出

- E1 脚本解析（把一段剪辑脚本逐段拆解）。
- E2 脚本逐段匹配（为每一段匹配候选镜头）。
- E3 剪辑清单导出（CSV）。
- E4 导出对应片段文件。

---

## 5. PR 拆分（完整 MVP 分 5 个 PR 交付）

| PR | 分支 | 范围 | 对应功能分组 |
| --- | --- | --- | --- |
| **PR-01** | `feat/mvp-foundation` | 基础架构 + 只读素材索引（**已合并**） | A（索引 / 目录管理）+ AI 接口骨架（仅文档与接口，不真实调用） |
| **PR-02** | `feat/shot-processing` | 拆镜头 + 派生文件（关键帧 / 缩略图 / 代理 / 片段裁剪下载，PySceneDetect）（**当前**） | B |
| **PR-03** | `feat/ai-shot-analysis` | AI 理解 + 人工审核（小米 MiMo，AIProvider 抽象，先能力探测） | C |
| **PR-04** | `feat/shot-search` | 搜索 + 画面描述匹配（pgvector 在此 PR 用独立迁移启用） | D |
| **PR-05** | `feat/script-shot-matching` | 脚本匹配 + 剪辑清单 CSV 导出 | E |

---

## 6. PR-01 基线范围与不做项

**PR-01 = `feat/mvp-foundation`：基础架构 + 只读素材索引。** PR-01 已合并，是后续所有 PR 的地基；当前正在交付的一轮是 PR-02（拆镜头 + 派生文件，见上表 B 组）。本节保留 PR-01 的基线范围与其当轮不做项，供追溯地基约束。

### 6.1 PR-01 本轮要做（范围内）

**基础架构**

- monorepo 目录结构落地：根 `compose.yml`、`apps/web`、`apps/api`、`services/worker`（包名 `clipmind_worker`）、`packages/shared`（包名 `clipmind_shared`）、`infra/`（api / worker / web 三个 Dockerfile）、`docs/`、`scripts/`、`sample_media/`（只读源目录，禁止提交视频）。
- Docker Compose 6 个服务（PR-01 基线；PR-02 在此基础上新增 `media-worker`，共 7 个）：
  - `postgres`（`pgvector/pgvector:pg16`）
  - `redis`（`7-alpine`）
  - `migrate`（一次性 `alembic upgrade head`）
  - `api`（uvicorn，绑 `127.0.0.1`，healthcheck = `/health/live`）
  - `worker`（`celery -A clipmind_worker.celery_app worker -Q default,scan`）
  - `web`（`next start`，服务端 rewrites 把 `/api` 代理到 `api:8000`）
  - 挂载 `./sample_media:/app/source:ro` 与命名卷 `clipmind-data:/app/data`；数据库用命名卷 `pgdata` 持久化。
- 技术栈骨架：前端 Next.js + React + TS + Tailwind + TanStack Query；后端 FastAPI + Pydantic + SQLAlchemy(async) + Alembic。

**数据模型（Alembic `0001_initial`，禁止删库重建；本轮不建 pgvector 扩展）**

- `SourceDirectory`、`Asset`、`ScanRun` 三张表及其枚举（`AssetStatus` / `ScanStatus` / `ScanRunStatus`）。
- `Asset` 唯一约束 `(source_directory_id, normalized_relative_path)`；`ScanRun` 部分唯一索引 `(source_directory_id) WHERE status IN ('queued','running')`。
- 时间统一 UTC、timezone-aware。

**API（PR-01）**

- `GET /health/live`、`GET /health/ready`
- `GET /api/system/status`
- `GET / POST /api/source-directories`、`GET / PUT /api/source-directories/{id}`
- `POST /api/source-directories/{id}/scan`、`GET /api/source-directories/{id}/status`
- `GET /api/assets`（分页 + 文件名搜索 + status 筛选）、`GET /api/assets/{id}`、`POST /api/assets/{id}/rescan`

**扫描流程（只读索引）**

- `POST scan` 在事务内建 `ScanRun(queued)` + 目录置 `queued` → 提交 → 入队 Celery → 写 `celery_task_id`。
- worker 取 PostgreSQL session 级 advisory lock（绑定单连接、跨多次 commit）执行。
- 分层变化检测：先 `size + mtime`，未变不读内容、不 probe；新增 / 变化才算 `quick_hash = sha256(size + 头 64KiB + 尾 64KiB)` + FFprobe。
- 缺失检测：基于 `last_seen_scan_id`，仅在完整成功后用 SQL 批量置 `source_missing`；失败 / 取消不标记。

**AI 接口骨架（仅文档与骨架，本轮不真实调用）**

- `clipmind_shared/ai/provider.py` 中的 `AIProvider` 接口与 `ProviderCapabilities` 定义，含能力探测项说明与降级策略说明。
- 预留环境键 `AI_*` / `EMBEDDING_*`（仅占位，不发起真实调用）。

**安全（最高优先级，PR-01 即落地）**

- 源目录只读挂载（`:ro`）；绝不修改 / 删除 / 移动 / 改名 / 覆盖源视频；无任何源删除 API。
- 白名单根 `ALLOWED_SOURCE_ROOTS=/app/source` + `os.path.realpath` 包含检查 + 软链逃逸防护；源目录只 `open(rb)`。
- 不提交视频 / 密钥；`.env` 被 git 忽略，仅提交 `.env.example`；API / web 默认仅绑 `127.0.0.1`、无鉴权、不公开。

### 6.2 PR-01 本轮不做（明确排除，留给后续 PR）

- **不做拆镜头与任何派生文件**（关键帧 / 缩略图 / 代理 / 片段裁剪）——属 PR-02。
- **不做真实 AI 调用**（不连 MiMo、不做画面描述 / 标签 / 能力探测真实执行）——PR-01 仅接口骨架与文档，真实调用在 PR-03。
- **不做人工审核流程**——属 PR-03。
- **不做检索 / 画面描述匹配 / 向量检索**——属 PR-04；本轮**不创建 pgvector 扩展**，pgvector 在 PR-04 用独立迁移启用。
- **不做脚本匹配与剪辑清单导出**——属 PR-05。
- **不启动** scheduler / beat、ai worker、media worker、export worker（compose 本轮只跑前述 6 个服务）。
- **不做素材上传**：PR-01 是**只读索引**，没有任何上传入口。
- **不做鉴权 / 公网暴露**：仅绑 `127.0.0.1`。
- **不做真实 NAS 生产部署**：当前仅本地 Docker Compose 开发环境。

---

## 7. 参考图与 PR 的对应关系

项目附带 4 张界面参考图，分别对应不同 PR 的目标形态。**参考图是设计意向，不代表 PR-01 已实现其全部细节。**

### 图二 → PR-01「素材统一管理」

对应 PR-01 的素材列表 / 目录管理界面。**重要：PR-01 与参考图存在如下差异，必须如实理解：**

- PR-01 是**只读索引**，**没有上传功能**（参考图里若出现上传入口，PR-01 不实现）。
- PR-01 **未实现列隐藏**（参考图里的列显示 / 隐藏控制，PR-01 不做）。
- PR-01 **不显示假状态**：界面状态必须来自真实 DB 数据（扫描状态 / 素材状态），不展示占位的假状态。

### 图一 → PR-01 / PR-02「拆镜头打标」

对应拆镜头与打标的界面形态。其中：

- 索引 / 镜头列表的基础框架属 PR-01；
- 拆镜头与镜头派生文件（关键帧 / 缩略图 / 代理 / 片段裁剪下载）属 PR-02，**已实现**；
- 「打标」中的 AI 画面描述 / 标签属 PR-03，**尚未实现**；PR-02 镜头详情中以占位文案（如「AI 内容分析将在 PR-03 提供」）说明，不显示伪造 AI 状态。

### 图三 → PR-05「脚本匹配」

对应脚本逐段匹配与剪辑清单导出的界面，属 PR-05。

### 图四 → PR-04「画面描述匹配」

对应按画面描述检索 / 匹配镜头的界面，属 PR-04（pgvector 在 PR-04 启用）。

---

## 8. 技术栈与部署速览（参考）

- **前端**：Next.js + React + TypeScript + Tailwind + TanStack Query。
- **后端**：FastAPI + Pydantic + SQLAlchemy(async) + Alembic。
- **数据库**：PostgreSQL（`pgvector` 预留，至 PR-04 才用独立迁移启用）。
- **异步**：Redis + Celery。
- **视频处理**：FFmpeg / FFprobe（提取、裁剪、转码派生文件，非生成式）。
- **部署**：Docker Compose（当前仅本地开发环境；服务全部跑在 Linux 容器）。
- **开发机**：Windows 11；git 2.53、Docker 29.4.3、Compose v5.1.3、Node 24、Python 3.13.2、FFmpeg / FFprobe 8.1.1。

---

## 9. 红线总结（务必遵守）

1. **不做任何生成式视频能力**（文生视频 / 图生视频 / 数字人 / 声音克隆 / 视频复刻 / 换人换物 / 自动成片）。
2. **源视频只读**：绝不修改 / 删除 / 移动 / 改名 / 覆盖；无源删除 API。
3. **DB 是事实来源**：界面不显示假状态。
4. **PR-01 只做只读索引**：无上传、无列隐藏、不建 pgvector 扩展、不真实调用 AI。
5. **不宣称已完成真实 NAS 生产部署**：当前仅本地 Docker Compose 开发环境。
