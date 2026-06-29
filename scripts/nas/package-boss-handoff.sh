#!/usr/bin/env bash
# 生成「老板私密交付包」：把公开发布包 + 公开文档 + 一份真实私密 .env 组装成单一压缩包，
# 供通过安全渠道私下交给老板 / NAS 管理员。
#
#   ❗ 产物含真实配置（数据库口令、AI 密钥等），是 PRIVATE 文件。
#   ❗ 全程落在 dist/（已被 .gitignore 忽略），绝不提交 GitHub / 公开网盘。
#   ❗ 本脚本本身不含任何秘密；秘密只来自调用方用 --private-env 指定的本机 .env。
#   ❗ 本脚本绝不打印 .env 的任何变量值（只报告"变量是否完整"）。
#
# 用法：
#   bash scripts/nas/package-boss-handoff.sh \
#     --private-env /absolute/path/to/private.env \
#     --release-archive dist/clipmind-nas-release.tar.gz
#
# 前置：先运行 scripts/nas/package.sh 生成 dist/clipmind-nas-release.tar.gz（及其 .sha256）。
set -euo pipefail

# ---- 定位仓库根（不依赖 _common.sh / docker）----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

die() { echo "ERROR: $*" >&2; exit 1; }
INVOKE_PWD="$(pwd)"

# 把可能相对（相对调用目录）的路径转为绝对路径，但**不解析符号链接**（防 symlink 逃逸）。
abspath() {
  local p="$1"
  case "$p" in
    /*) printf '%s\n' "$p" ;;            # 已是绝对路径
    *)  printf '%s/%s\n' "$INVOKE_PWD" "$p" ;;
  esac
}

# ---- 解析参数 ----
PRIVATE_ENV=""
RELEASE_ARCHIVE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --private-env)      PRIVATE_ENV="${2:-}"; shift 2 ;;
    --release-archive)  RELEASE_ARCHIVE="${2:-}"; shift 2 ;;
    -h|--help)
      grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "未知参数：$1（用 --help 查看用法）" ;;
  esac
done
[ -n "$PRIVATE_ENV" ]     || die "缺少 --private-env <path>"
[ -n "$RELEASE_ARCHIVE" ] || die "缺少 --release-archive <path>"

PRIVATE_ENV="$(abspath "$PRIVATE_ENV")"
RELEASE_ARCHIVE="$(abspath "$RELEASE_ARCHIVE")"

# ---- 1+3+7. 校验输入存在、是普通文件、且非符号链接 ----
[ -e "$PRIVATE_ENV" ]     || die "私密配置不存在：$PRIVATE_ENV"
[ ! -L "$PRIVATE_ENV" ]   || die "私密配置不能是符号链接（防 symlink 逃逸）：$PRIVATE_ENV"
[ -f "$PRIVATE_ENV" ]     || die "私密配置不是普通文件：$PRIVATE_ENV"
[ -e "$RELEASE_ARCHIVE" ] || die "发布包不存在：$RELEASE_ARCHIVE（请先运行 scripts/nas/package.sh）"
[ ! -L "$RELEASE_ARCHIVE" ] || die "发布包不能是符号链接：$RELEASE_ARCHIVE"
[ -f "$RELEASE_ARCHIVE" ] || die "发布包不是普通文件：$RELEASE_ARCHIVE"

echo "==> 校验发布包完整性（SHA256）"
SIDECAR="${RELEASE_ARCHIVE}.sha256"
ACTUAL_SHA="$(sha256sum "$RELEASE_ARCHIVE" | awk '{print $1}')"
if [ -f "$SIDECAR" ]; then
  EXPECTED_SHA="$(awk '{print $1}' "$SIDECAR" | head -n1)"
  [ "$ACTUAL_SHA" = "$EXPECTED_SHA" ] || die "发布包 SHA256 与 .sha256 不符（包可能损坏 / 不是最新）"
  echo "    SHA256 校验通过：$ACTUAL_SHA"
else
  echo "    WARN: 未找到 ${SIDECAR##*/}，跳过比对（仅记录当前 SHA256：$ACTUAL_SHA）"
fi

# ---- 5+6. 校验私密配置（只看变量是否完整，绝不打印任何值）----
echo "==> 校验私密配置（只报告变量是否完整，不显示任何值）"

