# ClipMind 配置说明（环境变量参考）

本文件逐项说明 ClipMind 的环境变量：用途、是否必填、是否敏感、安全默认值、示例格式与修改场景。
**面向部署/运维人员**；业务负责人请看 [BOSS_QUICKSTART.md](BOSS_QUICKSTART.md)，NAS 部署流程请看 [NAS_DEPLOYMENT.md](NAS_DEPLOYMENT.md)。

> 配置载体是仓库根的 `.env` 文件。复制模板后修改：
> - 本地开发：`cp .env.example .env`（配合 `compose.yml`）
> - NAS / 生产：`cp .env.nas.example .env`（配合 `docker-compose.nas.yml`）
>
> **`.env` 已被 git 忽略，绝不提交真实密钥 / 密码 / NAS 凭据 / 内网地址。** 仓库内只提交不含秘密的
> `.env.example` 与 `.env.nas.example` 两个模板。本文档中所有"示例"均为占位符（如 `CHANGE_ME`、
> `your-api-key`、`https://example.invalid`、`192.168.1.100`），**不是真实值**。

## 阅读约定

每个变量标注：

- **必填**：是 / 否（"否"通常表示留空有安全默认，或留空即关闭该能力）。
- **敏感**：是 / 否（敏感=口令/密钥/凭据，绝不进仓库、日志、镜像、交付公开包）。
- **默认**：模板中的安全默认值。
- **示例 / 用途 / 修改场景 / NAS 注意**：分别给出占位示例、作用、何时需要改、以及 NAS 上的特别提示。

---

## 1. 部署路径与网络绑定

NAS 部署最关键的一组，决定数据落在哪块盘、只读索引哪个素材目录、对谁开放端口。仅出现在 `docker-compose.nas.yml`（`.env.nas.example`）。

### `CLIPMIND_DATA_ROOT`
- **必填**：是（NAS）　**敏感**：否　**默认**：`./clipmind-data`
- **示例**：`/share/clipmind`
- **用途**：所有持久化数据的根目录（PostgreSQL、Redis、派生文件、上传、模型缓存、备份都落在它下面的子目录）。
- **修改场景**：几乎总要改成 NAS 上的**大容量可写磁盘**路径。
- **NAS 注意**：不要硬编码厂商专属路径；按你的 NAS 实际可写大盘填（如 `/share/clipmind`、`/mnt/data/clipmind`）。磁盘要够大（派生文件与数据库会持续增长）。

### `CLIPMIND_SOURCE_DIR`
- **必填**：是（NAS）　**敏感**：否　**默认**：`/please/set/your/nas/media/dir`（故意的占位，强制你显式设置）
- **示例**：`/share/video-assets`
- **用途**：NAS 原始素材目录，**只读**挂载到容器内 `/app/source`。系统只读取，**绝不**写入 / 改名 / 删除源文件。
- **修改场景**：必改为你的真实素材目录。
- **NAS 注意**：保持默认占位会导致启动报错（这是有意的防呆）。该目录以只读方式挂载，是最高优先级安全约束。

### `CLIPMIND_BIND_ADDR`
- **必填**：否　**敏感**：否　**默认**：`127.0.0.1`（仅本机）
- **示例**：`192.168.1.100`
- **用途**：宿主机端口绑定地址。决定谁能访问 Web / API。
- **修改场景**：要让内网其他机器访问，设为 NAS 内网网卡 IP；或 `0.0.0.0`（监听所有网卡）。
- **NAS 注意**：**本系统无应用级登录鉴权**。设为 `0.0.0.0` 或公网可达地址前，必须先置于可信内网 / VPN / 反向代理之后，**切勿裸露公网**。

### `API_PORT`
- **必填**：否　**敏感**：否　**默认**：`8000`
- **示例**：`8000`
- **用途**：API 对宿主机暴露的端口（`${CLIPMIND_BIND_ADDR}:${API_PORT}` → 容器 8000）。
- **修改场景**：端口冲突时改。
- **NAS 注意**：浏览器实际只需访问 Web 端口；API 端口主要供排查与健康检查。

### `WEB_PORT`
- **必填**：否　**敏感**：否　**默认**：`3000`
- **示例**：`3000`
- **用途**：前端 Web 对宿主机暴露的端口；用户浏览器访问 `http://<bind-addr>:<WEB_PORT>`。
- **修改场景**：端口冲突，或反向代理要求特定端口时改。
- **NAS 注意**：把该地址告知业务使用者即可。

