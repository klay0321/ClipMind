#!/usr/bin/env bash
# 备份：PostgreSQL 逻辑转储 + 配置(.env / compose) → ${CLIPMIND_DATA_ROOT}/backups/<ts>.tar.gz
# 选项：--with-data 额外打包派生数据目录(data/uploads，可能很大；默认不含，派生文件可重生成)。
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
load_env

WITH_DATA=0
[ "${1:-}" = "--with-data" ] && WITH_DATA=1

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${CLIPMIND_DATA_ROOT}/backups"
STAGE="$(mktemp -d)"
mkdir -p "$BACKUP_DIR"

echo "==> 导出数据库 (${POSTGRES_DB})"
$COMPOSE exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner > "$STAGE/db.sql"

echo "==> 收集配置"
cp .env "$STAGE/.env" 2>/dev/null || true
cp "$COMPOSE_FILE" "$STAGE/$COMPOSE_FILE" 2>/dev/null || true
[ -f VERSION ] && cp VERSION "$STAGE/VERSION" || echo "unknown" > "$STAGE/VERSION"
echo "backup_created_at=$TS" > "$STAGE/MANIFEST.txt"

if [ "$WITH_DATA" -eq 1 ]; then
  echo "==> 打包派生数据 (data/uploads，可能较大)"
  # --force-local：当 CLIPMIND_DATA_ROOT 为带盘符路径(如 C:/...)时，避免 GNU tar 误判为远程 host:path。
  tar --force-local -C "${CLIPMIND_DATA_ROOT}" -czf "$STAGE/derived.tar.gz" data uploads 2>/dev/null || true
fi

OUT="${BACKUP_DIR}/clipmind-backup-${TS}.tar.gz"
tar --force-local -C "$STAGE" -czf "$OUT" .
rm -rf "$STAGE"
echo "==> 备份完成：$OUT"
echo "NAS_BACKUP_OK $OUT"
