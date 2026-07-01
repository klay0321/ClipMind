#!/usr/bin/env python3
"""PR-A2 Gate A 端到端（动态属性 + 参考图库；纯 API + 中性合成数据，无外部依赖）。

验证真实 API + 数据库 + 重启持久化：
新建 Category→Family→Variant→SKU（零代码/零迁移）→ 定义动态属性（全 value_type）→
填属性值（含 measurement/enum/multi_enum）→ 上传合成参考图（多角度）→ 设主图/改角度 →
更名属性定义后旧值仍可读 → tree/search/resolve 与旧 /api/products 兼容不受影响 → 重启后仍在。

合成数据前缀 ``PRA2A-E2E`` 隔离；参考图用**内存合成 PNG**（不提交任何真实图片）。
``--mode cleanup`` 仅清理本前缀行。仅打印计数/状态标志，不输出文件名/密钥/公司产品名。

用法：
    API_BASE=http://localhost:8000 python scripts/ci_pr_a2a_e2e.py --mode full
    API_BASE=http://localhost:8000 python scripts/ci_pr_a2a_e2e.py --mode check-persist
    API_BASE=http://localhost:8000 python scripts/ci_pr_a2a_e2e.py --mode cleanup
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib

API = os.environ.get("API_BASE", "http://localhost:8000")
PREFIX = "PRA2A-E2E"
_PSQL = ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "clipmind", "-d", "clipmind", "-tAc"]


def _name(s: str) -> str:
    return f"{PREFIX}-{s}"


def _png(r: int, g: int, b: int) -> bytes:
    """合成有效 1×1 RGB PNG（不同颜色→不同 sha256）。"""
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00" + bytes([r, g, b])))
    return sig + ihdr + idat + chunk(b"IEND", b"")


def jreq(method: str, path: str, body=None, expect=(200, 201, 202, 204)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    if code not in expect:
        raise SystemExit(f"{method} {path} -> {code}: {raw[:300]!r}")
    return (json.loads(raw) if raw else None), code


def upload(path: str, fields: dict, files: list[tuple[str, str, bytes]], expect=(200, 201)):
    """multipart/form-data 上传（手写，无外部依赖）。files: [(filename, content_type, bytes)]。"""
    boundary = "----clipmind" + uuid.uuid4().hex
    parts = b""
    for k, v in fields.items():
        parts += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
        ).encode()
    for filename, ct, data in files:
        parts += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
            f"filename=\"{filename}\"\r\nContent-Type: {ct}\r\n\r\n"
        ).encode() + data + b"\r\n"
    parts += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{API}{path}", data=parts, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    if code not in expect:
        raise SystemExit(f"POST {path} (multipart) -> {code}: {raw[:300]!r}")
    return json.loads(raw), code


def get_status(path: str) -> int:
    """GET 仅取状态码（用于返回二进制的 /file、/thumbnail 端点，不解析 JSON）。"""
    req = urllib.request.Request(f"{API}{path}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _url(s: str) -> str:
    return urllib.parse.quote(s)


def q(sql: str) -> str:
    out = subprocess.run([*_PSQL, sql], capture_output=True, text=True, timeout=30, check=False)
    return out.stdout.strip() if out.returncode == 0 else ""


def run_full() -> None:
    # 0. 旧扁平产品 API 兼容基线
    legacy, _ = jreq("POST", "/api/products", {"name": _name("legacy")})
    assert jreq("GET", "/api/products")[1] == 200
    tree0, _ = jreq("GET", "/api/product-catalog/tree?include_archived=true")

    # 1. 新建 Category→Family→Variant→SKU（激活 category 便于后续）
    cat, _ = jreq("POST", "/api/product-categories", {"name_zh": _name("类别")})
    cid = cat["id"]
    jreq("POST", f"/api/product-categories/{cid}/status", {"status": "active"})
    fam, _ = jreq("POST", "/api/product-families", {"name_zh": _name("产品"), "category_id": cid})
    fid = fam["id"]
    var, _ = jreq("POST", "/api/product-variants", {"family_id": fid, "name_zh": _name("型号")})
    vid = var["id"]
    sku, _ = jreq("POST", "/api/product-skus", {"family_id": fid, "name_zh": _name("SKU")})
    sid = sku["id"]

    # 2. 定义动态属性（全 value_type，零迁移）
    defs = {}
    specs = [
        ("text", {}), ("number", {"validation_rules": {"min": 0, "max": 100}}),
        ("boolean", {}), ("date", {}),
        ("enum", {"allowed_values": ["a", "b", "c"]}),
        ("multi_enum", {"allowed_values": ["x", "y", "z"]}),
        ("measurement", {"unit": "mm"}),
    ]
    for vt, extra in specs:
        d, _ = jreq("POST", "/api/product-attribute-definitions",
                    {"name_zh": _name(f"属性{vt}"), "category_id": cid, "value_type": vt, **extra})
        defs[vt] = d["id"]
    print("PR_A2A_DYNAMIC_ATTRIBUTE_DEFS_OK")

    # 3. 填属性值（family），并验证 enum 非法值被拒
    vals = {
        "text": "示例", "number": 42, "boolean": True, "date": "2026-07-01",
        "enum": "a", "multi_enum": ["x", "z"], "measurement": 12.5,
    }
    for vt, v in vals.items():
        jreq("PUT", "/api/product-attribute-values",
             {"definition_id": defs[vt], "target_level": "family", "target_id": fid, "value": v})
    _, code = jreq("PUT", "/api/product-attribute-values",
                   {"definition_id": defs["enum"], "target_level": "family", "target_id": fid,
                    "value": "不在允许内"}, expect=(200, 422))
    assert code == 422, "enum 非法值必须 422"
    # variant / sku 也可绑定
    jreq("PUT", "/api/product-attribute-values",
         {"definition_id": defs["text"], "target_level": "variant", "target_id": vid, "value": "型号值"})
    jreq("PUT", "/api/product-attribute-values",
         {"definition_id": defs["text"], "target_level": "sku", "target_id": sid, "value": "SKU值"})
    print("PR_A2A_DYNAMIC_ATTRIBUTE_OK")

    # 4. 上传合成参考图（family 多角度 + variant + sku），设主图/改角度
    r1, _ = upload("/api/product-reference-assets",
                   {"target_level": "family", "target_id": fid, "angle": "front"},
                   [("a.png", "image/png", _png(200, 10, 10))])
    a_id = r1["created"][0]["id"]
    upload("/api/product-reference-assets",
           {"target_level": "family", "target_id": fid, "angle": "back"},
           [("b.png", "image/png", _png(10, 200, 10))])
    # 重复图 -> errors
    rdup, _ = upload("/api/product-reference-assets",
                     {"target_level": "family", "target_id": fid},
                     [("a.png", "image/png", _png(200, 10, 10))])
    assert not rdup["created"] and rdup["errors"], "同目标重复图必须进 errors"
    upload("/api/product-reference-assets",
           {"target_level": "variant", "target_id": vid}, [("v.png", "image/png", _png(0, 0, 200))])
    upload("/api/product-reference-assets",
           {"target_level": "sku", "target_id": sid}, [("s.png", "image/png", _png(50, 50, 50))])
    jreq("POST", f"/api/product-reference-assets/{a_id}/primary")
    jreq("PATCH", f"/api/product-reference-assets/{a_id}", {"angle": "detail"})
    # 文件与缩略可服务（返回二进制，仅校验状态码）
    assert get_status(f"/api/product-reference-assets/{a_id}/file") == 200
    assert get_status(f"/api/product-reference-assets/{a_id}/thumbnail") == 200
    print("PR_A2A_REFERENCE_LIBRARY_OK")

    # 5. 更名属性定义后旧值仍可读
    jreq("PATCH", f"/api/product-attribute-definitions/{defs['text']}", {"name_zh": _name("属性text改")})
    fam_vals, _ = jreq("GET", f"/api/product-attribute-values?target_level=family&target_id={fid}")
    assert any(v["definition_id"] == defs["text"] and v["value_text"] == "示例" for v in fam_vals), \
        "更名定义后旧属性值应仍可读"

    # 6. profile 真实完整度 + 参考图计数
    prof, _ = jreq("GET", f"/api/product-catalog/family/{fid}/profile")
    assert prof["reference_total"] == 2 and prof["ai_recognition_enabled"] is False
    print("PR_A2A_NEW_PRODUCT_NO_CODE_CHANGE_OK")

    # 7. 旧 API 兼容不受影响
    assert jreq("GET", "/api/products")[1] == 200
    assert any(p["id"] == legacy["id"] for p in jreq("GET", "/api/products")[0])
    tree1, _ = jreq("GET", "/api/product-catalog/tree?include_archived=true")
    assert len(tree1) >= len(tree0)
    rr, _ = jreq("GET", f"/api/product-catalog/resolve?value={_url(fam['code'])}")
    assert rr["status"] == "resolved" and rr["canonical"]["id"] == fid
    print("PR_A2A_LEGACY_PRODUCT_COMPAT_OK")

    print("PR_A2A_E2E_OK")


def run_check_persist() -> None:
    # 重启后：新建 family 仍在、属性值仍可读、参考图仍可服务
    lst, _ = jreq("GET", f"/api/product-families?q={_url(_name('产品'))}")
    fams = [it for it in lst["items"] if it["name_zh"].startswith(PREFIX)]
    assert fams, "重启后新建产品丢失"
    fid = fams[0]["id"]
    vals, _ = jreq("GET", f"/api/product-attribute-values?target_level=family&target_id={fid}")
    assert vals, "重启后属性值丢失"
    refs, _ = jreq("GET", f"/api/product-reference-assets?target_level=family&target_id={fid}")
    assert refs, "重启后参考图丢失"
    assert get_status(f"/api/product-reference-assets/{refs[0]['id']}/file") == 200, "重启后参考图文件丢失"
    # 旧扁平产品仍在
    assert any(p["name"].startswith(PREFIX) for p in jreq("GET", "/api/products")[0])
    print("PR_A2A_RESTART_PERSIST_OK")


def run_cleanup() -> None:
    q(f"delete from product_reference_asset using product_family f where product_reference_asset.family_id=f.id and f.name_zh like '{PREFIX}%'")
    q(f"delete from product_attribute_value using product_family f where product_attribute_value.family_id=f.id and f.name_zh like '{PREFIX}%'")
    q(f"delete from product_attribute_definition where name_zh like '{PREFIX}%'")
    q(f"delete from product_sku where name_zh like '{PREFIX}%'")
    q(f"delete from product_variant where name_zh like '{PREFIX}%'")
    q(f"delete from product_family where name_zh like '{PREFIX}%'")
    q(f"delete from product_category where name_zh like '{PREFIX}%'")
    q(f"delete from product where name like '{PREFIX}%'")
    print(f"cleaned synthetic PR-A2A rows with prefix {PREFIX}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "check-persist", "cleanup"], required=True)
    args = ap.parse_args()
    if args.mode == "full":
        run_full()
    elif args.mode == "check-persist":
        run_check_persist()
    else:
        run_cleanup()


if __name__ == "__main__":
    main()
    sys.exit(0)
