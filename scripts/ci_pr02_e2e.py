#!/usr/bin/env python3
"""PR-02 Docker 端到端断言脚本（仅标准库，供 CI 的 docker-e2e job 使用）。

针对已 `docker compose up` 的运行栈，通过真实 API 走通：
创建源目录 → 扫描 → 等素材 indexed → 镜头分析 → 等成功 → 校验镜头/关键帧/缩略图/
代理（含 HTTP Range 206）→ 导出片段并下载 → 重分析校验不重复且代次增长。

不包含任何真实凭据或公司素材；源目录为容器内只读 /app/source。

用法：
  python scripts/ci_pr02_e2e.py --mode full          # 完整 E2E
  python scripts/ci_pr02_e2e.py --mode check-persist  # 仅校验记录持久化（重启后）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("API_BASE", "http://localhost:8000")


def _req(method: str, path: str, body=None, headers=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            raw = resp.read()
            return resp.status, dict(resp.headers), raw
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def jreq(method: str, path: str, body=None, expect=(200, 201, 202)):
    status, _, raw = _req(method, path, body)
    if status not in expect:
        fail(f"{method} {path} -> {status}, 期望 {expect}: {raw[:300]!r}")
    return json.loads(raw) if raw else {}


def fail(msg: str):
    print(f"E2E FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def poll(fn, ok, *, timeout=180, interval=3, desc=""):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if ok(last):
            return last
        time.sleep(interval)
    fail(f"轮询超时（{desc}），最后状态：{last}")


def full() -> None:
    # 1) 源目录（容器逻辑路径 /app/source，强制只读）
    sd = jreq("POST", "/api/source-directories", {
        "name": "ci-e2e", "mount_path": "/app/source",
        "recursive": True, "include_extensions": ["mp4", "mov"],
    }, expect=(201,))
    sd_id = sd["id"]
    print(f"[1] 源目录 id={sd_id} read_only={sd.get('read_only')}")

    # 2) 扫描
    jreq("POST", f"/api/source-directories/{sd_id}/scan", expect=(202,))
    st = poll(lambda: jreq("GET", f"/api/source-directories/{sd_id}/status"),
              lambda s: s["scan_status"] in ("completed", "failed"),
              desc="扫描完成")
    if st["scan_status"] != "completed":
        fail(f"扫描未成功：{st}")
    print(f"[2] 扫描完成：{st.get('latest_run', {})}")

    # 3) 找到一个 indexed 素材
    assets = jreq("GET", "/api/assets?page=1&page_size=50")["items"]
    indexed = [a for a in assets if a["status"] in ("indexed", "shot_split")]
    if not indexed:
        fail(f"无 indexed 素材：{[a['status'] for a in assets]}")
    asset = indexed[0]
    aid = asset["id"]
    print(f"[3] 素材 id={aid} file={asset['filename']} status={asset['status']}")

    # 4) 镜头分析
    jreq("POST", f"/api/assets/{aid}/analyze-shots", expect=(202,))
    an = poll(lambda: jreq("GET", f"/api/assets/{aid}/shot-analysis"),
              lambda s: s.get("status") in ("completed", "failed"),
              desc="镜头分析完成")
    if an["status"] != "completed":
        fail(f"镜头分析失败：{an}")
    gen1 = an["generation"]
    print(f"[4] 镜头分析完成 generation={gen1} shots={an['shot_count']}")

    # 5) 至少一个 Shot
    shots = jreq("GET", f"/api/assets/{aid}/shots")
    if shots["total"] < 1:
        fail("未生成任何镜头")
    shot = shots["items"][0]
    sid = shot["id"]
    print(f"[5] 镜头数={shots['total']}，首镜头 id={sid} {shot['start_time']}-{shot['end_time']}")

    # 6) 关键帧 / 缩略图
    for kind in ("keyframe", "thumbnail"):
        s, h, _ = _req("GET", f"/api/shots/{sid}/{kind}")
        if s != 200 or "image/webp" not in h.get("Content-Type", ""):
            fail(f"{kind} 异常 status={s} ct={h.get('Content-Type')}")
    print("[6] 关键帧/缩略图 OK (image/webp)")

    # 7) 代理普通响应
    s, h, _ = _req("GET", f"/api/shots/{sid}/preview")
    if s != 200 or "video/mp4" not in h.get("Content-Type", ""):
        fail(f"代理普通响应异常 status={s}")
    print(f"[7] 代理普通响应 OK accept-ranges={h.get('Accept-Ranges')}")

    # 8) 代理 Range -> 206 + Content-Range
    s, h, body = _req("GET", f"/api/shots/{sid}/preview", headers={"Range": "bytes=0-1"})
    if s != 206 or not h.get("Content-Range", "").startswith("bytes 0-1/"):
        fail(f"Range 未返回 206/Content-Range：status={s} cr={h.get('Content-Range')}")
    print(f"[8] 代理 Range OK 206 Content-Range={h.get('Content-Range')}")

    # 9) 导出片段并下载
    eid = jreq("POST", f"/api/shots/{sid}/export", {"mode": "reencode"}, expect=(202,))["export_id"]
    ex = poll(lambda: jreq("GET", f"/api/exports/{eid}"),
              lambda e: e["status"] in ("completed", "failed"),
              desc="导出完成")
    if ex["status"] != "completed":
        fail(f"导出失败：{ex}")
    s, h, body = _req("GET", f"/api/exports/{eid}/download")
    if s != 200 or len(body) == 0:
        fail(f"下载异常 status={s} len={len(body)}")
    print(f"[9] 导出+下载 OK ({len(body)} 字节) source_filename={ex['source_filename']}")

    # 10) 重分析：代次增长、镜头不重复
    jreq("POST", f"/api/assets/{aid}/analyze-shots", expect=(202,))
    an2 = poll(lambda: jreq("GET", f"/api/assets/{aid}/shot-analysis"),
               lambda s: s.get("status") in ("completed", "failed") and s.get("generation", 0) > gen1,
               desc="重分析完成")
    if an2["status"] != "completed" or an2["generation"] <= gen1:
        fail(f"重分析异常：{an2}")
    shots2 = jreq("GET", f"/api/assets/{aid}/shots")
    if shots2["total"] != shots["total"]:
        fail(f"重分析后镜头数变化（应稳定）：{shots['total']} -> {shots2['total']}")
    print(f"[10] 重分析 OK generation {gen1}->{an2['generation']} 镜头数稳定={shots2['total']}")

    print("E2E_OK")


def check_persist() -> None:
    """重启后校验：记录仍在（至少一个素材已拆镜头且有 ready 镜头）。"""
    assets = jreq("GET", "/api/assets?page=1&page_size=50")["items"]
    withshots = [a for a in assets if a.get("shot_count", 0) > 0]
    if not withshots:
        fail("重启后无任何含镜头的素材")
    a = withshots[0]
    shots = jreq("GET", f"/api/assets/{a['id']}/shots")
    if shots["total"] < 1:
        fail("重启后镜头记录丢失")
    print(f"PERSIST_OK 素材 {a['id']} 镜头数={shots['total']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "check-persist"], default="full")
    args = ap.parse_args()
    if args.mode == "full":
        full()
    else:
        check_persist()


if __name__ == "__main__":
    main()
