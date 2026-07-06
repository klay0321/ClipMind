#!/usr/bin/env python3
"""P2a 素材级统一搜索端到端。

链路：上传图片 → 自动 AI 理解（poster 钩子）→ 素材级文档 → 按文档原文搜到该图；
上传视频 → 自动链（拆→打标→shot 文档→聚合钩子）→ 按聚合文档搜到整条视频。
"用文档原文搜到自己"同时是搜索相关性事故（PR#34）的素材级回归。

前置：栈以 AUTO_ANALYZE_ON_SCAN=true、AUTO_AI_AFTER_SHOTS=true、AI_PROVIDER=fake、
EMBEDDING_PROVIDER=fake 运行；本机 ffmpeg。隔离：AAPS-E2E 前缀。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zlib

API = os.environ.get("API_BASE", "http://localhost:8000")
PREFIX = "AAPS-E2E"
STATE_FILE = ".aaps_e2e_state.json"
_PSQL = ["docker", "compose", "exec", "-T", "postgres",
         "psql", "-U", "clipmind", "-d", "clipmind", "-tAc"]


def _req(method, path, body=None, *, raw=None, content_type="application/json"):
    data = raw if raw is not None else (
        json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
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
    import urllib.parse
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


def wait_doc(asset_id, deadline_s=600):
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        row = psql(
            "SELECT is_searchable, coalesce(search_document,'') FROM asset_search_document "
            f"WHERE asset_id={asset_id}"
        )
        if row and row.split("|", 1)[0] == "t":
            return row.split("|", 1)[1]
        time.sleep(5)
    return None


def _query_terms(doc_text: str) -> str:
    """从文档取一段可检索原文（前 12 个词/40 字符），复现"原文搜到自己"。"""
    text = re.sub(r"\s+", " ", doc_text).strip()
    return text[:40] if text else ""


def search_assets(query, media_kind, extra=None):
    body = {"query": query, "media_kind": media_kind, "page": 1, "page_size": 20}
    if extra:
        body.update(extra)
    return jreq("POST", "/api/search/assets", body)


def run_full():
    tag = uuid.uuid4().hex[:6]

    # 1) 图片：上传 → 自动 AI（poster 钩子）→ 素材级文档 → 原文搜到自己
    sd_id, img_name = upload(
        make_png(90, 40, 40, tag), f"{PREFIX}-img-{tag}.png", "image/png"
    )
    img = wait_asset(img_name, sd_id)
    img_doc = wait_doc(img["id"])
    check(img_doc is not None, "图片素材级文档未在时限内就绪（自动 AI→文档链断）")
    print("AAPS_IMAGE_DOC_OK")

    q = _query_terms(img_doc)
    check(bool(q), "图片文档为空")
    res = search_assets(q, "image")
    ids = [it["asset_id"] for it in res["items"]]
    check(img["id"] in ids, f"图片未被自身文档原文搜到: q={q!r} ids={ids[:5]}")
    hit = next(it for it in res["items"] if it["asset_id"] == img["id"])
    check(hit["media_kind"] == "image" and hit["document_excerpt"], "图片结果字段缺失")
    print("AAPS_IMAGE_SEARCH_OK")

    # 2) 视频：上传 → 全自动链 → 聚合文档 → 原文搜到整条视频
    with tempfile.TemporaryDirectory() as td:
        vp = os.path.join(td, f"{PREFIX}-vid-{tag}.mp4")
        make_video(vp, ["red", "green"])
        with open(vp, "rb") as f:
            _, vid_name = upload(f.read(), f"{PREFIX}-vid-{tag}.mp4", "video/mp4")
    vid = wait_asset(vid_name, sd_id)
    vid_doc = wait_doc(vid["id"])
    check(vid_doc is not None, "视频聚合文档未在时限内就绪（自动链→聚合钩子断）")
    print("AAPS_VIDEO_DOC_OK")

    qv = _query_terms(vid_doc)
    resv = search_assets(qv, "video")
    idsv = [it["asset_id"] for it in resv["items"]]
    check(vid["id"] in idsv, f"整条视频未被聚合文档原文搜到: q={qv!r} ids={idsv[:5]}")
    print("AAPS_VIDEO_SEARCH_OK")

    # 3) media_kind 隔离：图片查询在 video Tab 不返回该图片
    res_cross = search_assets(q, "video")
    check(img["id"] not in [it["asset_id"] for it in res_cross["items"]],
          "media_kind 过滤失效")
    print("AAPS_KIND_FILTER_OK")

    print("AAPS_API_E2E_OK")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"tag": tag, "image_id": img["id"], "video_id": vid["id"],
                   "image_q": q, "video_q": qv}, f, ensure_ascii=False)


def run_check_persist():
    with open(STATE_FILE, encoding="utf-8") as f:
        st = json.load(f)
    res = search_assets(st["image_q"], "image")
    check(st["image_id"] in [it["asset_id"] for it in res["items"]], "重启后图片检索丢失")
    resv = search_assets(st["video_q"], "video")
    check(st["video_id"] in [it["asset_id"] for it in resv["items"]], "重启后视频检索丢失")
    print("AAPS_RESTART_PERSIST_OK")


def run_cleanup():
    psql("DELETE FROM asset_search_document WHERE asset_id IN "
         f"(SELECT id FROM asset WHERE filename LIKE '{PREFIX}%')")
    psql("DELETE FROM asset_image_analysis WHERE asset_id IN "
         f"(SELECT id FROM asset WHERE filename LIKE '{PREFIX}%')")
    psql(f"DELETE FROM asset WHERE filename LIKE '{PREFIX}%'")
    print("AAPS_CLEANUP_OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "check-persist", "cleanup"],
                        default="full")
    args = parser.parse_args()
    {"full": run_full, "check-persist": run_check_persist,
     "cleanup": run_cleanup}[args.mode]()


if __name__ == "__main__":
    main()
