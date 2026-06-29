# ClipMind

AI 视频素材管理、镜头拆解、智能匹配与剪辑清单工具。

ClipMind 把公司 NAS 里**分散、难检索、难理解**的原始视频，转换为**结构化、可搜索、可匹配、可审核、可下载**的镜头资产库：只读索引素材、自动拆镜头与派生文件、调用外部 AI 理解打标、语义 / 混合检索、画面与脚本匹配、生成剪辑清单与导出片段包。

> **ClipMind 不做生成式视频**（文生视频、图生视频、数字人、声音克隆、视频复刻、自动成片）。
> 文档中"生成关键帧 / 缩略图 / 代理视频 / 片段"一律指**用 FFmpeg 从原始视频提取、裁剪或转码派生文件**，不是生成能力。
>
> 完整需求见 [docs/PRODUCT_REQUIREMENTS.md](docs/PRODUCT_REQUIREMENTS.md)（最高事实来源）。

---

## 1. 产品用途

ClipMind 面向短视频运营与剪辑团队，解决以下痛点：

- **视频素材分散**：素材散落在 NAS 各目录，靠文件名和记忆管理，越积越难找。
- **长视频查找镜头困难**：想用某个产品 / 动作 / 场景镜头，要逐个打开视频翻看。
- **人工拆镜头和打标签成本高**：剪辑前手工拆分镜头、截图、整理标签，准备周期长。
- **根据文案找画面困难**：脚本写完，难判断现有素材能否支撑每一段文案。
- **剪辑清单需要人工整理**：每段用哪个镜头、起止时间码，要人工拉表。
- **导出镜头片段和素材包效率低**：挑好镜头后还要手动裁剪、命名、打包。

---

## 2. 核心流程

```
导入视频（NAS 目录扫描 / 网页上传）
  → AI 自动拆镜头（PySceneDetect 内容检测 + 固定切分兜底）
  → 关键帧与代理视频（FFmpeg 派生缩略图 / 关键帧 / 低码率代理）
  → AI 分析与人工确认（外部 AI 打标 → 人工审核确认 / 修改 / 拒绝）
  → 语义索引（multilingual-e5-small 向量化，pgvector）
  → 搜索或画面描述匹配（关键词 / 语义 / 混合 + 多条件筛选）
  → 脚本拆段与镜头推荐（脚本拆段 → 逐段候选镜头）
  → 选择和锁定（人工挑选 / 锁定，重新匹配不覆盖锁定）
  → 导出剪辑清单与视频包（多格式清单 + 片段 ZIP）
```

各环节均**以 PostgreSQL 为事实来源**；原始素材**全程只读**，绝不被修改 / 改名 / 删除。

---

## 3. 当前完整功能

### 素材管理
- 网页上传视频（独立可写上传区，不污染只读源）
- NAS 目录扫描 / 重扫（只读索引，增量发现）
- 视频检测（FFprobe 提取时长 / 分辨率 / 编码等元数据）
- 自动拆镜头（可替换检测器：PySceneDetect 主 + 固定切分兜底）
- 关键帧（主关键帧 + 均匀采样关键帧条）
- 代理视频（低码率可播放代理，支持 HTTP Range 拖动）
- 处理状态可视化（扫描 / 拆镜头 / 派生 / AI 各阶段状态）
- 失败重试（拆镜头分析、AI 分析均可重试）

### AI 镜头拆解
- AI 自动分析每个镜头：产品、场景、动作、镜头类型、营销用途、风险、画面描述
- 人工审核：确认 / 修改 / 拒绝 / 标记无法确认 / 重新打开（带审计事件与乐观锁）
- 最终可搜索结果以"人工确认 > AI 原始"的有效结果为准
- 真实镜头下载（按时间码 FFmpeg 导出片段）
- 重新分析采用**原子代次替换**（旧镜头在新分析完整成功前持续可用）

### 智能匹配
- 关键词搜索 / 语义搜索 / 混合搜索（向量 + 词法 + 标签 + 产品融合）
- 按产品 / 场景 / 动作 / 镜头类型 / 营销用途 / 风险 / 审核状态筛选
- 画面描述匹配（输入一段画面需求，返回最相符镜头）
- 匹配度、推荐理由、不匹配项、风险提示（均来自真实检索，不伪造）
- Saved Search（保存搜索条件，一键重跑并恢复表单）
- 检索索引状态可见；未配置 / 降级时如实提示词法降级

