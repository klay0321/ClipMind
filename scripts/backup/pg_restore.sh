#!/bin/sh
# ClipMind PostgreSQL 恢复（在 postgres 容器内运行；详见 docs/BACKUP.md）。
#
# 用法（宿主机，项目根目录）：
#   演练（恢复到临时库并对比行数，不动生产库）：
#     docker compose exec -T postgres sh /backup-scripts/pg_restore.sh --drill /app/data/backups/clipmind-<TS>.dump
#   真实恢复（覆盖生产库；先停应用服务！见 docs/BACKUP.md 步骤）：
#     docker compose exec -T postgres sh /backup-scripts/pg_restore.sh --restore /app/data/backups/clipmind-<TS>.dump
set -eu

MODE="${1:?用法: pg_restore.sh --drill|--restore <dump 文件>}"
DUMP="${2:?缺少 dump 文件路径}"
: "${PGUSER:=clipmind}"
: "${PGDATABASE:=clipmind}"
export PGUSER PGDATABASE

[ -f "$DUMP" ] || { echo "dump 不存在: $DUMP" >&2; exit 1; }

if [ "$MODE" = "--drill" ]; then
  DRILL_DB="clipmind_restore_drill"
  echo "[drill] 恢复到临时库 $DRILL_DB（不影响生产库）"
  dropdb --if-exists "$DRILL_DB"
  createdb "$DRILL_DB"
  pg_restore --no-owner --dbname="$DRILL_DB" "$DUMP"
  echo "[drill] 行数对比（生产 vs 演练）："
  for t in asset shot product_media_link final_video_usage shot_review_state; do
    prod=$(psql -d "$PGDATABASE" -t -A -c "SELECT count(*) FROM $t" 2>/dev/null || echo "-")
    drill=$(psql -d "$DRILL_DB" -t -A -c "SELECT count(*) FROM $t" 2>/dev/null || echo "-")
    echo "  $t: 生产=$prod 演练=$drill"
  done
  dropdb "$DRILL_DB"
  echo "[drill] 演练完成，临时库已清理 RESTORE_DRILL_OK"
elif [ "$MODE" = "--restore" ]; then
  echo "[restore] 覆盖恢复生产库 $PGDATABASE（请确认应用服务已停止）"
  pg_restore --no-owner --clean --if-exists --dbname="$PGDATABASE" "$DUMP"
  echo "[restore] 完成。请重启应用服务并抽查数据。RESTORE_OK"
else
  echo "未知模式: $MODE（--drill 或 --restore）" >&2
  exit 2
fi
