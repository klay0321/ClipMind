#!/usr/bin/env bash
# 停止全部服务（保留容器与数据卷；绝不 down -v、绝不删除数据）。
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
load_env
echo "==> 停止 ClipMind（数据保留）"
$COMPOSE stop
echo "NAS_STOP_OK"