### 脚本剪辑
- 脚本创建与导入（粘贴文本，或上传 .txt / .md）
- AI 拆段（有 AI 用 AI 拆段，否则规则拆段）
- 每段可加场景 / 动作 / 镜头类型 / 营销用途约束、负向词、排除风险
- 镜头候选（逐段候选，支持多代次历史）
- 选择和锁定（人工挑选 / 锁定，锁定段重匹配时不被覆盖）
- 单段重匹配（生成新一代候选）
- 缺口（无合适镜头的段显示缺口原因，不编造素材）
- 补拍建议（缺口段给出可操作提示）
- 剪辑清单（每段镜头、时间码、建议入出点、时长分配汇总）

### 导出
- MP4 镜头片段（按时间码裁剪，默认重编码）
- 剪辑清单多格式：CSV / XLSX / JSON / Markdown / Printable HTML
- Bundle ZIP（多选镜头打包：`clips/` + `manifest.json` + 剪辑清单）
- Export Center（集中查看片段 / 脚本清单 / 打包三类导出）
- Retry（失败导出重试）、Delete（删除导出记录与派生文件，**不碰源视频**）
- Download Log（导出下载记录）

### 组织能力
- Project（项目）：聚合素材 / 镜头 / 产品 / 脚本 / 集合
- 成员：Asset、Shot、Product、Script 可加入项目
- 静态 Collection（手工挑选的镜头集合）
- Dynamic Collection（按搜索条件实时计算的镜头集合）
- Favorite（收藏镜头 / 素材 / 搜索结果 / 脚本匹配结果，多态）
- Saved Search（保存的搜索）
- 归档与恢复（项目归档后只读，恢复后可继续编辑）

> **当前不含**：应用级登录 / 权限（见 §10 安全限制）。前端不显示任何伪造的 AI 状态或匹配结果。

---

## 4. 页面入口

| 路由 | 用途 |
|---|---|
| [`/assets`](apps/web/app/assets) | 素材管理：上传 / 扫描 / 查看索引视频，触发拆镜头与 AI 分析 |
| [`/shots`](apps/web/app/shots) | AI 镜头拆解：镜头网格 + 详情 + 代理播放 + 关键帧 + 人工审核 + 快速下载 |
| [`/search`](apps/web/app/search) | 智能匹配工作台：语义 / 关键词 / 混合搜索 + 画面描述匹配 + Saved Search |
| [`/script`](apps/web/app/script) | 脚本剪辑：脚本列表 / 工作台（拆段 → 候选 → 选择锁定 → 剪辑清单 → 多格式导出） |
| [`/products`](apps/web/app/products) | 产品库：维护产品，查看产品的素材 / 镜头绑定统计 |
| [`/projects`](apps/web/app/projects) | 项目：聚合素材 / 镜头 / 产品 / 脚本 / 集合，含静态与动态集合、归档恢复 |
| [`/exports`](apps/web/app/exports) | 导出中心：集中查看 / 下载 / 重试 / 删除所有导出 |
| [`/favorites`](apps/web/app/favorites) | 收藏：按类型筛选收藏的镜头 / 素材 / 搜索结果 / 脚本匹配结果 |

> 顶部导航：素材管理 · AI 镜头拆解 · 智能匹配 · 脚本剪辑 · 项目 · 导出；产品库与收藏在"更多"菜单。
> 另有详情路由：`/shots/[id]`、`/script/[scriptId]`、`/projects/[projectId]`、`/collections/[collectionId]`。

---

## 5. 技术架构

```
浏览器 ──同源 /api──> Next.js(web) ──服务端代理──> FastAPI(api) ──> PostgreSQL(+pgvector)
                                                     │                       ▲ 派生路径 / 状态 / 索引
                                                     └─入队─> Redis ──> Celery workers ──> FFmpeg / 外部 AI / E5
```

