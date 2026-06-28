#!/usr/bin/env bash
# 重启全部服务（不重建、不迁移、不删数据）。
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
load_env
echo "==> 重启 ClipMind"
$COMPOSE restart
echo "NAS_RESTART_OK"