---

## 2. PostgreSQL 数据库

> **一致性铁律**：`POSTGRES_PASSWORD` 与 `DATABASE_URL` 中内嵌的密码**必须完全一致**，否则 API / worker / 迁移全部连不上库。

### `POSTGRES_USER`
- **必填**：否　**敏感**：否　**默认**：`clipmind`
- **示例**：`clipmind`
- **用途**：PostgreSQL 用户名（容器首次初始化时创建）。
- **修改场景**：一般无需改；改了须同步改 `DATABASE_URL`。
- **NAS 注意**：首次启动后再改用户名需重建数据库卷，不建议。

### `POSTGRES_PASSWORD`
- **必填**：是　**敏感**：**是**　**默认**：`CHANGE_ME_TO_A_STRONG_PASSWORD`（占位，必须改）
- **示例**：`CHANGE_ME`（请生成强随机口令）
- **用途**：PostgreSQL 口令。
- **修改场景**：**部署前必改为强随机口令**，并同步写入 `DATABASE_URL`。
- **NAS 注意**：`install.sh` 会拒绝仍为 `CHANGE_ME...` 的占位口令。绝不提交、绝不写入日志。

### `POSTGRES_DB`
- **必填**：否　**敏感**：否　**默认**：`clipmind`
- **示例**：`clipmind`
- **用途**：数据库名（容器首次初始化时创建）。
- **修改场景**：一般无需改；改了须同步改 `DATABASE_URL`。

### `DATABASE_URL`
- **必填**：是　**敏感**：**是**（内嵌口令）　**默认**：`postgresql+asyncpg://clipmind:CHANGE_ME_TO_A_STRONG_PASSWORD@postgres:5432/clipmind`
- **示例**：`postgresql+asyncpg://clipmind:CHANGE_ME@postgres:5432/clipmind`
- **用途**：应用连接串。API 用 async 驱动（`asyncpg`）；同步驱动（Alembic / 部分 worker）由代码从此串自动派生。
- **修改场景**：改用户名 / 口令 / 库名 / 主机时同步改。容器内主机名固定为服务名 `postgres`、端口 `5432`。
- **NAS 注意**：口令必须与 `POSTGRES_PASSWORD` 一致；主机请保持 `postgres`（容器服务名），勿写本机 IP。

---

## 3. Redis / Celery（异步任务）

容器内通过服务名 `redis` 互访；同一 Redis 不同 DB 编号区分用途。一般无需改。

### `REDIS_URL`
- **必填**：否　**敏感**：否　**默认**：`redis://redis:6379/0`
- **用途**：应用缓存 / 轻量状态。
- **修改场景**：仅当改用外部 Redis 时。

### `CELERY_BROKER_URL`
- **必填**：否　**敏感**：否　**默认**：`redis://redis:6379/1`
- **用途**：Celery 任务队列 broker（扫描 / 拆镜头 / AI / 检索 / 导出任务排队）。

### `CELERY_RESULT_BACKEND`
- **必填**：否　**敏感**：否　**默认**：`redis://redis:6379/2`
- **用途**：Celery 任务结果存储。
- **NAS 注意**：以上三项保持服务名 `redis`、按默认 DB 编号即可；改外部 Redis 时三者一并改。

---

## 4. AI 理解 Provider（ai-worker）

为镜头生成画面描述、产品 / 场景 / 动作 / 镜头类型 / 营销用途 / 风险标签。**留空 = 不调用任何 AI**（拆镜头 / 派生 / 检索仍可用，但不产出 AI 描述与标签）。真实密钥**只**写入本机 `.env`。

### `AI_PROVIDER`
- **必填**：否（留空=不启用 AI）　**敏感**：否　**默认**：空
- **取值**：空=未配置（NotConfigured，绝不联网、不产假结果）；`fake`=确定性假 Provider（仅测试 / CI，不联网）；`mimo`=小米 MiMo（OpenAI 兼容）。
- **示例**：`mimo`
- **用途**：选择 AI 实现。
- **修改场景**：要真实打标时设为 `mimo` 并填好下面三项。
- **NAS 注意**：生产环境**绝不要**用 `fake`（会产出假标签）；要么 `mimo`，要么留空。

