#!/usr/bin/env bash
# ClipMind 数据库升级（新部署 / 已有数据库 通用）。
#
# 为什么需要本脚本：``migrate`` 是一次性服务（restart: no）。``docker compose up -d`` **不会**
# 重跑已成功退出的 migrate 容器，会把"已有数据库"的升级**静默跳过**，导致 API 以旧 schema 启动、
# 对新接口 500。每次升级（尤其已有数据库）必须显式运行本脚本或等价的
# ``docker compose run --rm migrate``（始终新建容器并执行 ``alembic upgrade head``）。
#
# 用法：
#   bash scripts/db_upgrade.sh                      # 升级默认（.env 的 DATABASE_URL）数据库
#   DB_UPGRADE_DATABASE_URL=<async-url> bash scripts/db_upgrade.sh   # 升级指定数据库（如测试库）
#
# 安全：本脚本只 upgrade，绝不 ``down -v``、绝不删库；失败请见 docs（查看 revision / 恢复）。
set -Eeuo pipefail

cd "$(dirname "$0")/.."  # 仓库根（compose.yml 所在）

run_args=()
if [ -n "${DB_UPGRADE_DATABASE_URL:-}" ]; then
  run_args+=(-e "DATABASE_URL=${DB_UPGRADE_DATABASE_URL}")
fi

echo "[db_upgrade] 升级数据库到 head ..."
docker compose run --rm ${run_args[@]+"${run_args[@]}"} migrate

echo "[db_upgrade] 校验当前 revision 已到 head ..."
current_out="$(docker compose run --rm ${run_args[@]+"${run_args[@]}"} migrate alembic current 2>&1 || true)"
echo "$current_out"
if echo "$current_out" | grep -q "(head)"; then
  echo "[db_upgrade] 数据库已在 head"
  echo "SCRIPT_DB_UPGRADE_OK"
else
  echo "[db_upgrade] 失败：升级后 revision 未到 head（请查看上方输出与 docs 升级章节）" >&2
  exit 1
fi
