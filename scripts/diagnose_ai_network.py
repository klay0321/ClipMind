#!/usr/bin/env python3
"""AI Provider 网络连通性脱敏诊断（宿主机 / api 容器 / ai-worker 容器 / NAS 通用）。

定位"宿主机可达、Docker 容器不可达"类问题（典型为 Docker 子网与 Provider 私网地址重叠）。
**只读** Provider 配置，**默认脱敏**输出：scheme、脱敏 hostname、端口、地址类型、DNS 是否成功、
是否落入给定 Docker 子网（子网重叠）、TCP/TLS 连通性、代理变量是否"已配置"（不打印其值）。

绝不发送完整 AI 请求、绝不打印 API Key / Authorization / 图片 / 业务数据 / URL query。
私网 IP 仅在显式 --show-ip 时打印（供本地诊断；不要写入公开 PR / 文档）。

用法：
  python scripts/diagnose_ai_network.py                       # 脱敏诊断（读环境 / .env）
  python scripts/diagnose_ai_network.py --fail-on-overlap     # 子网重叠时返回非零
  python scripts/diagnose_ai_network.py --docker-network clipmind_default  # 读运行网络真实 CIDR
  python scripts/diagnose_ai_network.py --subnet 10.240.50.0/24 --show-ip
退出码：0 可达且无重叠；1 TCP/TLS 不可达；2 DNS 失败；3 未配置/无法解析 Base URL；
        4 子网重叠（仅 --fail-on-overlap）。
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import ssl
import sys
from urllib.parse import urlparse

DEFAULT_SUBNET = "172.28.10.0/24"


def _load_dotenv(path: str = ".env") -> None:
    """加载 .env，优先级：已存在的 os.environ（系统/命令行注入）> .env > 代码默认值。

    .env 只补充当前**不存在**的变量，绝不覆盖已注入的（与 docker compose 一致：shell env 优先）；
    文件内同名键 last-wins（后出现覆盖先前，仅限本次新增的键）。去除值的外层引号。
    """
    if not os.path.exists(path):
        return
    preexisting = set(os.environ)  # 调用前已存在的变量，本函数绝不覆盖
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if k in preexisting:
                    continue  # 系统/命令行注入优先
                os.environ[k] = v.strip().strip('"').strip("'")
    except OSError:
        pass


def _redact_host(host: str) -> str:
    if not host:
        return "(empty)"
    parts = host.split(".")
    head = parts[0]
    masked = (head[0] + "***" + head[-1]) if len(head) > 2 else "***"
    return ".".join([masked] + parts[1:]) if len(parts) > 1 else masked


def _addr_type(ip: str) -> str:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return "invalid"
    if a.is_loopback:
        return "loopback"
    if a.is_private:
        return "private"
    return "public"


def _resolve_all(host: str) -> list[str]:
    """host 的全部 IPv4/IPv6 地址（去重）；解析失败返回空列表。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    out: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in out:
            out.append(ip)
    return out


def _addrs_in_subnet(addrs: list[str], cidr: str | None) -> bool:
    """addrs 中任一地址是否落入 cidr（版本一致才比较）。cidr 非法/为空 → False。"""
    if not cidr:
        return False
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False
    for ip in addrs:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.version == net.version and a in net:
            return True
    return False


def _docker_subnet(network_name: str | None) -> str | None:
    """重叠检查所用的 Docker CIDR：优先读运行中的 docker 网络，回退到 CLIPMIND_DOCKER_SUBNET。"""
    if network_name:
        try:
            import subprocess  # noqa: PLC0415 - 仅在显式指定网络时才用

            r = subprocess.run(  # noqa: S603,S607 - 固定参数、无 shell、无外部输入
                [
                    "docker", "network", "inspect", network_name,
                    "--format", "{{range .IPAM.Config}}{{.Subnet}}{{end}}",
                ],
                capture_output=True, text=True, timeout=10, check=False,
            )
            cidr = (r.stdout or "").strip()
            if cidr:
                return cidr
        except (OSError, ValueError):
            pass
    return os.environ.get("CLIPMIND_DOCKER_SUBNET") or DEFAULT_SUBNET


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subnet", help="显式 Docker CIDR（覆盖自动来源），用于重叠判断")
    ap.add_argument("--docker-network", help="读取该运行中 docker 网络的真实 CIDR 做重叠判断")
    ap.add_argument("--fail-on-overlap", action="store_true", help="子网重叠时返回非零(4)")
    ap.add_argument("--show-ip", action="store_true", help="显示解析 IP（仅本地诊断）")
    ap.add_argument("--timeout", type=float, default=6.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    _load_dotenv()
    base = (os.environ.get("AI_BASE_URL") or "").strip()
    if not base:
        print("未配置 AI_BASE_URL（请在环境或 .env 提供）", file=sys.stderr)
        return 3

    u = urlparse(base if "://" in base else "https://" + base)
    host = u.hostname or ""
    port = u.port or (443 if u.scheme == "https" else 80)
    if not host:
        print(
            "AI_BASE_URL 解析不出 hostname（请检查是否含引号/行内注释/缺少 scheme）",
            file=sys.stderr,
        )
        return 3

    # 重叠检查用的 CIDR：--subnet 显式 > --docker-network 实际 > CLIPMIND_DOCKER_SUBNET/默认
    cidr = args.subnet or _docker_subnet(args.docker_network)

    rep: dict = {
        "scheme": u.scheme,
        "host_redacted": _redact_host(host),
        "port": port,
        "dns": None,
        "address_type": None,
        "docker_subnet": cidr,
        "subnet_overlap": None,
        "tcp": None,
        "tls": None,
        "proxy": {
            k: ("configured" if os.environ.get(k) or os.environ.get(k.upper()) else "-")
            for k in ("http_proxy", "https_proxy", "no_proxy")
        },
    }

    addrs = _resolve_all(host)
    if not addrs:
        rep["dns"] = "fail"
        _emit(rep, args)
        return 2
    rep["dns"] = "ok"
    rep["address_type"] = _addr_type(addrs[0])
    rep["subnet_overlap"] = _addrs_in_subnet(addrs, cidr)
    if args.show_ip:
        rep["resolved_ips"] = addrs

    rc = 0
    # TCP + TLS（不发请求体、不带任何 header / key）
    try:
        s = socket.create_connection((host, port), timeout=args.timeout)
        rep["tcp"] = "ok"
        if u.scheme == "https":
            try:
                ctx = ssl.create_default_context()
                with ctx.wrap_socket(s, server_hostname=host) as ts:
                    rep["tls"] = "ok"
                    _ = ts.version()
            except ssl.SSLError as e:
                rep["tls"] = f"fail:{type(e).__name__}"
                rc = 1
            finally:
                try:
                    s.close()
                except OSError:
                    pass
        else:
            s.close()
    except OSError as e:
        rep["tcp"] = f"fail:{type(e).__name__}:errno={getattr(e, 'errno', '')}"
        rc = 1

    _emit(rep, args)
    if args.fail_on_overlap and rep["subnet_overlap"]:
        return 4
    return rc


def _emit(rep: dict, args) -> None:
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return
    print("AI Provider 网络诊断（脱敏）")
    keys = [
        "scheme", "host_redacted", "port", "dns", "address_type",
        "docker_subnet", "subnet_overlap", "tcp", "tls",
    ]
    for k in keys:
        print(f"  {k:14}: {rep.get(k)}")
    if "resolved_ips" in rep:
        print(f"  {'resolved_ips':14}: {rep['resolved_ips']}")
    print(f"  {'proxy':14}: {rep['proxy']}")


if __name__ == "__main__":
    raise SystemExit(main())