### `AI_BASE_URL`
- **必填**：`AI_PROVIDER=mimo` 时必填　**敏感**：否（端点地址本身一般不算秘密，但**勿把真实内网端点提交仓库**）　**默认**：空
- **示例**：`https://example.invalid/v1`
- **用途**：AI Provider 的 OpenAI 兼容端点基址。
- **NAS 注意**：容器需能访问该端点；若为内网端点且容器内不可达（宿主机却可达），见 `CLIPMIND_DOCKER_SUBNET` 与 [DOCKER_AI_NETWORKING.md](DOCKER_AI_NETWORKING.md)。

### `AI_API_KEY`
- **必填**：`AI_PROVIDER=mimo` 时必填　**敏感**：**是**　**默认**：空
- **示例**：`your-api-key`
- **用途**：调用 AI Provider 的密钥。
- **NAS 注意**：绝不提交仓库 / 日志 / 公开交付包；只存在于本机 `.env` 与老板私密交付包的 `private/.env`。

### `AI_MODEL`
- **必填**：`AI_PROVIDER=mimo` 时必填　**敏感**：否　**默认**：空
- **示例**：`mimo-v2.5`（视觉打标）
- **用途**：视觉理解所用模型名。
- **NAS 注意**：视觉打标需选支持图片输入的模型；纯文本端点（如解析）可另配，见第 5、6 节。

### `AI_API_KEY_HEADER`
- **必填**：否　**敏感**：否　**默认**：空
- **示例**：`api-key`
- **用途**：鉴权头名。留空=标准 `Authorization: Bearer <key>`；某些端点用自定义头（如 `api-key`，类 Azure 风格）。
- **修改场景**：Provider 要求非标准鉴权头时填。

### 其余 AI 调参（非敏感，一般用默认）

| 变量 | 默认 | 用途 |
|---|---|---|
| `AI_MAX_IMAGES` | `4` | 每次调用最多发送的关键帧数 |
| `AI_TIMEOUT` | `60` | 单次 AI 请求超时（秒） |
| `AI_RETRIES` | `2` | 失败重试次数 |
| `AI_PROMPT_VERSION` | `v1` | Prompt 版本标识（便于追溯） |
| `AI_WORKER_CONCURRENCY` | `2` | ai-worker 并发 |
| `AI_MAX_COMPLETION_TOKENS` | `0` | >0 时随请求发送 `max_completion_tokens`（0=不设） |
| `AI_PRICE_INPUT_PER_1K` / `AI_PRICE_OUTPUT_PER_1K` | `0` | 每 1K token 计价（用于成本统计；未知留 0 只记 token 数） |

---

## 5. 语义检索 / Embedding

把镜头描述向量化以支持语义 / 混合搜索与画面描述匹配。**默认启用内置 `embedder` 微服务**（多语 `multilingual-e5-small`，纯 CPU 可用），首次构建会下载模型并持久化到 `${CLIPMIND_DATA_ROOT}/models`。

### `EMBEDDING_PROVIDER`
- **必填**：否　**敏感**：否　**默认**：`.env.nas.example` 为 `openai_compatible`；`.env.example` 为空
- **取值**：空=未配置（仅构建检索文本、不嵌入，索引标 `degraded`，搜索降级为词法 / 结构化）；`fake`=确定性假向量（CI / 降级验证，不联网、不下载模型）；`openai_compatible`=OpenAI 兼容 `/embeddings`（内置 embedder 或外部端点）。
- **示例**：`openai_compatible`
- **NAS 注意**：生产保持 `openai_compatible` + 内置 `embedder` 即可获得真实语义检索。

### `EMBEDDING_BASE_URL`
- **必填**：`openai_compatible` 时必填　**敏感**：否　**默认**：`http://embedder:8100`
- **示例**：`http://embedder:8100`
- **用途**：embedding 服务地址。容器内用服务名 `embedder`。
- **修改场景**：改用外部 embedding 端点时填外部地址。

### `EMBEDDING_API_KEY`
- **必填**：否（内置 embedder 无需）　**敏感**：**是**（用外部端点时）　**默认**：空
- **示例**：`your-api-key`
- **用途**：外部 embedding 端点的密钥；内置 `embedder` 留空。

### `EMBEDDING_MODEL`
- **必填**：否　**敏感**：否　**默认**：`intfloat/multilingual-e5-small`
- **用途**：embedding 模型名（多语，384 维）。
- **NAS 注意**：须与内置 `embedder` 的 `EMBEDDER_MODEL` 一致；换模型通常要改维度并全量重嵌。

