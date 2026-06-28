# 数据库升级（迁移）操作手册

> 适用于本机开发栈与公司 NAS 部署。**所有 schema 变更一律走 Alembic 迁移；禁止 `down -v`、禁止删库重建。**

## 0. 关键陷阱：`docker compose up -d` 会跳过已有库的迁移

`migrate` 是一次性服务（`restart: "no"`），依赖它的服务用 `depends_on: condition: service_completed_successfully`。

- **新部署**（首次起栈，无历史 migrate 容器）：`docker compose up -d` 会运行一次 `migrate`，DB 迁到 head，正常。
- **已有部署升级**（栈跑过、已存在一个成功退出的 migrate 容器）：再次 `docker compose up -d`（即便先
  `docker compose build` 重建了镜像）**不会重跑** migrate——Compose 认为依赖已满足，于是 API/worker 以
  **旧 schema** 启动，对新接口 `500`（如 PR-05 Gate B 接口因缺 `script_*` 表 500）。

> 因此：**升级已有数据库必须显式运行迁移**，不能只 `up -d`。

## 1. 新部署（全新数据库）

```bash
docker compose build          # 构建/更新所有镜像（含 migrate）
docker compose up -d          # 首次起栈会运行 migrate 到 head
docker compose ps             # 确认服务健康
curl -fsS http://localhost:8000/health/ready   # migration_ok 必须为 true
```

## 2. 已有数据库升级（最常见，务必显式迁移）

```bash
git pull                      # 取新代码（含新迁移）
docker compose build          # 重建镜像（含 migrate，使其包含新迁移脚本）
bash scripts/db_upgrade.sh    # 显式升级：docker compose run --rm migrate，并校验已到 head
#   Windows：pwsh scripts/db_upgrade.ps1
docker compose up -d          # 再启动/更新应用容器（此时 DB 已在 head）
curl -fsS http://localhost:8000/health/ready   # migration_ok=true 才算就绪
```

`scripts/db_upgrade.sh` 内部执行 `docker compose run --rm migrate`（**始终新建容器并运行
`alembic upgrade head`**，绕开 up -d 的跳过问题），随后校验 `alembic current` 已到 `(head)`，
输出 `SCRIPT_DB_UPGRADE_OK`。升级幂等：重复运行安全。

升级**只新增**表/列，不动既有业务数据（项目、镜头、分析、审核、导出均保留）。

> 升级指定数据库（如迁移演练用的独立测试库）：
> `DB_UPGRADE_DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/<db> bash scripts/db_upgrade.sh`

## 3. 查看当前 revision

```bash
docker compose run --rm migrate alembic current        # 应显示 ...(head)
docker compose run --rm migrate alembic heads          # 迁移脚本 head
docker compose exec -T postgres psql -U clipmind -d clipmind -tAc "select version_num from alembic_version"
curl -s http://localhost:8000/health/ready | jq '{migration_ok, migration_current, migration_head}'
```

`/health/ready` 在 DB revision 落后 head 时返回 **503** 且 `migration_ok=false`、`detail.migration`
明确提示需要升级——部署门禁/负载均衡可据此识别"需要先迁移"，而不是把流量打到旧 schema 的 API。
（容器 healthcheck 用 `/health/live`，不会因迁移落后而反复重启。）

## 4. 失败恢复

1. 看迁移输出定位失败的 revision：`docker compose run --rm migrate alembic current` 与 `... history`。
2. 修复后**重跑** `bash scripts/db_upgrade.sh`（幂等，可安全重试）。
3. 升级在事务内进行（Postgres 支持事务 DDL）；单个迁移失败会回滚到上一个 revision，不会留下半完成 schema。
4. 仍异常时，用**独立测试库**演练 `upgrade→downgrade→upgrade` 复现，再回到业务库；
   **绝不**对业务库 `alembic downgrade` 或 `docker compose down -v`。

## 5. 禁止事项

- **禁止 `docker compose down -v`**（会删除数据卷 = 删库）。`down`（不带 `-v`）只停容器、保留卷。
- 禁止删库重建代替迁移；禁止手改既有迁移文件（改 schema 一律新增迁移）。
- 不让 API 在每个请求时自行迁移；迁移只在显式升级步骤运行一次。
