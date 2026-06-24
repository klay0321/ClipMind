#!/usr/bin/env bash
# ClipMind NAS 部署前环境预检（模板）。
# 仅做本机环境检查，不连接、不登录、不修改任何真实 NAS。
# 正式部署前请结合 docs/NAS_DEPLOYMENT_CHECKLIST.md 人工确认全部事项。
set -u

echo "=== ClipMind NAS 预检 ==="

echo "--- CPU 架构（需确认镜像兼容，x86_64 / aarch64）---"
uname -m || true

echo "--- 操作系统 ---"
uname -a || true

echo "--- Docker ---"
if command -v docker >/dev/null 2>&1; then
  docker --version
else
  echo "未安装 Docker（NAS 上需可安装/启用 Docker）"
fi

echo "--- Docker Compose ---"
if docker compose version >/dev/null 2>&1; then
  docker compose version
else
  echo "未检测到 docker compose 插件"
fi

echo "--- 内存（建议 ≥ 8GB，推荐 16GB）---"
free -h 2>/dev/null || echo "无 free 命令（可在 NAS 上手动确认内存）"

echo "--- 磁盘可用空间（派生文件需原始素材容量的 0.5~1 倍）---"
df -h 2>/dev/null || true

echo "--- FFmpeg/FFprobe ---"
command -v ffmpeg >/dev/null 2>&1 && ffmpeg -version | head -1 || echo "未安装 ffmpeg（容器内置，本机可选）"
command -v ffprobe >/dev/null 2>&1 && ffprobe -version | head -1 || echo "未安装 ffprobe（容器内置，本机可选）"

echo
echo "提醒："
echo "  1) 原始素材目录必须以只读方式挂载（/nas/source:/app/source:ro）。"
echo "  2) 系统数据目录可读写（/nas/clipmind-data:/app/data:rw）。"
echo "  3) 不要把 NAS 用户名/密码/IP/密钥写入代码或 Git。"
echo "  4) 当前为本地模拟验证，未进行真实 NAS 部署。"