### `EMBEDDING_MODEL_REVISION`
- **必填**：否　**敏感**：否　**默认**：`614241f622f53c4eeff9890bdc4f31cfecc418b3`（不可变 commit SHA，公开模型 revision，非敏感）
- **用途**：钉死模型版本，保证向量可复现。
- **修改场景**：升级模型版本时改，并须全量重嵌；须与 `EMBEDDER_MODEL_REVISION` 一致。
- **NAS 注意**：默认开启 `EMBEDDING_REQUIRE_PINNED_REVISION=true`，若设为空 / `main` / `latest` / `head` 会 fail-closed（不嵌入、向量降级，但镜头仍可被词法 / 标签 / 产品检索到）。

### `EMBEDDING_DIMENSION`
- **必填**：否　**敏感**：否　**默认**：`384`
- **用途**：向量维度，**必须与数据库 `vector` 列维度一致**（迁移 `0007` 为 `vector(384)`）。
- **修改场景**：换不同维度的模型时改；改维度需新建 Alembic 迁移，不能直接改。

### 其余检索 / Embedding 调参（非敏感，一般用默认）

| 变量 | 默认 | 用途 |
|---|---|---|
| `EMBEDDING_REQUIRE_PINNED_REVISION` | `true` | 要求钉死 revision；未钉死则 fail-closed 降级 |
| `EMBEDDING_TIMEOUT` | `30` | embedding 请求超时（秒） |
| `EMBEDDING_PREFIX_SCHEME` | `e5` | e5 前缀方案（查询加 `query:`、文档加 `passage:`）；可设 `none` |
| `SEARCH_WORKER_CONCURRENCY` | `2` | search-worker 并发 |
| `SEARCH_QUERY_PARSER` | 空 | 查询解析器：空/`auto`=有 AI 用 AI，否则规则；可显式 `fake`/`rulebased`/`mimo` |
| `SEARCH_PARSER_MODEL` | 空 | 查询解析所用文本模型（留空默认纯文本端点） |
| `SEARCH_PARSER_TIMEOUT` | `8` | 查询解析超时（秒），超时降级规则解析 |
| `SEARCH_CANDIDATE_POOL` | `200` | 每召回通道候选池上限（有界融合） |

### 内置 embedder 微服务

| 变量 | 默认 | 用途 |
|---|---|---|
| `EMBEDDER_MODEL` | `intfloat/multilingual-e5-small` | 微服务加载的模型（须与 `EMBEDDING_MODEL` 一致） |
| `EMBEDDER_MODEL_REVISION` | `614241f622f53c4eeff9890bdc4f31cfecc418b3` | 同上不可变 commit SHA（须与 `EMBEDDING_MODEL_REVISION` 一致） |
| `EMBEDDER_DIMENSION` | `384` | 输出维度（须与 `EMBEDDING_DIMENSION` 一致） |
| `EMBEDDER_DEVICE` | `cpu` | 推理设备；有 GPU 可改，但 CPU 已可用 |
| `EMBEDDER_PORT` | `8100` | 仅本地 `compose.yml` 暴露端口用（NAS compose 不需要） |

---

## 6. 脚本拆段 / 匹配 / 导出

| 变量 | 默认 | 用途 |
|---|---|---|
| `SCRIPT_PARSER` | 空 | 脚本拆段器：空/`auto`=有 AI 用 AI 拆段，否则规则；可显式 `fake`/`rulebased`/`mimo` |
| `SCRIPT_PARSER_MODEL` | 空 | 拆段所用文本模型（留空回退 `AI_MODEL`，再回退纯文本端点） |
| `SCRIPT_PARSER_TIMEOUT` | `12` | 拆段超时（秒），超时降级规则拆段 |
| `SCRIPT_MATCH_CANDIDATE_LIMIT` | `10` | 每段默认候选数（上限 50） |
| `SCRIPT_MATCH_MIN_SCORE` | `0.05` | 候选最低综合分（未达视为该段缺口） |
| `SCRIPT_MATCH_MAX_REUSE` | `1` | 全局分配中单个镜头最多被分配的段数 |
| `EXPORT_WORKER_CONCURRENCY` | `1` | export-worker 并发（剪辑清单导出，轻量） |

---

## 7. Web → API 同源代理 / CORS

### `API_INTERNAL_URL`
- **必填**：否　**敏感**：否　**默认**：`http://api:8000`
- **用途**：Next.js 服务端转发到内部 API 的地址（仅服务端使用，不下发浏览器）。容器内用服务名 `api`。
- **修改场景**：一般无需改。

