#!/usr/bin/env bash
# 启动全部服务（不重建镜像；如需迁移请用 update.sh）。
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
load_env
echo "==> 启动 ClipMind"
$COMPOSE up -d
echo "NAS_START_OK"
