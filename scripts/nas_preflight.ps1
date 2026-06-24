# ClipMind NAS 部署前环境预检（模板，PowerShell）。
# 仅做本机环境检查，不连接、不登录、不修改任何真实 NAS。
# 正式部署前请结合 docs/NAS_DEPLOYMENT_CHECKLIST.md 人工确认全部事项。

Write-Output "=== ClipMind NAS 预检 ==="

Write-Output "--- CPU 架构 ---"
Write-Output $env:PROCESSOR_ARCHITECTURE

Write-Output "--- 操作系统 ---"
try { (Get-CimInstance Win32_OperatingSystem).Caption } catch { Write-Output "无法获取系统信息" }

Write-Output "--- Docker ---"
if (Get-Command docker -ErrorAction SilentlyContinue) { docker --version } else { Write-Output "未安装 Docker" }

Write-Output "--- Docker Compose ---"
try { docker compose version } catch { Write-Output "未检测到 docker compose 插件" }

Write-Output "--- 内存（建议 >= 8GB，推荐 16GB）---"
try {
  $mem = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
  Write-Output ("总内存: {0:N1} GB" -f ($mem / 1GB))
} catch { Write-Output "无法获取内存信息" }

Write-Output "--- 磁盘可用空间 ---"
try { Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}} } catch { }

Write-Output "--- FFmpeg/FFprobe ---"
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { (ffmpeg -version)[0] } else { Write-Output "未安装 ffmpeg（容器内置，本机可选）" }
if (Get-Command ffprobe -ErrorAction SilentlyContinue) { (ffprobe -version)[0] } else { Write-Output "未安装 ffprobe（容器内置，本机可选）" }

Write-Output ""
Write-Output "提醒："
Write-Output "  1) 原始素材目录必须以只读方式挂载（/nas/source:/app/source:ro）。"
Write-Output "  2) 系统数据目录可读写（/nas/clipmind-data:/app/data:rw）。"
Write-Output "  3) 不要把 NAS 用户名/密码/IP/密钥写入代码或 Git。"
Write-Output "  4) 当前为本地模拟验证，未进行真实 NAS 部署。"
