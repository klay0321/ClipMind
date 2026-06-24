# 本地开发指南（Local Development）

本文档描述如何在本地（Windows 11 开发机）拉起并开发 ClipMind。

ClipMind 是面向公司 NAS 部署的「AI 视频素材管理与智能匹配系统」：只读索引视频素材、用 FFmpeg 拆镜头与生成派生文件、调用外部 AI 理解打标、自然语言检索、画面/脚本匹配、剪辑清单导出。

> 注意：本文档描述的是**本地开发环境**。真实 NAS 部署尚未进行，本文不涉及生产部署。当前仓库处于 **PR-02（feat/shot-processing：拆镜头 + 派生文件）** 阶段（PR-01 已合并）：在只读素材索引之上，已实现 FFmpeg / PySceneDetect 拆镜头与派生文件（关键帧 / 缩略图 / 代理视频 / 片段裁剪下载）。**尚未实现 AI 理解打标、搜索、脚本匹配**（PR-03~05）。

## 能力边界（务必先读）

ClipMind **明确不做**以下事情，本文档与代码中的任何「生成」字样都**不是**生成式视频能力：

- 不做文生视频、图生视频、数字人、声音克隆、视频复刻、替换人物/产品、自动成片。
- 所谓「生成关键帧 / 缩略图 / 代理视频 / 片段」，指的是用 **FFmpeg 提取 / 裁剪 / 转码**派生文件，而**不是**生成式能力。

安全红线（最高优先级）：

- 源视频目录**只读挂载**（`:ro`），绝不修改 / 删除 / 移动 / 改名 / 覆盖源视频。
- 没有任何删除源文件的 API。
- 源目录只允许 `open(rb)` 读取。
- 不提交视频、密钥到仓库；`.env` 已被 git 忽略，仓库内只提交 `.env.example`。
- API / Web 默认只绑定 `127.0.0.1`，无鉴权，不对外暴露。

---

## 1. 前置依赖

所有服务都运行在 **Linux 容器**里，Windows 本机只需要 Docker 工具链即可拉起整套系统。前端/后端的本地（非容器）开发是可选的。

| 依赖 | 用途 | 参考版本（本项目验证环境） |
| --- | --- | --- |
| Docker Engine | 运行所有服务容器 | 29.4.3 |
| Docker Compose | 编排 7 个服务 | v5.1.3 |
| Git | 版本控制 | 2.53 |
| Node.js | （可选）前端本地开发 | 24 |
| Python | （可选）后端本地开发 | 3.13.2 |
| FFmpeg / FFprobe | 视频探测 + 拆镜头 / 派生文件（PR-02 在 media-worker 容器内使用） | 8.1.1 |

> **Windows 开发者只需安装 Docker + Compose（Docker Desktop 即可同时提供二者）。** 数据库（PostgreSQL）和 Redis 都跑在容器里，**无需在本机安装 PostgreSQL / Redis**。Node / Python / FFmpeg 仅在你想脱离容器、在本机直接跑前端或后端时才需要。

---

## 2. 快速开始

在**项目根目录**（包含 `compose.yml` 的目录）执行以下步骤。

### 2.1 准备环境变量

复制示例环境文件并按需修改：

```bash
cp .env.example .env
```

`.env` 已被 git 忽略，不会被提交。请勿把任何密钥写入 `.env.example`。

### 2.2 放入示例视频

把要索引的视频放入只读源目录 `sample_media/`：

```
sample_media/
  └── 你的示例视频.mp4
```

`sample_media/` 在容器内会被**只读挂载**为 `/app/source`。仓库**禁止提交视频文件**，该目录仅用于本地索引演示。

> 没有现成测试视频时，可用本机 ffmpeg 生成一段合成视频（如 `ffmpeg -f lavfi -i testsrc=duration=10:size=640x360:rate=25 sample_media/test.mp4`），用于本地拆镜头验证。**生成的视频同样禁止提交仓库。**

### 2.3 拉起全部服务

在项目根目录执行：

```bash
docker compose up -d
```

### 2.4 确认 7 个服务健康

```bash
docker compose ps
```

应当看到以下 **7 个服务**，关键服务（带 healthcheck 的）状态为 `healthy`：

| 服务 | 镜像 / 命令 | 说明 |
| --- | --- | --- |
| `postgres` | `pgvector/pgvector:pg16` | 数据库；数据持久化在命名卷 `pgdata`（**pgvector 扩展预留到 PR-04 才启用**） |
| `redis` | `redis:7-alpine` | Celery broker / backend |
| `migrate` | 一次性 `alembic upgrade head` | 跑完即退出（Exited 0 属正常） |
| `api` | `uvicorn`（绑定 `127.0.0.1`） | FastAPI，healthcheck=`/health/live` |
| `worker` | `celery -A clipmind_worker.celery_app worker -Q default,scan` | 扫描 worker |
| `media-worker` | `celery -A clipmind_worker.celery_app worker -Q media -c 1` | 拆镜头 / 派生 / 导出 worker（FFmpeg 重负载，默认并发 1，env `MEDIA_WORKER_CONCURRENCY` 可调） |
| `web` | `next start` | 前端，服务端 `rewrites` 把 `/api` 代理到 `api:8000` |