# 仍含占位符 = 没改完，硬失败
if grep -q 'CHANGE_ME' "$PRIVATE_ENV"; then
  die "私密配置仍包含 CHANGE_ME 占位符，请先填好真实强口令再打包"
fi

# 取某变量的值（去除首尾空白/引号），仅用于判空，**不回显**
env_value() {
  local k="$1" line val
  line="$(grep -E "^[[:space:]]*${k}=" "$PRIVATE_ENV" | head -n1 || true)"
  val="${line#*=}"
  val="${val%\"}"; val="${val#\"}"
  val="${val%\'}"; val="${val#\'}"
  # 去首尾空白
  val="$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  printf '%s' "$val"
}

# 基础设施必填（缺任一 → 硬失败）
REQUIRED_VARS="POSTGRES_PASSWORD DATABASE_URL CLIPMIND_DATA_ROOT CLIPMIND_SOURCE_DIR CLIPMIND_BIND_ADDR WEB_ORIGIN EMBEDDING_PROVIDER EMBEDDING_MODEL EMBEDDING_DIMENSION"
MISSING_REQUIRED=""
for k in $REQUIRED_VARS; do
  if [ -z "$(env_value "$k")" ]; then MISSING_REQUIRED="$MISSING_REQUIRED $k"; fi
done
if [ -n "$MISSING_REQUIRED" ]; then
  die "私密配置缺少必填变量（仅列名称，不显示值）：$MISSING_REQUIRED"
fi
echo "    必填基础设施变量：完整 ✓"

# AI 打标变量（推荐但非必填：留空=不打标，仍可用拆镜头/派生/检索）
AI_PROVIDER_VAL="$(env_value AI_PROVIDER)"
AI_VARS="AI_PROVIDER AI_BASE_URL AI_API_KEY AI_MODEL"
MISSING_AI=""
for k in $AI_VARS; do
  if [ -z "$(env_value "$k")" ]; then MISSING_AI="$MISSING_AI $k"; fi
done
AI_STATUS="complete"
if [ -z "$AI_PROVIDER_VAL" ]; then
  AI_STATUS="disabled"
  echo "    AI 打标：未启用（AI_PROVIDER 留空）—— 交付包将标注「AI 打标未启用」"
elif [ -n "$MISSING_AI" ]; then
  AI_STATUS="incomplete"
  echo "    AI 打标：已选 Provider 但缺变量（仅列名称）：$MISSING_AI —— 交付包将标注「需补配置」"
else
  echo "    AI 打标：配置完整 ✓"
fi

# 从发布包内取 VERSION（top dir 为 clipmind-nas/）
echo "==> 读取发布包版本信息"
TMP_VER="$(mktemp -d)"
trap 'rm -rf "$TMP_VER"' EXIT
tar -xzf "$RELEASE_ARCHIVE" -C "$TMP_VER" clipmind-nas/VERSION clipmind-nas/README.md clipmind-nas/CHECKSUMS.txt 2>/dev/null \
  || die "发布包内缺少 VERSION/README.md/CHECKSUMS.txt（请用 scripts/nas/package.sh 重新生成）"
VERSION_FULL="$(cat "$TMP_VER/clipmind-nas/VERSION")"
# 形如：clipmind-nas 2026-06-28 <shortsha> —— 取后两段拼出版本标签
VERSION_TAG="$(printf '%s' "$VERSION_FULL" | awk '{print $2"-"$3}' | tr -cd 'A-Za-z0-9._-')"
[ -n "$VERSION_TAG" ] || VERSION_TAG="unknown"
echo "    VERSION: $VERSION_FULL  (tag: $VERSION_TAG)"

# ---- 8. 创建（被 git 忽略的）交付目录 ----
DELIVERY="$ROOT/dist/clipmind-boss-delivery"
echo "==> 组装交付目录：$DELIVERY"
rm -rf "$DELIVERY"
mkdir -p "$DELIVERY/docs" "$DELIVERY/private"

