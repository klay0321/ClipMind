#!/usr/bin/env python3
"""AAP 端到端：素材进来自动变可搜索（扫描→拆镜头→AI→检索文档，全程零手动点击）。

前置：栈以 AUTO_ANALYZE_ON_SCAN=true、AUTO_AI_AFTER_SHOTS=true、AI_PROVIDER=fake
启动；本机有 ffmpeg（合成小视频）。隔离：AAP-E2E 前缀。
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib

API = os.environ.get("API_BASE", "http://localhost:8000")
PREFIX = "AAP-E2E"
STATE_FILE = ".aap_e2e_state.json"
_PSQL = ["docker", "compose", "exec", "-T", "postgres",
         "psql", "-U", "clipmind", "-d", "clipmind", "-tAc"]


def _req(method, path, body=None, *, raw=None, content_type="application/json"):
    data = raw if raw is not None else (
        json.dumps(body).encode() if body is not None else None
    )
    req = urllib.request.Request(f"{API}{path}", data=data, method=method,
                                 headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            payload = resp.read()
            return resp.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        return e.code, {"_error": e.read().decode("utf-8", "replace")[:300]}


def jreq(method, path, body=None, expect=(200, 201, 202, 204), **kw):
    status, data = _req(method, path, body, **kw)
    if status not in expect:
        print(f"E2E FAIL: {method} {path} -> {status}: {data}", file=sys.stderr)
        sys.exit(1)
    return data


def check(cond, msg):
    if not cond:
        print(f"E2E FAIL: {msg}", file=sys.stderr)
        sys.exit(1)


def psql(sql):
    out = subprocess.run(_PSQL + [sql], capture_output=True, text=True, check=False,
                         encoding="utf-8", errors="replace")
    if out.returncode != 0:
        print(f"E2E FAIL: psql: {out.stderr[:200]}", file=sys.stderr)
        sys.exit(1)
    return out.stdout.strip()


def make_png(r, g, b, salt=""):
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" + bytes((r, g, b))))
            + chunk(b"IEND", b"") + salt.encode())


def make_video(path, colors, seg_seconds=2.5):
    inputs = []
    for c in colors:
        inputs += ["-f", "lavfi", "-i", f"color=c={c}:s=320x240:d={seg_seconds}:r=25"]
    filt = "".join(f"[{i}:v]" for i in range(len(colors))) + \
        f"concat=n={len(colors)}:v=1:a=0[v]"
    out = subprocess.run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", filt, "-map", "[v]",
         "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        print(f"E2E FAIL: ffmpeg 合成失败: {out.stderr[-300:]!r}", file=sys.stderr)
        sys.exit(1)


def upload(content, name, mime):
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{name}\"\r\nContent-Type: {mime}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    res = jreq("POST", "/api/uploads", raw=body,
               content_type=f"multipart/form-data; boundary={boundary}", expect=(202,))
    return int(res["source_directory_id"]), str(res["filename"])


def wait_asset(name, sd_id, deadline_s=300):
    deadline = time.time() + deadline_s
    rescan = time.time() + 45
    while time.time() < deadline:
        data = jreq("GET", f"/api/assets?page=1&page_size=50&q={urllib.parse.quote(name)}")
        for it in data.get("items", []):
            if it["filename"] == name and it["status"] in ("indexed", "shot_split", "ai_analyzing"):
                return it
        if time.time() >= rescan:
            _req("POST", f"/api/source-directories/{sd_id}/scan")
            rescan = time.time() + 45
        time.sleep(3)
    print(f"E2E FAIL: 等待素材 {name} 超时", file=sys.stderr)
    sys.exit(1)


def run_full():
    tag = uuid.uuid4().hex[:6]

    # 0) 概览配置回显：自动开关必须开启（栈 env 已设）
    ov = jreq("GET", "/api/processing/overview")
    check(ov["config"]["auto_analyze_on_scan"] is True, "AUTO_ANALYZE_ON_SCAN 未生效")
    check(ov["config"]["auto_ai_after_shots"] is True, "AUTO_AI_AFTER_SHOTS 未生效")
    print("AAP_OVERVIEW_OK")

    # 1) 图片守卫：AI 发起 422（确定性，无竞态）
    sd_id, img_name = upload(make_png(120, 30, 30, tag), f"{PREFIX}-img-{tag}.png", "image/png")
    img = wait_asset(img_name, sd_id)
    st, body = _req("POST", f"/api/assets/{img['id']}/analyze")
    check(st == 422, f"图片 AI 守卫应 422，实际 {st}: {body}")
    print("AAP_GUARD_IMAGE_OK")

    # 2) 自动链主验证：上传两段纯色视频 → 全程不点分析 → 自动变可搜索
    with tempfile.TemporaryDirectory() as td:
        vp = os.path.join(td, f"{PREFIX}-auto-{tag}.mp4")
        make_video(vp, ["red", "blue"])
        with open(vp, "rb") as f:
            _, vid_name = upload(f.read(), f"{PREFIX}-auto-{tag}.mp4", "video/mp4")
    asset = wait_asset(vid_name, sd_id)
    aid = asset["id"]

    deadline = time.time() + 600
    shots_ok = ai_ok = doc_ok = False
    while time.time() < deadline and not (shots_ok and ai_ok and doc_ok):
        if not shots_ok:
            n = psql(f"SELECT count(*) FROM shot WHERE asset_id={aid} AND status='ready'")
            if int(n or 0) > 0:
                shots_ok = True
                print("AAP_AUTO_SHOTS_OK")
        if shots_ok and not ai_ok:
            n = psql(
                "SELECT count(*) FROM ai_shot_analysis a JOIN shot s ON s.id=a.shot_id "
                f"WHERE s.asset_id={aid}"
            )
            if int(n or 0) > 0:
                ai_ok = True
                print("AAP_AUTO_AI_OK")
        if ai_ok and not doc_ok:
            n = psql(
                "SELECT count(*) FROM shot_search_document d JOIN shot s ON s.id=d.shot_id "
                f"WHERE s.asset_id={aid} AND d.is_searchable"
            )
            if int(n or 0) > 0:
                doc_ok = True
                print("AAP_AUTO_SEARCHDOC_OK")
        time.sleep(5)
    check(shots_ok and ai_ok and doc_ok,
          f"自动链未在时限内完成: shots={shots_ok} ai={ai_ok} doc={doc_ok}")
    print("AAP_AUTO_CHAIN_OK")

    # 3) 批量分析 API 语义
    # 注意：只对本脚本自己的资产提交（asset_ids），绝不对共享 uploads 目录全量
    # 提交——否则会把其他 E2E 时间窗口内的未打标镜头补打标，破坏 PR-E 等
    # 脚本"重启后排序快照一致"的持久化断言。
    st, _ = _req("POST", "/api/assets/batch-analyze", {"stages": ["shots"]})
    check(st == 422, "无显式条件应 422")
    res = jreq("POST", "/api/assets/batch-analyze",
               {"asset_ids": [aid], "stages": ["shots", "ai"]}, expect=(202,))
    for key in ("matched", "enqueued_shots", "enqueued_ai", "skipped_active",
                "skipped_ineligible", "truncated"):
        check(key in res, f"batch 响应缺 {key}")
    print("AAP_BATCH_OK")

    print("AAP_API_E2E_OK")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"tag": tag, "asset_id": aid, "sd_id": sd_id}, f)


def run_check_persist():
    with open(STATE_FILE, encoding="utf-8") as f:
        st = json.load(f)
    aid = st["asset_id"]
    n_shots = int(psql(f"SELECT count(*) FROM shot WHERE asset_id={aid} AND status='ready'") or 0)
    n_docs = int(psql(
        "SELECT count(*) FROM shot_search_document d JOIN shot s ON s.id=d.shot_id "
        f"WHERE s.asset_id={aid} AND d.is_searchable") or 0)
    check(n_shots > 0 and n_docs > 0, f"重启后自动链产物丢失: shots={n_shots} docs={n_docs}")
    ov = jreq("GET", "/api/processing/overview")
    check(ov["totals"]["searchable_docs"] >= n_docs, "重启后 overview 异常")
    print("AAP_RESTART_PERSIST_OK")


def run_cleanup():
    psql("DELETE FROM shot_search_document WHERE shot_id IN (SELECT id FROM shot WHERE asset_id IN "
         f"(SELECT id FROM asset WHERE filename LIKE '{PREFIX}%'))")
    psql("DELETE FROM ai_shot_analysis WHERE asset_id IN "
         f"(SELECT id FROM asset WHERE filename LIKE '{PREFIX}%')")
    psql(f"DELETE FROM asset WHERE filename LIKE '{PREFIX}%'")
    print("AAP_CLEANUP_OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "check-persist", "cleanup"],
                        default="full")
    args = parser.parse_args()
    {"full": run_full, "check-persist": run_check_persist,
     "cleanup": run_cleanup}[args.mode]()


if __name__ == "__main__":
    main()
