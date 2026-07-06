#!/usr/bin/env python3
"""OPS 端到端（分组审核→批量确认→统计→撤销→恢复→审计→重启保持）。

隔离：POPS-E2E 前缀。不依赖视觉模型（fake/关闭均可）。
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
import urllib.parse
import urllib.request
import uuid
import zlib

API = os.environ.get("API_BASE", "http://localhost:8000")
PREFIX = "POPS-E2E"
STATE_FILE = ".pops_e2e_state.json"
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


def upload(content, name, mime):
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{name}\"\r\nContent-Type: {mime}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    res = jreq("POST", "/api/uploads", raw=body,
               content_type=f"multipart/form-data; boundary={boundary}", expect=(202,))
    return int(res["source_directory_id"]), str(res["filename"])


def wait_asset(name, sd_id):
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


def run_full():
    tag = uuid.uuid4().hex[:6]
    fam = jreq("POST", "/api/product-families",
               {"code": f"{PREFIX}-G-{tag}", "name_zh": f"{PREFIX}分组产品{tag}"},
               expect=(201,))
    # 3 张文件名含产品 code 的图（同一建议组）+ 1 张无候选图
    names = []
    sd_id = None
    for i in range(3):
        sd_id, n = upload(make_png(200, 30 + i, 30, f"{tag}{i}"),
                          f"{PREFIX}-G-{tag}-img{i}.png", "image/png")
        names.append(n)
    _, plain = upload(make_png(30, 30, 200, tag), f"{PREFIX}-none-{tag}.png", "image/png")
    for n in names:
        wait_asset(n, sd_id)
    wait_asset(plain, sd_id)

    # 1) 分组：建议产品组含 3 项 + 无候选桶存在
    groups = jreq("GET", "/api/product-media/unassigned/groups"
                  "?kind=image&group_by=suggested_family")
    gmap = {g["key"]: g for g in groups["groups"]}
    fg = gmap.get(f"family:{fam['id']}")
    check(fg and fg["count"] == 3 and len(fg["targets"]) == 3,
          f"建议组异常: {fg and fg['count']}")
    check(fg["suggested"][0]["family_id"] == fam["id"], "组级建议缺失")
    check("none" in gmap, "无候选桶缺失")
    print("POPS_GROUPED_QUEUE_OK")

    # 2) 整组批量确认（显式 targets；排除 1 项模拟异常剔除）
    targets = fg["targets"][:2]  # 模拟排除第 3 项
    bulk = jreq("POST", "/api/product-media/links/bulk", {
        "items": targets, "family_id": fam["id"], "role": "related",
        "origin": "path_or_filename_confirmed",
    })
    op_id = bulk["operation_id"]
    check(len(bulk["completed"]) == 2 and op_id, f"批量结果异常: {bulk}")
    print("POPS_GROUP_CONFIRM_OK")

    # 3) 统计更新 + 覆盖状态
    row = next(x for x in jreq("GET", "/api/product-media/summary")
               if x["family_id"] == fam["id"])
    check(row["image_count"] == 2, f"统计未更新: {row['image_count']}")
    check("缺视频" in row["coverage_gaps"] and row["coverage_status"] != "资料较完整",
          f"覆盖状态异常: {row}")
    print("POPS_COVERAGE_OK")

    # 4) 其中一条后续修改（设主）→ 撤销只删未修改的
    modified_link = bulk["completed"][0]["link_id"]
    jreq("PATCH", f"/api/product-media/links/{modified_link}", {"role": "primary"})
    undo = jreq("POST", f"/api/product-media/operations/{op_id}/undo")
    check(undo["removed_count"] == 1 and undo["kept_count"] == 1,
          f"撤销明细异常: {undo}")
    row2 = next(x for x in jreq("GET", "/api/product-media/summary")
                if x["family_id"] == fam["id"])
    check(row2["image_count"] == 1, "撤销后统计未恢复")
    # 重复撤销 409；审计含 undo 事件
    st2, _ = _req("POST", f"/api/product-media/operations/{op_id}/undo")
    check(st2 == 409, "重复撤销应 409")
    ops = jreq("GET", "/api/product-media/operations")
    kinds = {o["kind"] for o in ops["items"][:5]}
    check("undo" in kinds and "bulk_link" in kinds, "审计事件缺失")
    orig = next(o for o in ops["items"] if o["id"] == op_id)
    check(orig["undone_at"] and not orig["undoable"], "原操作撤销标记异常")
    print("POPS_UNDO_OK")
    print("POPS_AUDIT_OK")
    print("POPS_API_E2E_OK")

    state = {"tag": tag, "fam": fam["id"], "op_id": op_id,
             "kept_link": modified_link}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def run_check_persist():
    with open(STATE_FILE, encoding="utf-8") as f:
        st = json.load(f)
    row = next(x for x in jreq("GET", "/api/product-media/summary")
               if x["family_id"] == st["fam"])
    check(row["image_count"] == 1, "重启后统计变化")
    ops = jreq("GET", "/api/product-media/operations")
    orig = next(o for o in ops["items"] if o["id"] == st["op_id"])
    check(orig["undone_at"] is not None, "重启后审计丢失")
    links = jreq("GET", "/api/product-media/operations")
    check(links["total"] >= 2, "重启后操作历史缺失")
    print("POPS_RESTART_PERSIST_OK")


def run_cleanup():
    psql("DELETE FROM product_media_operation WHERE family_id IN "
         f"(SELECT id FROM product_family WHERE code LIKE '{PREFIX}%')")
    psql("DELETE FROM product_media_link WHERE family_id IN "
         f"(SELECT id FROM product_family WHERE code LIKE '{PREFIX}%')")
    psql(f"DELETE FROM product_family WHERE code LIKE '{PREFIX}%'")
    psql(f"DELETE FROM asset WHERE filename LIKE '{PREFIX}%'")
    print("POPS_CLEANUP_OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "check-persist", "cleanup"],
                        default="full")
    args = parser.parse_args()
    {"full": run_full, "check-persist": run_check_persist,
     "cleanup": run_cleanup}[args.mode]()


if __name__ == "__main__":
    main()
