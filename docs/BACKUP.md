# 数据库备份与恢复

## 为什么只备份数据库

系统三类数据的可再生性完全不同：

| 数据 | 位置 | 丢了怎么办 |
| --- | --- | --- |
| 源视频/图片 | NAS（只读挂载） | 系统从不写它，NAS 自身冗余负责 |
| 派生文件（关键帧/代理/海报/导出） | data 目录 | 由源视频重新计算即可 |
| AI 打标/向量 | PostgreSQL | 重新调用 AI/模型即可（花钱但可再生） |
| **人工成果**（产品绑定、审核结论、使用血缘、产品目录、项目） | **PostgreSQL** | **不可再生——这是备份存在的唯一原因** |

因此备份策略 = 只备 PostgreSQL（`pg_dump -Fc` custom 格式，支持选择性恢复）。

## 自动备份（db-backup sidecar）

`docker compose up -d` 即自动运行：启动立即备份一次，之后每
`BACKUP_INTERVAL_HOURS`（默认 24）小时一次，滚动保留 `BACKUP_RETAIN`
（默认 14）份。备份文件：data 卷/目录下 `backups/clipmind-<UTC时间>.dump`。

```bash
# 查看备份状态与文件
docker compose logs db-backup --tail 10
docker compose exec -T postgres ls -lh /app/data/backups/
```

**强烈建议**：把备份目录同步到另一块盘/另一台设备（NAS 部署时
`${CLIPMIND_DATA_ROOT}/data/backups` 加入 NAS 自带的同步/复制计划）。
备份和数据库在同一块盘上只能防"误删库/迁移事故"，防不了盘坏。

## 恢复演练（不动生产库，随时可做）

```bash
docker compose exec -T postgres sh /backup-scripts/pg_restore.sh \
  --drill /app/data/backups/clipmind-<TS>.dump
```

恢复到临时库并对比关键表行数（asset/shot/产品绑定/使用血缘/审核状态），
完成后自动清理临时库，输出 `RESTORE_DRILL_OK`。建议每月做一次演练——
没演练过的备份等于没有备份。

## 真实恢复（灾难后）

1. 停应用服务（保留 postgres）：
   `docker compose stop api worker media-worker ai-worker search-worker export-worker beat web`
2. 恢复：
   `docker compose exec -T postgres sh /backup-scripts/pg_restore.sh --restore /app/data/backups/clipmind-<TS>.dump`
3. 重启全栈并抽查：`docker compose up -d`，打开首页仪表盘核对数字，
   抽查产品绑定与使用记录。
4. 备份时点之后的派生文件/AI 结果差异由自动链自愈（扫描 sweep 会补齐）。

## 与 scripts/nas/backup.sh 的关系

仓库另有一套**手动**备份脚本（`scripts/nas/backup.sh` / `restore.sh`）：
打包数据库 + `.env` 配置（可选加派生数据），适合升级前/迁移前的一次性
全量快照。本文的 db-backup sidecar 是**自动**层——无人值守的日常兜底，
不需要任何人记得去跑。两者互补：日常靠 sidecar，大变更前手动跑一次
`bash scripts/nas/backup.sh`。

## 配置

`.env`：`BACKUP_INTERVAL_HOURS`（默认 24）、`BACKUP_RETAIN`（默认 14）。
