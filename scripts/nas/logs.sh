#!/usr/bin/env bash
# 查看日志：bash scripts/nas/logs.sh [service]（默认跟随全部；Ctrl-C 退出）。
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
load_env
$COMPOSE logs -f --tail=200 "$@"