> `migrate` 是一次性任务，跑完 `alembic upgrade head` 后会退出，`docker compose ps` 里显示其为已退出状态属正常。当前**不启动** scheduler/beat、ai/export 等 worker（`media-worker` 已在 PR-02 启用）。

### 2.5 打开前端

浏览器访问：

```
http://localhost:3000
```

### 2.6 创建素材目录并扫描

在页面上创建一个素材目录（Source Directory），关键字段：

- `mount_path` 填**容器内逻辑路径**：`/app/source`（必须在白名单根 `ALLOWED_SOURCE_ROOTS=/app/source` 之下）。
- `read_only` 强制为 `true`。

创建后在页面上触发**扫描（Scan）**，扫描会发现 `sample_media/` 中的视频并入库。

### 2.7 对素材发起镜头分析（PR-02）

素材入库后，可对其发起拆镜头分析：

- **页面方式**：在素材库中对某个素材点「开始分析」，随后在「镜头库」`/shots` 查看产出的镜头；点单个镜头查看缩略图 / 关键帧 / 代理视频预览，并可导出片段下载。
- **API 方式**（同源走 web 的 `/api` 代理）：

  ```bash
  # 发起分析（{id} 为素材 id），入队 media 队列
  curl -X POST http://localhost:3000/api/assets/{id}/analyze-shots

  # 查看该素材的镜头
  curl "http://localhost:3000/api/shots?asset_id={id}"
  ```

> 镜头分析由 `media-worker` 消费 `media` 队列执行，派生文件写入命名卷 `clipmind-data:/app/data`，**不写源目录**。镜头详情中的 AI 内容分析为占位（「AI 内容分析将在 PR-03 提供」），PR-02 不调用 AI、不显示伪造状态。

---

## 3. 常用命令

均在项目根目录执行。

```bash
# 启动（后台）
docker compose up -d

# 查看服务状态
docker compose ps

# 查看日志（全部 / 指定服务，-f 跟随）
docker compose logs -f
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f media-worker

# 停止并移除容器（保留命名卷，即保留数据库与数据目录）
docker compose down

# 重启某个服务
docker compose restart api

# 进入某个容器执行命令
docker compose exec api sh
docker compose exec worker sh
docker compose exec media-worker sh
docker compose exec postgres psql -U postgres
```

> `docker compose down` **不会**删除命名卷 `pgdata` / `clipmind-data`，因此数据库和数据目录会保留。只有显式 `docker compose down -v` 才会删除卷——本项目数据模型**禁止删库重建**，请勿随意使用 `-v`。

---

## 4. 后端开发（apps/api、services/worker、packages/shared）

后端是 FastAPI + Pydantic + SQLAlchemy(async) + Alembic。可以在**容器内**或**本机 venv**中开发。

### 4.1 在容器内

```bash
# 应用数据库迁移（migrate 服务已自动跑过一次，按需手动重跑）
docker compose exec api alembic upgrade head

# 运行后端测试
docker compose exec api pytest

# 运行 ruff（lint）
docker compose exec api ruff check .
```

### 4.2 在本机 venv（可选）

需要本机 Python 3.13.2。数据库 / Redis 仍可继续使用容器（通过 `.env` 中的连接配置指向容器端口）。

```bash
# 进入后端目录
cd apps/api

# 创建并激活虚拟环境（Windows PowerShell）
python -m venv .venv
.venv\Scripts\Activate.ps1

# 安装依赖（按 apps/api 的依赖声明）
pip install -e .

# 迁移 / 测试 / lint
alembic upgrade head
pytest
ruff check .
```

> Alembic 初始迁移为 `0001_initial`，**禁止删库重建**；该迁移**不创建 pgvector 扩展**（pgvector 预留到 PR-04 用独立迁移启用）。

---

## 5. 前端开发（apps/web）

前端是 Next.js + React + TypeScript + Tailwind + TanStack Query。

### 5.1 在容器内

```bash
docker compose exec web npm run dev
docker compose exec web npm run lint
docker compose exec web npm run typecheck
docker compose exec web npm run test
docker compose exec web npm run build
```

### 5.2 在本机（可选）

需要本机 Node 24。

```bash
cd apps/web

npm install

npm run dev        # 本地开发服务器
npm run lint       # ESLint
npm run typecheck  # TypeScript 类型检查
npm run test       # 前端测试
npm run build      # 生产构建
```

