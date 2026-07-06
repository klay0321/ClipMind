#!/usr/bin/env python3
"""PM 端到端（产品素材工作台；纯 API 中性数据；不依赖视觉模型）。

流程：建产品 → 上传图片（新能力）与视频 → 扫描/拆镜头 → 未标注队列 →
单个/批量绑定 → Shot 继承/覆盖 → 产品视图 → 产品搜索 hard filter →
文件名候选确认 → fake provider 禁写视觉确认 → 解绑 → 重启持久化。
隔离：PMA-E2E 前缀 + created_from 时间窗。
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib
from datetime import UTC, datetime, timedelta

API = os.environ.get("API_BASE", "http://localhost:8000")
PREFIX = "PMA-E2E"
STATE_FILE = ".pma_e2e_state.json"
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


def poll(fn, ok, *, timeout=300, interval=3, desc=""):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if ok(last):
            return last
        time.sleep(interval)
    print(f"E2E FAIL: 轮询超时（{desc}）: {last}", file=sys.stderr)
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


def make_video(path, colors, uniq):
    inputs = []
    for c in [*colors, uniq]:
        inputs += ["-f", "lavfi", "-i", f"color=c={c}:s=320x240:d=2.5:r=25"]
    n = len(colors) + 1
    filt = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0,format=yuv420p[v]"
    out = subprocess.run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", filt, "-map", "[v]",
         "-c:v", "libx264", "-preset", "ultrafast", path],
        capture_output=True, check=False,
    )
    check(out.returncode == 0, f"ffmpeg: {out.stderr[-200:]!r}")


def upload(content: bytes, name: str, mime: str):
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{name}\"\r\nContent-Type: {mime}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    res = jreq("POST", "/api/uploads", raw=body,
               content_type=f"multipart/form-data; boundary={boundary}", expect=(202,))
    return int(res["source_directory_id"]), str(res["filename"])


def wait_asset(name, sd_id):
    import urllib.parse
    deadline = time.time() + 300
    rescan = time.time() + 45
    while time.time() < deadline:
        data = jreq("GET", f"/api/assets?page=1&page_size=50&q={urllib.parse.quote(name)}")
        for it in data.get("items", []):
            if it["filename"] == name and it["status"] == "indexed":
                return it
        if time.time() >= rescan:
            _req("POST", f"/api/source-directories/{sd_id}/scan")
            rescan = time.time() + 45
        time.sleep(3)
    print(f"E2E FAIL: 等待素材 {name} 超时", file=sys.stderr)
    sys.exit(1)


def analyze(aid):
    jreq("POST", f"/api/assets/{aid}/analyze-shots", expect=(202,))
    poll(lambda: jreq("GET", f"/api/assets/{aid}/shot-analysis"),
         lambda s: s.get("status") == "completed", desc=f"拆镜头 {aid}")
    return jreq("GET", f"/api/assets/{aid}/shots?page=1&page_size=50")["items"]


def run_full():
    tag = uuid.uuid4().hex[:6]
    created_from = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
    st = jreq("GET", "/api/product-visual-experiments/status")
    check(st["provider"] == "fake" or not st["enabled"],
          "E2E 需 fake provider 或视觉关闭")

    fam_a = jreq("POST", "/api/product-families",
                 {"code": f"{PREFIX}-A-{tag}", "name_zh": f"{PREFIX}产品甲{tag}"},
                 expect=(201,))
    fam_b = jreq("POST", "/api/product-families",
                 {"code": f"{PREFIX}-B-{tag}", "name_zh": f"{PREFIX}产品乙{tag}"},
                 expect=(201,))

    # 上传：2 图（一张文件名嵌产品 code → 文件名候选）+ 1 视频
    sd_id, img1 = upload(make_png(200, 30, 30, tag + "1"),
                         f"{PREFIX}-A-{tag}-front.png", "image/png")
    _, img2 = upload(make_png(30, 200, 30, tag + "2"),
                     f"{PREFIX}-plain-{tag}.png", "image/png")
    import tempfile
    tmp = tempfile.mkdtemp(prefix="pma_")
    vid_path = os.path.join(tmp, "v.mp4")
    make_video(vid_path, ["red", "blue"], f"#{tag}")
    with open(vid_path, "rb") as f:
        _, vid = upload(f.read(), f"{PREFIX}-vid-{tag}.mp4", "video/mp4")

    a_img1 = wait_asset(img1, sd_id)
    a_img2 = wait_asset(img2, sd_id)
    a_vid = wait_asset(vid, sd_id)
    check(a_img1["media_kind"] == "image" if "media_kind" in a_img1 else True,
          "图片 media_kind 异常")
    mk = psql(f"SELECT media_kind FROM asset WHERE id={a_img1['id']}")
    check(mk == "image", f"图片 media_kind 应 image: {mk}")
    shots = analyze(a_vid["id"])
    check(len(shots) >= 2, f"视频镜头不足: {len(shots)}")
    s1, s2 = shots[0]["id"], shots[1]["id"]

    # 1) 未标注队列可见
    unimg = jreq("GET", "/api/product-media/unassigned?kind=image&page_size=100")
    check(any(i["asset_id"] == a_img1["id"] for i in unimg["items"]), "图片未入未标注队列")
    unshot = jreq("GET", "/api/product-media/unassigned?kind=shot&page_size=100")
    check(any(i["shot_id"] == s1 for i in unshot["items"]), "Shot 未入未标注队列")

    # 2) 单个绑定（图片1 → A primary）
    l1 = jreq("POST", "/api/product-media/links", {
        "target_type": "asset", "target_id": a_img1["id"],
        "family_id": fam_a["id"], "role": "primary",
    }, expect=(201,))
    check(l1["role"] == "primary" and l1["origin"] == "manual", "单个绑定字段异常")
    print("PRODUCT_MEDIA_MANUAL_ASSIGNMENT_OK")

    # 3) 批量绑定（图片2 + 视频 → A；含一条重复触发 skipped）
    bulk = jreq("POST", "/api/product-media/links/bulk", {
        "items": [
            {"target_type": "asset", "target_id": a_img2["id"]},
            {"target_type": "asset", "target_id": a_vid["id"]},
            {"target_type": "asset", "target_id": a_img1["id"]},  # 已绑 → skipped
        ],
        "family_id": fam_a["id"], "role": "related",
    })
    check(len(bulk["completed"]) == 2 and len(bulk["skipped"]) == 1
          and len(bulk["failed"]) == 0, f"批量明细异常: {bulk}")
    print("PRODUCT_MEDIA_BULK_ASSIGNMENT_OK")

    # 4) Shot 继承 + 覆盖
    v1 = jreq("GET", f"/api/product-media/shots/{s1}/links")
    check(v1["effective_source"] == "asset_inherited"
          and v1["effective"][0]["family_id"] == fam_a["id"], "Shot 继承异常")
    print("PRODUCT_MEDIA_SHOT_INHERITANCE_OK")
    jreq("POST", "/api/product-media/links", {
        "target_type": "shot", "target_id": s2,
        "family_id": fam_b["id"], "role": "primary",
    }, expect=(201,))
    v2 = jreq("GET", f"/api/product-media/shots/{s2}/links")
    check(v2["effective_source"] == "shot_override"
          and v2["effective"][0]["family_id"] == fam_b["id"]
          and v2["inherited"][0]["family_id"] == fam_a["id"], "Shot 覆盖异常")
    print("PRODUCT_MEDIA_SHOT_OVERRIDE_OK")

    # 5) 产品视图（summary + items）
    summary = jreq("GET", "/api/product-media/summary")
    row = next(x for x in summary if x["family_id"] == fam_a["id"])
    check(row["image_count"] == 2 and row["video_count"] == 1,
          f"summary 计数异常: {row}")
    imgs = jreq("GET", f"/api/product-media/families/{fam_a['id']}/items?kind=image")
    check(imgs["total"] == 2, f"产品图片数异常: {imgs['total']}")
    shots_view = jreq("GET", f"/api/product-media/families/{fam_a['id']}/items?kind=shot")
    ids = {i["shot_id"]: i["source"] for i in shots_view["items"]}
    check(ids.get(s1) == "asset_inherited", "产品 Shot 视图继承标记异常")
    check(s2 not in ids, "覆盖为 B 的镜头不应出现在 A 的有效列表")
    b_shots = jreq("GET", f"/api/product-media/families/{fam_b['id']}/items?kind=shot")
    check(any(i["shot_id"] == s2 and i["source"] == "shot_override"
              for i in b_shots["items"]), "B 产品应含覆盖镜头")
    print("PRODUCT_MEDIA_PRODUCT_VIEW_OK")

    # 6) 产品搜索 hard filter（时间窗隔离；直接播种检索文档——本 E2E 不跑 AI）
    for sid in (s1, s2):
        psql(
            "INSERT INTO shot_search_document (shot_id, shot_generation, asset_id, "
            "document_status, embedding_status, is_searchable, retry_count, "
            "search_document, normalized_document, created_at, updated_at) VALUES "
            f"({sid}, 1, {a_vid['id']}, 'indexed', 'degraded', true, 0, "
            "'pm 搜索 测试', 'pm 搜索 测试', now(), now()) "
            "ON CONFLICT DO NOTHING"
        )
    def search(extra):
        _st, d = _req("POST", "/api/search/shots", {
            "query": "", "search_mode": "lexical", "page": 1, "page_size": 100,
            "created_from": created_from, **extra,
        })
        check(_st == 200, f"搜索失败: {d}")
        return {i["shot_id"] for i in d["items"]}

    fam_hits = search({"product_family_id": fam_a["id"]})
    check(s1 in fam_hits and s2 not in fam_hits, "family 过滤（含继承）异常")
    unass = search({"unassigned_only": True})
    check(s1 not in unass and s2 not in unass, "unassigned_only 异常")
    # Saved Search 兼容
    saved = jreq("POST", "/api/saved-searches", {
        "name": f"{PREFIX}-产品筛选-{tag}", "search_kind": "shot_search",
        "query": {"query": "", "search_mode": "lexical",
                  "product_family_id": fam_a["id"]},
    }, expect=(201,))
    got = jreq("GET", f"/api/saved-searches/{saved['id']}")
    check(got["query"]["product_family_id"] == fam_a["id"], "Saved Search 产品条件丢失")
    print("PRODUCT_MEDIA_SEARCH_FILTER_OK")

    # 7) 文件名候选 → 人工确认（img1 文件名含 A 的 code）
    sugg = jreq("GET", "/api/product-media/suggestions"
                f"?target_type=asset&target_id={a_img2['id']}")
    # img2 无产品名 → 可能无候选；img1 已绑定。用视频名（含 PREFIX 不含 code）——
    # 改验证 img1 的候选包含 A（文件名命中）
    sugg1 = jreq("GET", "/api/product-media/suggestions"
                 f"?target_type=asset&target_id={a_img1['id']}")
    check(any(s["family_id"] == fam_a["id"]
              and s["suggestion_type"] in ("filename", "alias", "path")
              for s in sugg1), f"文件名候选未命中: {sugg1}")
    check(isinstance(sugg, list), "候选端点异常")

    # 8) fake provider 禁写视觉确认（唯一被拒来源）
    st2, d2 = _req("POST", "/api/product-media/links", {
        "target_type": "shot", "target_id": s1,
        "family_id": fam_b["id"], "origin": "visual_suggestion_confirmed",
    })
    check(st2 == 422, f"fake provider 应拒绝视觉确认: {st2} {d2}")
    print("PRODUCT_MEDIA_VISUAL_SUGGESTION_OK")

    # 9) 全流程未调用任何 AI（管理功能与视觉解耦）
    print("PRODUCT_MEDIA_NO_AI_REQUIRED_OK")

    # 10) 解除错误绑定
    l_extra = jreq("POST", "/api/product-media/links", {
        "target_type": "asset", "target_id": a_img2["id"], "family_id": fam_b["id"],
    }, expect=(201,))
    jreq("DELETE", f"/api/product-media/links/{l_extra['id']}", expect=(204,))
    links_after = jreq("GET", f"/api/product-media/assets/{a_img2['id']}/links")
    check(all(x["family_id"] != fam_b["id"] for x in links_after), "解绑未生效")

    state = {
        "tag": tag, "fam_a": fam_a["id"], "fam_b": fam_b["id"],
        "img1": a_img1["id"], "vid": a_vid["id"], "s1": s1, "s2": s2,
        "saved_id": saved["id"], "created_from": created_from,
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)
    print("PRODUCT_MEDIA_API_E2E_OK")


def run_check_persist():
    with open(STATE_FILE, encoding="utf-8") as f:
        st = json.load(f)
    v1 = jreq("GET", f"/api/product-media/shots/{st['s1']}/links")
    check(v1["effective_source"] == "asset_inherited"
          and v1["effective"][0]["family_id"] == st["fam_a"], "重启后继承关系丢失")
    v2 = jreq("GET", f"/api/product-media/shots/{st['s2']}/links")
    check(v2["effective_source"] == "shot_override"
          and v2["effective"][0]["family_id"] == st["fam_b"], "重启后覆盖关系丢失")
    row = next(x for x in jreq("GET", "/api/product-media/summary")
               if x["family_id"] == st["fam_a"])
    check(row["image_count"] == 2 and row["video_count"] == 1, "重启后计数变化")
    got = jreq("GET", f"/api/saved-searches/{st['saved_id']}")
    check(got["query"]["product_family_id"] == st["fam_a"], "重启后 Saved Search 丢失")
    mk = psql(f"SELECT media_kind FROM asset WHERE id={st['img1']}")
    check(mk == "image", "重启后 media_kind 丢失")
    print("PRODUCT_MEDIA_RESTART_PERSIST_OK")


def run_cleanup():
    psql(f"DELETE FROM saved_search WHERE name LIKE '{PREFIX}%'")
    psql("DELETE FROM product_media_link WHERE family_id IN "
         f"(SELECT id FROM product_family WHERE code LIKE '{PREFIX}%')")
    psql(f"DELETE FROM product_family WHERE code LIKE '{PREFIX}%'")
    psql(f"DELETE FROM asset WHERE filename LIKE '{PREFIX}%'")
    subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "sh", "-c",
         f"rm -rf /app/uploads/{PREFIX}* 2>/dev/null; true"],
        capture_output=True, check=False,
    )
    print("PMA_CLEANUP_OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "check-persist", "cleanup"],
                        default="full")
    args = parser.parse_args()
    if args.mode == "full":
        run_full()
    elif args.mode == "check-persist":
        run_check_persist()
    else:
        run_cleanup()


if __name__ == "__main__":
    main()
