#!/usr/bin/env bash
# 从备份恢复数据库（破坏性：覆盖当前库）。需显式确认。绝不 down -v、绝不删派生媒体目录。
# 用法：bash scripts/nas/restore.sh <backup.tar.gz> [--yes]
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
load_env

BACKUP="${1:-}"
if [ -z "$BACKUP" ] || [ ! -f "$BACKUP" ]; then
  echo "用法：bash scripts/nas/restore.sh <backup.tar.gz> [--yes]" >&2
  exit 1
fi

if [ "${2:-}" != "--yes" ]; then
  echo "!! 即将用备份覆盖当前数据库 ${POSTGRES_DB}（不可逆）。"
  printf '请输入大写 RESTORE 以确认：'
  read -r ans
  [ "$ans" = "RESTORE" ] || { echo "已取消。"; exit 1; }
fi

STAGE="$(mktemp -d)"
# --force-local：备份路径可能带盘符(如 C:/...)，避免 GNU tar 误判为远程 host:path。
tar --force-local -C "$STAGE" -xzf "$BACKUP"
[ -f "$STAGE/db.sql" ] || { echo "ERROR: 备份缺少 db.sql" >&2; rm -rf "$STAGE"; exit 1; }

echo "==> 确保数据库容器运行"
$COMPOSE up -d postgres
echo "==> 等待 postgres 就绪（轮询 pg_isready，避免固定 sleep 在冷启动时不足）"
ready=0
for _ in $(seq 1 60); do
  if $COMPOSE exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[ "$ready" = "1" ] || { echo "ERROR: postgres 未在预期时间内就绪。" >&2; rm -rf "$STAGE"; exit 1; }

echo "==> 重置并恢复库 schema"
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$STAGE/db.sql"

if [ -f "$STAGE/derived.tar.gz" ]; then
  echo "==> 恢复派生数据"
  tar --force-local -C "${CLIPMIND_DATA_ROOT}" -xzf "$STAGE/derived.tar.gz"
fi

rm -rf "$STAGE"
echo "==> 应用最新迁移（确保 schema 与代码一致）"
$COMPOSE run --rm migrate
echo "==> 重启应用"
$COMPOSE up -d
echo "NAS_RESTORE_OK"