### `WEB_ORIGIN`
- **必填**：是（内网访问时）　**敏感**：否　**默认**：`http://localhost:3000`
- **示例**：`http://192.168.1.100:3000`
- **用途**：允许的前端来源（CORS / 同源校验）。
- **修改场景**：用户实际通过内网 IP / 域名访问 Web 时，必须设为该实际地址，否则可能被 CORS 拦截。
- **NAS 注意**：设为业务实际访问的 `http://<bind-addr>:<WEB_PORT>` 或反代后的对外地址。

---

## 8. 容器内逻辑路径与安全白名单（一般无需改）

| 变量 | 默认 | 用途 |
|---|---|---|
| `ALLOWED_SOURCE_ROOTS` | `/app/source,/app/uploads` | 允许作为素材源根的白名单（逗号分隔）；素材 `mount_path` 必须在其下 |
| `SOURCE_MOUNT_PATH` | `/app/source` | 只读 NAS 源在容器内的挂载点 |
| `DATA_DIR` | `/app/data` | 派生数据目录（关键帧 / 缩略图 / 代理 / 片段 / 导出，可读写） |
| `UPLOAD_DIR` | `/app/uploads` | 网页上传可写区（独立于只读源） |
| `UPLOAD_MAX_MB` | `4096` | 单文件上传大小上限（MiB） |

> 这些是**容器内**逻辑路径，与宿主机路径解耦；宿主机实际位置由 `CLIPMIND_DATA_ROOT` / `CLIPMIND_SOURCE_DIR` 决定。非特殊需求勿改。

---

## 9. 拆镜头 / 派生（media-worker，非敏感调参）

| 变量 | 默认 | 用途 |
|---|---|---|
| `FFPROBE_TIMEOUT` | `30` | ffprobe 探测超时（秒） |
| `FFMPEG_TIMEOUT` | `300` | 单次 ffmpeg 调用超时（秒） |
| `MEDIA_WORKER_CONCURRENCY` | `1` | media-worker 并发（FFmpeg 重负载，默认 1） |
| `DISK_MIN_FREE_MB` | `1000`（nas）/ `500`（dev） | 写派生前要求剩余空间（MiB） |
| `SHOT_DETECTOR_TYPE` | `pyscenedetect` | 镜头检测器：`pyscenedetect`（内容检测）/ `fixed`（固定时长兜底） |
| `SCENE_THRESHOLD` | `27.0` | 场景切分阈值 |
| `MIN_SHOT_DURATION` / `MAX_SHOT_DURATION` | `1.0` / `12.0` | 镜头最短 / 最长时长（秒） |
| `FALLBACK_SEGMENT_DURATION` | `5.0` | 兜底固定切分时长（秒） |
| `HEAD_PADDING` / `TAIL_PADDING` | `0` / `0` | 镜头首尾留白（秒） |
| `PROXY_MAX_HEIGHT` | `720` | 代理视频最大高度 |
| `PROXY_CRF` / `PROXY_PRESET` | `28` / `veryfast` | 代理视频编码质量 / 速度 |
| `PROXY_KEEP_AUDIO` / `PROXY_AUDIO_BITRATE` | `true` / `96k` | 代理是否保留音轨及码率 |
| `KEYFRAME_MAX_WIDTH` / `THUMBNAIL_MAX_WIDTH` | `640` / `320` | 关键帧 / 缩略图最大宽度 |
| `AUX_KEYFRAMES` | `4` | 关键帧条采样帧数（0=仅主关键帧） |

---

## 10. Docker 网络与可选代理

### `CLIPMIND_DOCKER_SUBNET`
- **必填**：否　**敏感**：否（但**勿提交真实内网网段**）　**默认**：`172.28.10.0/24`
- **示例**：`172.28.10.0/24`
- **用途**：本项目 Compose 网络子网。
- **修改场景**：仅当内网 AI Provider 私网 IP 落入默认段、或本机该段已被占用导致容器内 Provider 不可达（宿主机却可达，典型 `No route to host`）时，改为不冲突的私网 CIDR。
- **NAS 注意**：检测 `python scripts/diagnose_ai_network.py --subnet <cidr> --show-ip`；详见 [DOCKER_AI_NETWORKING.md](DOCKER_AI_NETWORKING.md)。