> 前端通过 Next.js 服务端 `rewrites` 把 `/api` 代理到容器内的 `api:8000`，因此浏览器始终走**同源** `/api`，不直接访问后端端口（见第 7 节端到端验证）。

---

## 6. 只跑后端测试 / 只跑前端测试

**只跑后端测试：**

```bash
# 容器内
docker compose exec api pytest

# 或本机 venv
cd apps/api && pytest
```

**只跑前端测试：**

```bash
# 容器内
docker compose exec web npm run test

# 或本机
cd apps/web && npm run test
```

---

## 7. 端到端验证步骤

以下步骤验证 PR-01 的核心契约：只读安全、扫描幂等、数据持久化、同源访问。

### 7.1 验证只读挂载（写入应报错）

源目录被 `:ro` 挂载，任何写入都应失败：

```bash
docker compose exec api sh -c "touch /app/source/should_fail.txt"
```

预期：报错（Read-only file system 之类），**无法**在源目录创建文件。这印证了「绝不修改源视频」的安全约束。

### 7.2 验证扫描幂等 / 新增 / 修改 / 缺失

通过页面或 API 多次触发扫描，观察 `ScanRun` 的统计字段（`files_discovered/new/modified/missing/errored`）：

1. **幂等**：内容不变时再次扫描，`new`/`modified` 应为 0（变化检测先比较 `size + mtime`，未变则不读内容、不 FFprobe）。
2. **新增**：往 `sample_media/` 放入一个新视频后扫描，`new` 增加。
3. **修改**：替换某个视频内容（导致 `size` 或 `mtime` 变化）后扫描，`modified` 增加（此时才会重算 `quick_hash` 并 FFprobe）。
4. **缺失**：删除 `sample_media/` 中某个视频后扫描，**完整成功**的扫描结束后，缺失资产会被批量置为 `source_missing`（基于 `last_seen_scan_id`；扫描失败或取消时不标记）。

> 说明：删除发生在你本机的 `sample_media/` 目录（源在本机、容器只读读取），ClipMind **不会**、也**没有 API** 去删除源文件。

### 7.3 验证重启后数据保留

```bash
docker compose down
docker compose up -d
docker compose ps
```

预期：数据库（命名卷 `pgdata`）与数据目录（命名卷 `clipmind-data`）保留，之前创建的素材目录与已索引资产仍在。

### 7.4 验证同源 /api 访问、不暴露 api:8000

```bash
# 同源访问（经 web 的 rewrites 代理到 api:8000），应可用
curl http://localhost:3000/api/system/status

# 后端端口不对外暴露：api 绑定 127.0.0.1 且不通过 web 暴露给外部
# 浏览器/外部不应直接以 http://<本机外网IP>:8000 访问到 api
```

预期：业务请求统一走 `http://localhost:3000/api/...`（同源），后端 `api:8000` 仅在 Compose 内网与本机回环可达，不对外暴露。

---

## 8. Windows 开发注意事项

- **所有服务都运行在 Linux 容器内**，不是 Windows 进程。容器内一切按 Linux 语义运行。
- **路径用容器内逻辑路径**：素材目录的 `mount_path` 必须填容器内路径 `/app/source`，**不要**填 Windows 路径（如 `C:\...`）。`/app/source` 由 Compose 把本机的 `./sample_media` 只读挂载而来。
- 白名单根为 `ALLOWED_SOURCE_ROOTS=/app/source`，结合 `os.path.realpath` 包含检查与软链逃逸防护，确保不会越出该根目录。
- **无需在本机安装 PostgreSQL / Redis**：二者都由 Compose 以容器形式提供。Windows 下**用 `docker compose` 即可**拉起整套系统。
- 行尾与文件编码：若在本机编辑被容器挂载的脚本，注意保持 LF 行尾，避免 Windows CRLF 影响容器内执行。

---

## 9. 目录结构速览（monorepo）

```
.
├── compose.yml            # 根编排文件（7 个服务）
├── .env.example           # 环境变量示例（.env 被 git 忽略）
├── apps/
│   ├── web/               # Next.js 前端
│   └── api/               # FastAPI 后端
├── services/
│   └── worker/            # Celery worker（包名 clipmind_worker）
├── packages/
│   └── shared/            # 共享代码（包名 clipmind_shared，含 ai/provider.py 接口骨架）
├── infra/                 # api / worker / web 三个 Dockerfile
├── docs/                  # 文档（含本文件）
├── scripts/               # 脚本
└── sample_media/          # 只读源目录（禁止提交视频）
```

挂载关系：`./sample_media:/app/source:ro`、命名卷 `clipmind-data:/app/data`、命名卷 `pgdata` 持久化数据库。
