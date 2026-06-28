#!/usr/bin/env bash
# 首次安装：准备 .env 与数据目录 → 构建镜像 → 自动迁移 → 启动 → 就绪检查。
# 幂等：可重复运行；绝不删库、绝不 down -v。
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

echo "==> ClipMind NAS 安装 (repo: $ROOT)"

if [ ! -f .env ]; then
  cp .env.nas.example .env
  echo "已从 .env.nas.example 生成 .env。"
  echo "!! 请先编辑 .env：至少设置 POSTGRES_PASSWORD / DATABASE_URL 一致、CLIPMIND_SOURCE_DIR、CLIPMIND_DATA_ROOT、CLIPMIND_BIND_ADDR、AI_* 与 WEB_ORIGIN，然后重新运行本脚本。"
  exit 0
fi
load_env

if [ "${POSTGRES_PASSWORD:-}" = "CHANGE_ME_TO_A_STRONG_PASSWORD" ] || [ -z "${POSTGRES_PASSWORD:-}" ]; then
  echo "ERROR: 请在 .env 设置强 POSTGRES_PASSWORD（且 DATABASE_URL 与之一致）。" >&2
  exit 1
fi
if [ ! -d "${CLIPMIND_SOURCE_DIR:-}" ]; then
  echo "WARNING: CLIPMIND_SOURCE_DIR='${CLIPMIND_SOURCE_DIR:-}' 不是已存在目录。请确认 NAS 素材目录路径。" >&2
fi

echo "==> 创建持久化数据目录于 ${CLIPMIND_DATA_ROOT}"
mkdir -p "${CLIPMIND_DATA_ROOT}"/{pgdata,redis,data,uploads,models,backups}

echo "==> 构建镜像（首次较慢：含 embedder 的 torch + 模型）"
$COMPOSE build

echo "==> 数据库迁移到最新（migrate 一次性服务）"
$COMPOSE run --rm migrate

echo "==> 启动全部服务"
$COMPOSE up -d

echo "==> 等待就绪 ..."
"$SCRIPT_DIR/healthcheck.sh" || {
  echo "就绪检查未通过，请查看日志：bash scripts/nas/logs.sh" >&2
  exit 1
}
echo "==> 安装完成。Web: http://<bind-addr>:${WEB_PORT:-3000}  API: http://<bind-addr>:${API_PORT:-8000}"
echo "NAS_INSTALL_OK"
