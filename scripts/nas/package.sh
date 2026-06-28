#!/usr/bin/env bash
# 生成自包含交付包 dist/clipmind-nas/（可在无 git 的目录独立构建启动）+ tar.gz + SHA256。
#
# 文件集 = 仓库「应有内容」：git 跟踪文件 + 新增未忽略文件（git ls-files [--others]），
# 因此自动排除 .gitignore 覆盖的 .env / .local / node_modules / venv / 真实视频 / 测试产物 /
# 模型缓存 / 备份 / dist 等。额外补 docker-compose.yml(=nas) / VERSION / README / CHECKSUMS。
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

OUT_DIR="dist/clipmind-nas"
echo "==> 清理 $OUT_DIR"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

echo "==> 收集文件（git 跟踪 + 新增未忽略）"
{ git ls-files; git ls-files --others --exclude-standard; } | sort -u > "$ROOT/.pkg_filelist"
# git 列表已尊重 .gitignore（真实 .env/.local/node_modules/视频 已排除，.env*.example 经 ! 例外保留）。
# 这里仅作双保险：再排除 dist 自身 / .local / 真实媒体与转储（绝不误伤 .env.example）。
grep -vEi '^dist/|(^|/)\.local/|\.(mp4|mov|mkv|avi|webm|sql)$' \
  "$ROOT/.pkg_filelist" > "$ROOT/.pkg_filelist.clean" || true

count=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  mkdir -p "$OUT_DIR/$(dirname "$f")"
  cp "$f" "$OUT_DIR/$f"
  count=$((count + 1))
done < "$ROOT/.pkg_filelist.clean"
rm -f "$ROOT/.pkg_filelist" "$ROOT/.pkg_filelist.clean"
echo "    复制 $count 个文件"

# docker-compose.yml = NAS compose（便于无脚本时直接 docker compose up）
cp docker-compose.nas.yml "$OUT_DIR/docker-compose.yml"

# VERSION
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
echo "clipmind-nas $(date +%Y-%m-%d) ${GIT_SHA}" > "$OUT_DIR/VERSION"

# 交付包 README
cat > "$OUT_DIR/README.md" <<'EOF'
# ClipMind NAS 交付包

自包含部署包（无需 git）。在 NAS 上：

1. `cp .env.nas.example .env` 并按 `docs/NAS_DEPLOYMENT.md` 填写
   （至少 POSTGRES_PASSWORD / DATABASE_URL 一致、CLIPMIND_SOURCE_DIR、CLIPMIND_DATA_ROOT、
   CLIPMIND_BIND_ADDR、AI_* 与 WEB_ORIGIN）。
2. `bash scripts/nas/install.sh`（首次：构建 → 迁移 → 启动 → 就绪检查）。
3. 浏览器访问 `http://<CLIPMIND_BIND_ADDR>:<WEB_PORT>`。

常用：`scripts/nas/{start,stop,restart,update,backup,restore,logs,healthcheck}.sh`。
**无应用级用户权限**，默认仅可信内网/VPN，勿裸露公网。详见 docs/NAS_DEPLOYMENT.md 与 docs/BOSS_QUICKSTART.md。
EOF

# CHECKSUMS（包内所有文件 sha256）
echo "==> 生成 CHECKSUMS.txt"
( cd "$OUT_DIR" && find . -type f ! -name CHECKSUMS.txt -print0 \
    | sort -z | xargs -0 sha256sum > CHECKSUMS.txt )

# 压缩包 + SHA256
echo "==> 打包 tar.gz"
TARBALL="dist/clipmind-nas-release.tar.gz"
tar -C dist -czf "$TARBALL" clipmind-nas
sha256sum "$TARBALL" | tee "${TARBALL}.sha256"

echo "==> 交付包就绪：$OUT_DIR  和  $TARBALL"
echo "RELEASE_PACKAGE_OK"