# ---- 9+11. 复制公开内容（仅普通文件；不含 DB/视频/日志/模型/备份/git 历史）----
cp -p "$RELEASE_ARCHIVE"                  "$DELIVERY/clipmind-nas-release.tar.gz"
cp -p "$TMP_VER/clipmind-nas/VERSION"     "$DELIVERY/VERSION"
cp -p "$TMP_VER/clipmind-nas/README.md"   "$DELIVERY/README.md"
cp -p "$TMP_VER/clipmind-nas/CHECKSUMS.txt" "$DELIVERY/CHECKSUMS.txt"
for d in BOSS_QUICKSTART.md NAS_DEPLOYMENT.md CONFIGURATION.md DEMO_ACCEPTANCE_CHECKLIST.md; do
  [ -f "$ROOT/docs/$d" ] || die "缺少 docs/$d"
  cp -p "$ROOT/docs/$d" "$DELIVERY/docs/$d"
done

# ---- 10. 复制私密 .env（严格权限；绝不回显内容）----
cp -p "$PRIVATE_ENV" "$DELIVERY/private/.env"
chmod 600 "$DELIVERY/private/.env" 2>/dev/null || true

# AI 状态对应的中文提示
case "$AI_STATUS" in
  complete)   AI_NOTE="AI 打标已配置完整，可开箱使用。" ;;
  disabled)   AI_NOTE="⚠️ AI 打标未启用（AI_PROVIDER 留空）：拆镜头 / 派生 / 语义检索可用，但不会产出 AI 画面描述与标签。如需打标，请补 AI_PROVIDER / AI_BASE_URL / AI_API_KEY / AI_MODEL。" ;;
  incomplete) AI_NOTE="⚠️ 需补配置：已选 AI Provider，但 AI 相关变量不完整，AI 打标暂不可用。请补齐：$MISSING_AI" ;;
esac

# ---- private/部署前需要修改的配置.md（只写变量名与说明，不含任何值）----
cat > "$DELIVERY/private/部署前需要修改的配置.md" <<EOF
# 部署前需要由 NAS 管理员确认 / 修改的配置

