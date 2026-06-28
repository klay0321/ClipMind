# ClipMind 数据库升级（Windows PowerShell；与 db_upgrade.sh 等价）。
#
# 为什么需要本脚本：migrate 是一次性服务，`docker compose up -d` 不会重跑已成功退出的 migrate
# 容器，会把"已有数据库"的升级静默跳过。每次升级必须显式运行本脚本或等价的
# `docker compose run --rm migrate`。
#
# 用法：
#   pwsh scripts/db_upgrade.ps1
#   $env:DB_UPGRADE_DATABASE_URL="<async-url>"; pwsh scripts/db_upgrade.ps1   # 升级指定数据库
#
# 安全：只 upgrade，绝不 down -v、绝不删库。
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$runArgs = @()
if ($env:DB_UPGRADE_DATABASE_URL) {
    $runArgs += @("-e", "DATABASE_URL=$($env:DB_UPGRADE_DATABASE_URL)")
}

Write-Host "[db_upgrade] 升级数据库到 head ..."
docker compose run --rm @runArgs migrate
if ($LASTEXITCODE -ne 0) { Write-Error "migrate 失败"; exit 1 }

Write-Host "[db_upgrade] 校验当前 revision 已到 head ..."
$current = (docker compose run --rm @runArgs migrate alembic current 2>&1 | Out-String)
Write-Host $current
if ($current -match "\(head\)") {
    Write-Host "[db_upgrade] 数据库已在 head"
    Write-Host "SCRIPT_DB_UPGRADE_OK"
} else {
    Write-Error "升级后 revision 未到 head（请查看上方输出与 docs 升级章节）"
    exit 1
}
