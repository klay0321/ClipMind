# Docker 内访问 AI Provider 的网络问题与修复

适用于"**宿主机能调用 AI Provider，但 Docker 容器内调用失败**"的情况（典型现象 `No route to host`、
请求无 HTTP 响应、provider health 失败）。本文不含任何真实内网地址 / Endpoint / 凭据。

## 1. 典型症状

- 宿主机直接调用 Provider（或 `scripts/probe_ai_provider.py`）成功；
- `docker compose exec ai-worker` 内调用失败，错误码常见 `OSError: [Errno 113] No route to host`，
  数据库里表现为 `ai_call_log.error_code=unavailable`、`http_status` 为空（连 HTTP 都没握上）；
- Provider 域名在容器内**能正常 DNS 解析**，但 TCP 443 连不上。

## 2. 最常见根因：Docker 子网与 Provider 私网地址重叠

许多公司把 AI Provider 部署在内网，其域名解析出的是**私有地址**（如 `172.x.x.x` / `10.x.x.x`）。
Docker 给 Compose 项目自动分配的网桥子网也常落在 `172.16.0.0/12` 区间。当二者重叠时：

- 容器路由表把整个项目子网视为 **eth0 直连**；
- 容器误判 Provider 的私网 IP 也"在本网桥上"，于是在桥上 ARP；
- 桥上并没有这台主机 → `No route to host`；
- 宿主机却在真实网络/VPN 上能到达该 IP，于是"宿主机可、容器不可"。

> 它**不是** DNS 问题（解析正常）、**不是**鉴权/模型问题（连 TCP 都没通）。

## 3. 诊断（脱敏）

```bash
# 1) 宿主机：自动读运行网络真实 CIDR，重叠则非零退出（subnet_overlap=true / 退出码 4）
python scripts/diagnose_ai_network.py --docker-network clipmind_default --fail-on-overlap

# 2) 容器内（与宿主机对比）：脚本仅依赖标准库，可直接管道进容器执行
docker compose exec -T ai-worker python - < scripts/diagnose_ai_network.py
#    或显式给定子网： ... --subnet ${CLIPMIND_DOCKER_SUBNET:-172.28.10.0/24} --show-ip

# 3) 看本项目 Docker 网络实际子网
docker network inspect clipmind_default --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'
```

`scripts/diagnose_ai_network.py` 默认脱敏（只打印 scheme、脱敏 hostname、端口、地址类型、
所用 Docker 子网、是否重叠、DNS/TCP/TLS 结果、代理是否"已配置"），加 `--show-ip` 才显示解析 IP，
绝不打印 API Key / Authorization / URL query。它可在**宿主机、api 容器、ai-worker 容器、NAS** 分别运行以对比。
重叠判定 CIDR 来源优先级：`--subnet` 显式 > `--docker-network` 实际 > `CLIPMIND_DOCKER_SUBNET`/默认。

判定矩阵：

| 现象 | 根因 | 处理 |
|---|---|---|
| 容器 DNS ok、TCP fail、Provider IP 落入本网子网 | **子网重叠** | 改 `CLIPMIND_DOCKER_SUBNET`（见 §4） |
| 容器 DNS fail | 容器 DNS 不可用 | 配置容器 DNS / 走企业解析 |
| 容器无代理但企业要求经代理出网 | 代理未透传 | 设 `HTTP(S)_PROXY` + `NO_PROXY`（见 §5） |
| 宿主机也连不上 | VPN/网络本身 | 先在宿主机打通，再看容器 |

## 4. 修复：可配置的 Compose 子网

`compose.yml` 把默认网络子网设为可覆盖变量，默认 `172.28.10.0/24`（避开常见的
`172.17`(docker0) 与 `172.19`）：

```yaml
networks:
  default:
    ipam:
      config:
        - subnet: ${CLIPMIND_DOCKER_SUBNET:-172.28.10.0/24}
```

当默认段仍与你的 Provider 私网 IP 重叠、或本机该段已被占用时，在 `.env` 覆盖为**不冲突**的私网 CIDR：

```dotenv
CLIPMIND_DOCKER_SUBNET=10.123.45.0/24   # 示例；请按本机实际选一个不冲突的私网段
```