### 可选容器代理（`HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`）
- **必填**：否　**敏感**：否（**勿把含凭据的代理串提交仓库**）　**默认**：未设置（模板中注释）
- **用途**：企业网络要求经代理访问外网 Provider 时透传。
- **NAS 注意**：若设代理，务必把内部服务名加入 `NO_PROXY`（`localhost,127.0.0.1,postgres,redis,api,web,worker,media-worker,ai-worker,search-worker,embedder`），否则容器间互访会被代理破坏。

### `LOG_LEVEL`
- **必填**：否　**敏感**：否　**默认**：`INFO`
- **用途**：日志级别（`DEBUG`/`INFO`/`WARNING`/`ERROR`）。排查问题可临时调 `DEBUG`。日志不会输出完整密钥。

---

## 11. 最小可启动配置

只想先把系统跑起来（**不接真实 AI、用内置语义检索**），NAS 上至少要改这几项，其余用默认：

```dotenv
# 路径与绑定
CLIPMIND_DATA_ROOT=/share/clipmind            # 改成你的大容量可写盘
CLIPMIND_SOURCE_DIR=/share/video-assets       # 改成你的只读素材目录
CLIPMIND_BIND_ADDR=127.0.0.1                  # 内网访问改为 NAS 内网 IP
WEB_ORIGIN=http://192.168.1.100:3000          # 改成用户实际访问地址

# 数据库（口令二处必须一致）
POSTGRES_PASSWORD=CHANGE_ME                    # 强随机口令
DATABASE_URL=postgresql+asyncpg://clipmind:CHANGE_ME@postgres:5432/clipmind

# AI 留空 = 不打标（拆镜头 / 派生 / 内置语义检索仍可用）
AI_PROVIDER=

# 语义检索：保持默认内置 embedder
EMBEDDING_PROVIDER=openai_compatible
```

此配置下可用：素材扫描 / 上传、拆镜头、关键帧 / 缩略图 / 代理、语义 / 混合搜索、画面描述匹配、脚本规则拆段与匹配、各类导出、项目 / 集合 / 收藏。**不可用**：AI 画面描述与标签（产品 / 场景 / 动作 / 风险等需真实 AI）。

---

## 12. 启用真实 MiMo（AI 打标）和 E5（语义检索）

在"最小可启动配置"基础上，补齐 AI Provider；E5 默认已启用，确认即可：

```dotenv
# 真实 AI 打标（小米 MiMo，OpenAI 兼容）
AI_PROVIDER=mimo
AI_BASE_URL=https://example.invalid/v1        # 改成真实端点
AI_API_KEY=your-api-key                        # 真实密钥，绝不提交
AI_MODEL=mimo-v2.5                             # 视觉打标模型（支持图片）
AI_API_KEY_HEADER=                             # 非标准鉴权头才填，如 api-key

# 语义检索（E5，内置 embedder，已是默认）
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_BASE_URL=http://embedder:8100
EMBEDDING_MODEL=intfloat/multilingual-e5-small
EMBEDDING_MODEL_REVISION=614241f622f53c4eeff9890bdc4f31cfecc418b3
EMBEDDING_DIMENSION=384
```

补充说明：

- 视觉打标用 `AI_MODEL`（须支持图片）；脚本拆段 / 查询解析是**纯文本**任务，可按需另配 `SCRIPT_PARSER_MODEL` / `SEARCH_PARSER_MODEL`（留空则走默认纯文本端点）。
- E5 首次启动会下载模型到 `${CLIPMIND_DATA_ROOT}/models`，需要出网；之后离线可用。
- 容器内访问内网 AI 端点不通时，见 `CLIPMIND_DOCKER_SUBNET` 与 [DOCKER_AI_NETWORKING.md](DOCKER_AI_NETWORKING.md)。

---

## 13. 敏感变量清单（绝不提交 GitHub / 公开交付包）

以下变量含秘密，**只允许**出现在本机 `.env` 与老板私密交付包的 `private/.env`：

- `POSTGRES_PASSWORD`
- `DATABASE_URL`（内嵌口令）
- `AI_API_KEY`
- `EMBEDDING_API_KEY`（用外部 embedding 端点时）
- 含凭据的 `HTTP_PROXY` / `HTTPS_PROXY`（如有）

另外**不要写入仓库**的（虽非口令，但属内网信息）：真实 `AI_BASE_URL` 内网端点、真实 `CLIPMIND_DOCKER_SUBNET` 内网网段、真实 NAS 路径与内网 IP。仓库内只保留占位模板。

> 校验仓库未泄密：`git diff --cached --check` + 人工扫描 `AI_API_KEY` / `Bearer` / `password` 等关键字。
