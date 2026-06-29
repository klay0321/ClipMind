# ClipMind NAS 部署指南（部署人员）

面向 NAS 管理员/部署人员。ClipMind 是公司自托管的 AI 视频素材管理与匹配系统，只读索引 NAS 原始素材，
派生关键帧/缩略图/代理、外部 AI 打标、自然语言检索、画面/脚本匹配、多格式与打包导出。

> **重要边界**：本版本**无应用级用户登录/权限**（计划于后续版本 PR-07）。因此**默认仅限可信内网/VPN 访问，
> 切勿直接暴露到公网**。需要外网访问时，请置于反向代理 + HTTPS + 网络层访问控制之后。

## 1. 前置条件
- 已安装 **Docker** 与 **Docker Compose v2**（`docker compose version`）。
- **x86_64（amd64）已验证**。**arm64 未验证**：部分基础镜像/torch 轮子在 arm64 上可能需自行调整，
  本包不对 arm64 作可用性承诺（见 §8）。
- 一块**大容量可写磁盘**用于派生数据与数据库；NAS 原始素材目录（只读）。
- 出网能力：首次构建需拉取基础镜像与 Python/Node 依赖；若用真实 AI（MiMo）需能访问其 API 端点。

## 2. 交付包内容
解压交付包 `clipmind-nas-release.tar.gz` 后得到 `clipmind-nas/`，包含：
`docker-compose.nas.yml`（= `docker-compose.yml`）、`.env.nas.example`、`apps/`、`packages/`、
`services/`、`infra/`（各服务 Dockerfile）、`scripts/nas/`（运维脚本）、`docs/`、`VERSION`、`CHECKSUMS.txt`。
**不含** `.env`、密钥、真实视频、数据库、模型缓存、`node_modules`、虚拟环境、测试产物。
可用 `sha256sum -c CHECKSUMS.txt` 校验完整性。

## 3. 配置 `.env`
```bash
cp .env.nas.example .env
# 然后编辑 .env
```
必须修改的关键项：
| 变量 | 说明 |
|---|---|
| `POSTGRES_PASSWORD` | 强口令；**`DATABASE_URL` 中的密码必须与之一致**。 |
| `CLIPMIND_SOURCE_DIR` | NAS 原始素材目录（**只读**挂载到 `/app/source`）。例如 `/share/video-assets`。 |
| `CLIPMIND_DATA_ROOT` | 持久化数据根（数据库/redis/派生/上传/模型/备份）。指向大容量磁盘，例如 `/share/clipmind`。**不要硬编码厂商专属路径**，按你的 NAS 实际路径填。 |
| `CLIPMIND_BIND_ADDR` | 端口绑定地址。默认 `127.0.0.1`（仅本机）。内网访问设为 NAS 内网 IP；`0.0.0.0` 仅在已受 VPN/反代保护时。 |
| `WEB_ORIGIN` | 用户访问 Web 的地址（CORS），如 `http://192.168.1.10:3000`。 |
| `AI_PROVIDER` / `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL` | 真实视频打标所需的外部 AI（如小米 MiMo，OpenAI 兼容）。留空则不产出 AI 描述/标签。密钥仅写入本机 `.env`，绝不进仓库/日志。 |
| `API_PORT` / `WEB_PORT` | 对外端口（默认 8000 / 3000）。 |

语义检索默认启用内置 `embedder`（多语 e5-small，纯 CPU 可用），首次构建会下载模型并持久化到
`${CLIPMIND_DATA_ROOT}/models`。

## 4. 安装与启动
```bash
bash scripts/nas/install.sh
```
该脚本：校验 `.env` → 创建数据目录 → 构建镜像 → 自动迁移数据库到最新 → 启动全部服务 → 就绪检查
（输出 `NAS_INSTALL_OK`）。完成后浏览器访问 `http://<CLIPMIND_BIND_ADDR>:<WEB_PORT>`。

## 5. 数据布局（`${CLIPMIND_DATA_ROOT}` 下）
```
pgdata/    PostgreSQL 数据      redis/    Redis AOF
data/      派生（关键帧/缩略图/代理/导出 exports·script_exports·bundle_exports）
uploads/   网页上传可写区        models/   embedder 模型缓存
backups/   备份产物（backup.sh 写入）
```
原始素材在 `CLIPMIND_SOURCE_DIR`，**系统只读、绝不写入/改名/删除源文件**。

## 6. 日常运维
| 操作 | 命令 |
|---|---|
| 启动 / 停止 / 重启 | `scripts/nas/start.sh` · `stop.sh` · `restart.sh` |
| 就绪检查 | `scripts/nas/healthcheck.sh`（API `/health/ready`） |
| 查看日志 | `scripts/nas/logs.sh [服务名]` |
| 备份 | `scripts/nas/backup.sh`（DB+配置）；`--with-data` 含派生数据 |
| 恢复 | `scripts/nas/restore.sh <backup.tar.gz>`（**需输入 RESTORE 确认**，破坏性） |
| 升级 | `scripts/nas/update.sh`（**先自动备份** → 重建 → 迁移 → 滚动重启） |

> 停止只用 `stop`（保留数据卷）。**任何脚本都不会执行 `down -v`，不会删除数据库或派生数据。**
> 数据库变更一律 Alembic 迁移，绝不删库重建。容器 `restart: unless-stopped`，NAS 重启后随 Docker 自启。
> 日志已配置 json-file 轮转（单文件 10MB × 5）。

## 7. 安全
- 无应用级鉴权 → **仅可信内网/VPN**；公网访问须反代 + HTTPS + 访问控制。
- 源素材只读；导出删除只删派生文件，绝不碰源。下载只服务派生目录，路径经穿越校验。
- `.env`/密钥不入镜像、不入日志、不入交付包。

## 8. 架构兼容
- **x86_64：已验证**（构建、迁移、核心流程、导出、重启持久均通过）。
- **arm64：未验证**。`embedder` 的 torch 与若干轮子在 arm64 上可能需替换基础镜像/依赖；
  如在 arm64 NAS 部署，请先小范围验证，本包不作 arm64 可用性承诺。

## 9. 故障排查
- 升级后接口 500：多为未迁移。运行 `scripts/nas/update.sh` 或 `docker compose -f docker-compose.nas.yml run --rm migrate`。
- 容器内无法访问内网 AI（No route to host，宿主机却可达）：调整 `CLIPMIND_DOCKER_SUBNET` 避开 Provider 私网段。
- 搜索为词法降级：检查 `embedder` 是否 healthy、`EMBEDDING_PROVIDER=openai_compatible`、模型已下载。