> **没有对所有环境永远安全的默认值**：任何私有 CIDR 都可能与某个具体企业网络冲突。
> `172.28.10.0/24` 只是一个避开常见冲突的**安全起点**。**正式部署（尤其 NAS / 企业内网）前
> 必须先跑诊断脚本**确认所选段与 Provider 地址、本机网络都不重叠：
> ```bash
> python scripts/diagnose_ai_network.py --docker-network clipmind_default --fail-on-overlap
> # subnet_overlap=true / 退出码 4 → 换 CLIPMIND_DOCKER_SUBNET
> ```
> 校验时机：`docker compose config` 只做模板替换、**不校验** CIDR 格式；非法值（如缺 `/`）会在
> `docker compose up` 建网时**直接报错失败**（`netip.ParsePrefix` 错误），**绝不会静默回退**到其它网络。

选段原则：避开 Provider 解析出的 IP 所在段、避开 `docker0`、避开本机已用的 LAN/VPN 段。
改完安全重启（**保留数据卷**）：

```bash
docker compose down        # 切勿 down -v（会删数据库与派生文件）
docker compose up -d
docker network inspect clipmind_default --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'  # 确认已生效
```

子网改到不重叠后，Provider 私网 IP 不再"直连"，改经默认网关转发到宿主机出网即可到达。
**绝不**把 Provider 真实 IP 硬编码进 `compose.yml` 或用 `extra_hosts` 固定真实地址。

> 失败症状：若你本机（如企业 VPN）已占用默认段 `172.28.10.0/24`，`docker compose up` 会
> 直接报 `Pool overlaps with other one on this address space`（固定子网无法像自动分配那样
> 回退到空闲段）。这不是项目坏了——在 `.env` 把 `CLIPMIND_DOCKER_SUBNET` 改成本机空闲的私网段即可。

## 5. 代理 / NO_PROXY（仅当企业要求经代理出网）

代理变量通过 `.env`（`env_file`）自动透传到 api 与 ai-worker，二者行为一致。只透传变量、
**绝不**把代理账号密码提交进仓库。务必把内部服务名加入 `NO_PROXY`，避免内部流量被发往代理：

```dotenv
HTTPS_PROXY=http://<你的企业代理>:<port>
NO_PROXY=localhost,127.0.0.1,postgres,redis,api,web,worker,media-worker,ai-worker
```

## 6. Windows Docker Desktop + VPN 注意

- 容器运行在 Docker Desktop 的 Linux VM 内，出网经 VM→Windows 宿主 NAT。只要宿主机能到达
  Provider（含 VPN 路由），子网不重叠时容器即可经宿主出网到达。
- 若改子网后宿主机能连、容器仍不通，多为 VPN 仅在宿主生效、未进入 Docker VM：评估
  Docker Desktop 的 VPN 兼容选项或经企业允许的代理出网；**不要**用仅 Linux 适用的
  `network_mode: host` 作为 Windows 默认方案。

## 7. NAS 部署注意

- NAS 上同样先确认宿主（NAS）能解析并到达 Provider；
- 用 `diagnose_ai_network.py` 在 NAS 容器内核对子网是否与 Provider/内网网段重叠；
- 如重叠，设 `CLIPMIND_DOCKER_SUBNET` 为 NAS 网络中不冲突的私网段；
- 详见 `docs/NAS_DEPLOYMENT_CHECKLIST.md`。

## 8. FakeProvider 与真实 Provider 切换

- CI / 离线 / 截图演示用 `AI_PROVIDER=fake`（确定性、不联网，不受本网络问题影响）；
- 真实分析设 `AI_PROVIDER=mimo`（或其它 OpenAI 兼容 Provider）+ `AI_BASE_URL` / `AI_API_KEY`
  （仅本机 `.env`，git 忽略，绝不提交）。切换后 `docker compose down && up -d` 重载环境（勿 `-v`）。

## 9. 安全红线

- 不在仓库/PR/公开日志写入：真实 Endpoint、私网 IP、内网拓扑、API Key、Authorization、代理凭据；
- 诊断脚本默认脱敏；`--show-ip` 仅供本地终端；
- 修复必须可移植、可配置，不绑定单一开发者机器，不硬编码任何环境专属地址。