> 本目录 \`private/.env\` 已含一份**真实私密配置**（口令 / 密钥），属 PRIVATE 文件。
> 安装时把它复制为部署目录下的 \`.env\` 即可：\`cp private/.env .env\`。
> **绝不**把 \`.env\` 上传 GitHub / 公开网盘；只通过安全渠道传输。

## 上 NAS 前几乎必须按本机实际修改的变量（仅列名称）

- \`CLIPMIND_SOURCE_DIR\`：你的 NAS **只读**原始素材目录（如 \`/share/video-assets\`）。
- \`CLIPMIND_DATA_ROOT\`：持久化数据根，指向**大容量可写盘**（如 \`/share/clipmind\`）。
- \`CLIPMIND_BIND_ADDR\`：端口绑定地址。仅本机=\`127.0.0.1\`；内网访问设为 NAS 内网 IP。
- \`WEB_ORIGIN\`：用户实际访问 Web 的地址（如 \`http://<NAS内网IP>:3000\`）。
- \`API_PORT\` / \`WEB_PORT\`：如与现有服务端口冲突再改。

> 数据库口令（\`POSTGRES_PASSWORD\` 与 \`DATABASE_URL\` 内嵌口令）本包已生成并保持一致，
> 一般无需改动；如需轮换，请两处同步修改为同一强口令。

## AI 打标状态

$AI_NOTE

## 详细变量说明

见 \`docs/CONFIGURATION.md\`。
EOF

# ---- 01-请先阅读.md（交付包首读，含 PRIVATE 标记与校验信息）----
cat > "$DELIVERY/01-请先阅读.md" <<EOF
# ClipMind 老板交付包 — 请先阅读

> **PRIVATE — DO NOT UPLOAD TO GITHUB**
> 本压缩包含真实配置（数据库口令、AI 密钥等），仅供私下安全交付，
> **严禁**上传 GitHub / 公开网盘 / 公共聊天群。

- 版本：\`$VERSION_FULL\`
- 发布包 \`clipmind-nas-release.tar.gz\` 的 SHA256：\`$ACTUAL_SHA\`
- AI 打标状态：$AI_NOTE

## 包内是什么

| 路径 | 说明 |
|---|---|
| \`clipmind-nas-release.tar.gz\` | 自包含部署包（无需 git，含全部代码与运维脚本） |
| \`VERSION\` / \`CHECKSUMS.txt\` | 版本号 / 发布包内文件校验和 |
| \`README.md\` | 发布包说明 |
| \`docs/BOSS_QUICKSTART.md\` | **业务负责人**快速上手（非技术） |
| \`docs/NAS_DEPLOYMENT.md\` | **NAS 管理员**部署 / 运维指南 |
| \`docs/CONFIGURATION.md\` | 配置变量逐项说明 |
| \`docs/DEMO_ACCEPTANCE_CHECKLIST.md\` | 验收清单 |
| \`private/.env\` | **真实私密配置**（PRIVATE，安装时复制为 \`.env\`） |
| \`private/部署前需要修改的配置.md\` | 上 NAS 前还需确认 / 修改的变量 |

## 怎么用（交给 NAS 管理员）

1. 在 NAS 上解压 \`clipmind-nas-release.tar.gz\` 得到 \`clipmind-nas/\` 目录。
2. 把 \`private/.env\` 复制进该目录并改名为 \`.env\`：\`cp ../private/.env ./clipmind-nas/.env\`
   （或先按 \`private/部署前需要修改的配置.md\` 核对路径 / 绑定地址再放入）。
3. 进入 \`clipmind-nas/\`，运行 \`bash scripts/nas/install.sh\`。
4. 浏览器访问 \`http://<CLIPMIND_BIND_ADDR>:<WEB_PORT>\`。

> 业务使用方法见 \`docs/BOSS_QUICKSTART.md\`；详细部署 / 备份 / 升级见 \`docs/NAS_DEPLOYMENT.md\`。
> **本系统无应用级登录鉴权，请仅在可信内网 / VPN 内使用，勿裸露公网。**
EOF

# 额外放一个显眼的 PRIVATE 标记文件
printf 'PRIVATE — DO NOT UPLOAD TO GITHUB\n含真实口令/密钥，仅供安全私下交付。\n' \
  > "$DELIVERY/PRIVATE-DO-NOT-UPLOAD.txt"

# 尽量收紧整个交付目录权限
chmod -R go-rwx "$DELIVERY" 2>/dev/null || true

# ---- 12. 生成单一压缩包（优先 zip，便于 Windows 老板；否则 tar.gz）----
echo "==> 打包老板交付压缩包"
OUT_BASE="$ROOT/dist/clipmind-boss-delivery-$VERSION_TAG"
BOSS_ARCHIVE=""
if command -v zip >/dev/null 2>&1; then
  BOSS_ARCHIVE="${OUT_BASE}.zip"
  rm -f "$BOSS_ARCHIVE"
  ( cd "$ROOT/dist" && zip -q -r -X "$(basename "$BOSS_ARCHIVE")" "clipmind-boss-delivery" )
else
  BOSS_ARCHIVE="${OUT_BASE}.tar.gz"
  rm -f "$BOSS_ARCHIVE"
  tar -C "$ROOT/dist" -czf "$BOSS_ARCHIVE" clipmind-boss-delivery
fi
chmod 600 "$BOSS_ARCHIVE" 2>/dev/null || true

# ---- 13+15. 输出路径 / 大小 / SHA256（绝不输出 .env 内容）----
BOSS_SHA="$(sha256sum "$BOSS_ARCHIVE" | awk '{print $1}')"
BOSS_SIZE="$(du -h "$BOSS_ARCHIVE" | awk '{print $1}')"
echo "$BOSS_SHA  $(basename "$BOSS_ARCHIVE")" > "${BOSS_ARCHIVE}.sha256"

echo ""
echo "================ 老板私密交付包就绪 ================"
echo "交付目录 : $DELIVERY"
echo "压缩包   : $BOSS_ARCHIVE"
echo "大小     : $BOSS_SIZE"
echo "SHA256   : $BOSS_SHA"
echo "版本     : $VERSION_FULL"
echo "AI 打标  : $AI_STATUS"
echo "---------------------------------------------------"
echo "⚠️  PRIVATE：含真实口令/密钥。绝不上传 GitHub / 公开网盘。"
echo "⚠️  只通过安全渠道把上面这个压缩包发给老板 / NAS 管理员。"
echo "BOSS_HANDOFF_OK"
