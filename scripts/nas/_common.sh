#!/usr/bin/env bash
# ClipMind NAS 脚本公共前导：定位仓库根、定义 compose 包装、加载 .env。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="docker-compose.nas.yml"
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: 未找到 docker，请先安装 Docker / Docker Compose。" >&2
  exit 1
fi
COMPOSE="docker compose -f $COMPOSE_FILE"

load_env() {
  if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
  fi
}

: "${CLIPMIND_DATA_ROOT:=./clipmind-data}"
: "${POSTGRES_USER:=clipmind}"
: "${POSTGRES_DB:=clipmind}"
