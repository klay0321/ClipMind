#!/bin/sh
# ClipMind PostgreSQL 定时备份（db-backup sidecar 内运行）。
#
# 为什么只备份数据库：源视频只读在 NAS、派生文件（关键帧/代理/海报）可由
# 源视频重算、AI 结果可重打——唯独 PostgreSQL 里的人工成果（产品绑定、
# 审核结论、使用血缘、目录结构）不可再生。本脚本用 pg_dump -Fc（custom
# 格式，支持 pg_restore 选择性恢复）备份到 /app/data/backups/。
#
# 行为：启动立即备份一次，之后每 BACKUP_INTERVAL_HOURS 小时一次；
# 按 BACKUP_RETAIN 份数滚动清理最旧备份；单次失败只记日志不退出（下轮重试）。
set -u

: "${PGHOST:=postgres}"
: "${PGUSER:=clipmind}"
: "${PGDATABASE:=clipmind}"
: "${BACKUP_DIR:=/app/data/backups}"
: "${BACKUP_INTERVAL_HOURS:=24}"
: "${BACKUP_RETAIN:=14}"
export PGHOST PGUSER PGDATABASE

mkdir -p "$BACKUP_DIR"

do_backup() {
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  tmp="$BACKUP_DIR/.inprogress-$ts.dump"
  out="$BACKUP_DIR/clipmind-$ts.dump"
  echo "[backup] $(date -u) 开始 pg_dump -> $out"
  if pg_dump -Fc --no-owner --file="$tmp"; then
    mv "$tmp" "$out"
    size=$(wc -c < "$out")
    echo "[backup] 完成（$size bytes）"
  else
    rm -f "$tmp"
    echo "[backup] pg_dump 失败，等待下一轮重试" >&2
    return 1
  fi
  # 滚动保留：只留最近 BACKUP_RETAIN 份（按文件名时间序）
  ls -1 "$BACKUP_DIR"/clipmind-*.dump 2>/dev/null | sort | head -n "-$BACKUP_RETAIN" | \
    while read -r old; do
      echo "[backup] 清理过期备份 $old"
      rm -f "$old"
    done
  return 0
}

echo "[backup] 每 ${BACKUP_INTERVAL_HOURS}h 一次，保留 ${BACKUP_RETAIN} 份，目录 $BACKUP_DIR"
while true; do
  do_backup || true
  sleep $((BACKUP_INTERVAL_HOURS * 3600))
done
