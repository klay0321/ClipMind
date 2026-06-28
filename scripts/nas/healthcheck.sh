#!/usr/bin/env bash
# 就绪检查：关键容器 running + API /health/ready 通过。退出码非 0 表示未就绪。
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
load_env

deadline=$(( $(date +%s) + 180 ))
ok=0
while [ "$(date +%s)" -lt "$deadline" ]; do
  if $COMPOSE exec -T api curl -fsS http://localhost:8000/health/ready >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 5
done

echo "==> 容器状态："
$COMPOSE ps

if [ "$ok" -ne 1 ]; then
  echo "API /health/ready 未在超时内通过。" >&2
  exit 1
fi
echo "NAS_HEALTH_OK"
