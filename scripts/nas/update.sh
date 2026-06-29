#!/usr/bin/env bash
# 升级：先自动备份 → 重建镜像 → 迁移数据库 → 滚动重启。绝不删库、绝不 down -v。
# 幂等：已是最新时再次运行不会破坏数据（迁移为空操作）。
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
load_env

echo "==> 升级前自动备份"
"$SCRIPT_DIR/backup.sh"

echo "==> 重建镜像（代码/依赖更新后）"
$COMPOSE build

echo "==> 数据库迁移到最新"
$COMPOSE run --rm migrate

echo "==> 滚动重启服务"
$COMPOSE up -d

echo "==> 就绪检查"
"$SCRIPT_DIR/healthcheck.sh"
echo "NAS_UPDATE_OK"