- **前端**：Next.js + React + TypeScript + Tailwind CSS + TanStack Query
- **后端**：FastAPI + Pydantic + SQLAlchemy(async) + Alembic（当前迁移 head：`0012_library_export_features`）
- **数据库**：PostgreSQL 16 + **pgvector**（`vector(384)` 语义检索）+ pg_trgm
- **异步任务**：Redis + **Celery**（worker=default/scan、media-worker=media、ai-worker=ai、search-worker=search、export-worker=export）
- **视频处理**：FFmpeg / FFprobe + PySceneDetect（`opencv-python-headless` 后端）
- **AI 理解**：外部 Provider（小米 **MiMo**，OpenAI 兼容；可留空 = 不打标）
- **语义检索**：内置 `embedder` 微服务（**multilingual-e5-small**，384 维，纯 CPU 可用）
- **部署**：Docker + Docker Compose（NAS 生产 compose 共 11 个服务）

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 6. 快速启动

前置：Docker + Docker Compose v2。

**本地开发**（`compose.yml`，源目录默认指向 `sample_media/`）：

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps          # 等待服务 healthy
# 打开 http://localhost:3000
```

> 内置语义检索需要 `embedder`（profile `embedding`）：`docker compose --profile embedding up -d embedder`。

**NAS / 生产环境**（`docker-compose.nas.yml` + 运维脚本）：

```bash
cp .env.nas.example .env
# 按 docs/NAS_DEPLOYMENT.md 与 docs/CONFIGURATION.md 修改 .env（至少改素材目录、数据盘、绑定地址、口令）
bash scripts/nas/install.sh    # 校验 .env → 建目录 → 构建 → 迁移 → 启动 → 就绪检查
```

部署前请先阅读：

- [docs/NAS_DEPLOYMENT.md](docs/NAS_DEPLOYMENT.md)
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md)

---

## 7. 配置说明

配置通过仓库根 `.env` 提供（已被 git 忽略，仅提交 `.env.example` 与 `.env.nas.example` 两个**不含秘密**的模板）。
每个变量的用途、是否必填、是否敏感、安全默认值与修改场景见：

- [docs/CONFIGURATION.md](docs/CONFIGURATION.md)

**绝不**把真实密钥 / 数据库口令 / MiMo 端点 / NAS 凭据 / 本机 `.env` 写入仓库或文档。

---

## 8. 数据持久化

NAS 部署下所有持久化数据落在 `${CLIPMIND_DATA_ROOT}` 下的子目录：

| 子目录 | 内容 |
|---|---|
| `pgdata/` | PostgreSQL 数据（含语义向量索引） |
| `redis/` | Redis AOF（任务队列 / 状态） |
| `data/` | 派生文件：关键帧 / 缩略图 / 代理视频 / 导出片段 / 剪辑清单 / 打包 ZIP |
| `uploads/` | 网页上传的原始视频（独立于只读 NAS 源） |
| `models/` | embedder 模型缓存（E5 首次下载后持久化） |
| `backups/` | 备份产物（`backup.sh` 写入） |

原始素材在 `${CLIPMIND_SOURCE_DIR}`，**只读挂载**到容器内 `/app/source`，系统绝不写入。

---

## 9. 更新与运维

NAS 运维脚本（`scripts/nas/`）：

| 脚本 | 用途 |
|---|---|
| [`start.sh`](scripts/nas/start.sh) | 启动全部服务 |
| [`stop.sh`](scripts/nas/stop.sh) | 停止（保留数据卷，**绝不** `down -v`） |
| [`restart.sh`](scripts/nas/restart.sh) | 重启（不重建、不迁移、不删数据） |
| [`update.sh`](scripts/nas/update.sh) | 升级：**先自动备份** → 重建 → 迁移 → 滚动重启 |
| [`healthcheck.sh`](scripts/nas/healthcheck.sh) | 就绪检查（API `/health/ready`） |
| [`logs.sh`](scripts/nas/logs.sh) | 查看日志 `logs.sh [服务名]` |
| [`backup.sh`](scripts/nas/backup.sh) | 备份（DB + 配置；`--with-data` 含派生数据） |
| [`restore.sh`](scripts/nas/restore.sh) | 恢复（需显式 `RESTORE` 确认，破坏性） |

> **禁止随意执行 `docker compose down -v`**：会删除数据库与所有派生数据卷。任何运维脚本都不会执行它。
> 数据库变更一律走 Alembic 迁移，绝不删库重建。

---

## 10. 安全限制

- **当前没有应用级登录 / 权限**。
- 仅建议在**可信内网、VPN 或受控反向代理（+HTTPS + 访问控制）**之后访问；**不允许裸露公网**。
- 默认端口仅绑定 `127.0.0.1`（NAS 经 `CLIPMIND_BIND_ADDR` 显式放开内网）。
- **`.env` 不得提交**；真实密钥 / 口令只存在于本机 `.env`。
- **原始素材目录只读**；路径经白名单 + `realpath` 包含检查 + 软链逃逸防护。
- **删除导出不会删除源视频**（只删派生文件与导出记录）。
- **老板私密交付包绝不上传 GitHub / 公开网盘**（含真实 `.env`，只通过安全渠道传输）。

---

## 11. 支持范围

- **x86_64（amd64）Docker NAS：已验证**。
- **ARM64：尚未验证**（embedder 的 torch 等依赖在 arm64 上可能需自行调整，本包不作可用性承诺）。
- 实际 NAS 需要 **Docker + Docker Compose v2**。
- **首次启动**需拉取镜像并下载 E5 模型（需出网），之后离线可用。
- 导出支持 **Retry / Delete**；**暂无**运行中 Cancel 与自动 TTL 清理。

---

## 12. 测试与验收

测试规模（按当前分支源码统计）：

| 范围 | 数量 |
|---|---|
| 后端测试（pytest） | 57 个测试文件 / 480 个测试函数 / **502 个收集用例** |
| 前端测试（Vitest） | 31 个测试文件 / 239 个用例 |
| UI E2E（Playwright） | 6 个 spec / 24 个用例（5 个 spec 入 CI；`real-provider.spec.ts` 为真实 Provider 门控，CI 不跑） |
| Docker 端到端场景脚本 | 9 个（`scripts/ci_*_e2e.py`） |
| CI 任务 | 5 个：`backend`、`frontend`、`compose-config`、`docker-e2e`、`ui-e2e`（`.github/workflows/ci.yml`） |

两层验收制度（详见 [docs/REAL_MEDIA_ACCEPTANCE.md](docs/REAL_MEDIA_ACCEPTANCE.md)）：

- **A 层 自动回归（CI）**：用 Fake Provider / Fake Embedding + FFmpeg 合成视频，验证 API 契约、数据流、迁移、UI 流程与重启持久化。**不证明** AI 真懂内容。
- **B 层 真实业务验收（本地，提交前）**：用**真实 MiMo**、**真实 E5**、**真实视频**与真实脚本人工抽检；并验证**最终 tarball 独立生产栈**起栈与 **backup/restore** 一致性。证据仅本地保存（`.local/`，绝不提交）。

---

## 13. 文档索引

| 文档 | 面向 |
|---|---|
| [docs/BOSS_QUICKSTART.md](docs/BOSS_QUICKSTART.md) | 业务负责人快速上手（非技术） |
| [docs/NAS_DEPLOYMENT.md](docs/NAS_DEPLOYMENT.md) | NAS 管理员部署 / 运维 |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | 环境变量逐项说明 |
| [docs/DEMO_ACCEPTANCE_CHECKLIST.md](docs/DEMO_ACCEPTANCE_CHECKLIST.md) | 演示验收清单 |
| [docs/DATABASE_UPGRADE.md](docs/DATABASE_UPGRADE.md) | 数据库迁移 / 升级 |
| [docs/SCRIPT_MATCHING.md](docs/SCRIPT_MATCHING.md) | 脚本拆段与镜头匹配逻辑 |
| [docs/REAL_MEDIA_ACCEPTANCE.md](docs/REAL_MEDIA_ACCEPTANCE.md) | 真实素材验收制度 |
| [docs/PRODUCT_REQUIREMENTS.md](docs/PRODUCT_REQUIREMENTS.md) | 完整需求规格（最高事实来源） |

更多专题见 [docs/](docs/)（架构、语义检索、AI 方案、Docker 网络等）。开发约定见 [CLAUDE.md](CLAUDE.md)。
