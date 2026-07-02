#!/usr/bin/env python3
"""PR-A2 Gate B 端到端（入驻治理；纯 API + 中性合成数据，无外部依赖）。

覆盖 §十二 中性通用性验收：
创建 readiness policy → 定义必填/identity 属性 → 建产品 → 初次评估 incomplete →
补属性与合成参考图 → 重新评估 complete → 提交审核 → 批准 → 同层级混淆关系 +
distinguishing features → 改产品名 → 历史名可解析 + revision 记录 → 重启后全在。

合成数据前缀 ``PRA2B-E2E``；``--mode cleanup`` 仅清理本前缀行。
仅打印计数/状态标志，不输出文件名/密钥/公司产品名。

用法：
    API_BASE=http://localhost:8000 python scripts/ci_pr_a2b_e2e.py --mode full
    API_BASE=http://localhost:8000 python scripts/ci_pr_a2b_e2e.py --mode check-persist
    API_BASE=http://localhost:8000 python scripts/ci_pr_a2b_e2e.py --mode cleanup
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
PREFIX = "PRA2B-E2E"
_PSQL = [
    "docker", "compose", "exec", "-T", "postgres",
    "psql", "-U", "clipmind", "-d", "clipmind", "-tAc",
]


def _name(s: str) -> str:
    return f"{PREFIX}-{s}"


def _png(r: int, g: int, b: int) -> bytes:
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(
            ">I", zlib.crc32(body) & 0xFFFFFFFF
        )

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


def upload_png(target_level: str, target_id: int, png: bytes, angle: str = "front"):
    boundary = "----clipmind" + uuid.uuid4().hex
    parts = b""
    for k, v in (
        ("target_level", target_level), ("target_id", str(target_id)), ("angle", angle),
    ):
        parts += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
        ).encode()
    parts += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
        f"filename=\"{uuid.uuid4().hex}.png\"\r\nContent-Type: image/png\r\n\r\n"
    ).encode() + png + b"\r\n"
    parts += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{API}/api/product-reference-assets", data=parts, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        return json.loads(r.read())


def _url(s: str) -> str:
    return urllib.parse.quote(s)


def q(sql: str) -> str:
    out = subprocess.run([*_PSQL, sql], capture_output=True, text=True, timeout=30, check=False)
    return out.stdout.strip() if out.returncode == 0 else ""


def run_full() -> None:
    # 1. 中性产品层级 + 分类激活
    cat, _ = jreq("POST", "/api/product-categories", {"name_zh": _name("类别")})
    cid = cat["id"]
    jreq("POST", f"/api/product-categories/{cid}/status", {"status": "active"})
    fam, _ = jreq("POST", "/api/product-families", {"name_zh": _name("产品"), "category_id": cid})
    fid = fam["id"]

    # 2. 创建并激活 readiness policy（要求 2 图 + front 角度 + 1 个 identity 属性 + 主图）
    pol, _ = jreq("POST", "/api/product-readiness-policies", {
        "category_id": cid, "name": _name("策略"),
        "min_reference_count": 2, "min_identity_attribute_count": 1,
        "require_primary_reference": True, "required_angles": ["front"],
    })
    jreq("POST", f"/api/product-readiness-policies/{pol['id']}/activate")
    print("PR_A2B_READINESS_POLICY_OK")

    # 3. 必填 + identity 属性定义（active）
    d, _ = jreq("POST", "/api/product-attribute-definitions", {
        "name_zh": _name("身份属性"), "category_id": cid,
        "value_type": "text", "identity_relevant": True, "required": True,
    })
    jreq("POST", f"/api/product-attribute-definitions/{d['id']}/status", {"status": "active"})

    # 4. 初次评估 incomplete；提交被守卫拒绝
    r, _ = jreq("GET", f"/api/product-catalog/family/{fid}/readiness")
    assert r["complete"] is False and r["policy_version"] == pol["version"], r
    assert any(m["key"] == "minimum_references" for m in r["missing_items"])
    _, code = jreq(
        "POST", f"/api/product-catalog/family/{fid}/submit-review", expect=(200, 422)
    )
    assert code == 422, "不完整必须拒绝提交"

    # 5. 补资料：属性值 + 2 图（front）+ 主图
    jreq("PUT", "/api/product-attribute-values", {
        "definition_id": d["id"], "target_level": "family", "target_id": fid, "value": "样例",
    })
    first = upload_png("family", fid, _png(200, 20, 20), angle="front")["created"][0]
    upload_png("family", fid, _png(20, 200, 20), angle="front")
    jreq("POST", f"/api/product-reference-assets/{first['id']}/primary")

    # 6. 重新评估 complete → 提交 → 批准
    r2, _ = jreq("POST", f"/api/product-catalog/family/{fid}/evaluate-readiness")
    assert r2["complete"] is True and r2["score"] == 100, r2
    ob, _ = jreq("POST", f"/api/product-catalog/family/{fid}/submit-review",
                 {"actor_label": _name("运营")})
    assert ob["status"] == "ready_for_review" and ob["readiness_score"] == 100
    ap, _ = jreq("POST", f"/api/product-catalog/family/{fid}/approve",
                 {"note": "合成验收", "actor_label": _name("审核")})
    assert ap["status"] == "approved"
    print("PR_A2B_ONBOARDING_WORKFLOW_OK")

    # 7. 同层级混淆关系 + distinguishing features（反向重复 409）
    fam_b, _ = jreq("POST", "/api/product-families",
                    {"name_zh": _name("相近品"), "category_id": cid})
    bid = fam_b["id"]
    pair, _ = jreq("POST", "/api/product-confusion-pairs", {
        "target_level": "family", "left_target_id": fid, "right_target_id": bid,
        "severity": "high", "reason": "外观相近",
        "distinguishing_features": [{
            "feature": "接口结构", "left_value": "结构A", "right_value": "结构B",
            "visible_in_reference": True, "identity_relevant": True,
        }],
    })
    assert pair["left"] and pair["right"]
    _, code = jreq("POST", "/api/product-confusion-pairs", {
        "target_level": "family", "left_target_id": bid, "right_target_id": fid,
    }, expect=(201, 409))
    assert code == 409, "反向重复必须 409"
    cons, _ = jreq("GET", f"/api/product-catalog/family/{fid}/confusions")
    assert cons["total"] >= 1
    print("PR_A2B_CONFUSION_PAIR_OK")

    # 8. 改名 → 历史名可解析 + revision 记录（含 correlation）
    old_name = fam["name_zh"]
    jreq("PATCH", f"/api/product-families/{fid}", {"name_zh": _name("产品改名")})
    rr, _ = jreq("GET", f"/api/product-catalog/resolve?value={_url(old_name)}")
    assert rr["status"] == "resolved" and rr["canonical"]["id"] == fid
    revs, _ = jreq("GET", f"/api/product-catalog/family/{fid}/revisions")
    actions = {r["action"] for r in revs["items"]}
    assert {"create", "update"} <= actions, actions
    all_revs, _ = jreq("GET", "/api/catalog-revisions?entity_type=onboarding_review")
    assert all_revs["total"] >= 2  # submit + approve
    nums = [r["revision_number"] for r in revs["items"]]
    assert nums == sorted(nums, reverse=True), "revision_number 必须单调"
    print("PR_A2B_CATALOG_REVISION_OK")

    # 9. 全程零代码/零迁移/旧接口兼容
    assert jreq("GET", "/api/products")[1] == 200
    print("PR_A2B_NEW_PRODUCT_NO_CODE_CHANGE_OK")
    print("PR_A2B_E2E_OK")


def run_check_persist() -> None:
    # 重启后：approved 状态 / 混淆关系 / revision 历史 均在
    lst, _ = jreq("GET", f"/api/product-families?q={_url(_name('产品改名'))}")
    fams = [it for it in lst["items"] if it["name_zh"].startswith(PREFIX)]
    assert fams, "重启后产品丢失"
    fid = fams[0]["id"]
    ob, _ = jreq("GET", f"/api/product-catalog/family/{fid}/onboarding")
    assert ob and ob["status"] == "approved", "重启后审核状态丢失"
    cons, _ = jreq("GET", f"/api/product-catalog/family/{fid}/confusions")
    assert cons["total"] >= 1, "重启后混淆关系丢失"
    revs, _ = jreq("GET", f"/api/product-catalog/family/{fid}/revisions")
    assert revs["total"] >= 2, "重启后变更历史丢失"
    print("PR_A2B_RESTART_PERSIST_OK")


def run_cleanup() -> None:
    q(f"delete from product_confusion_pair using product_family f "
      f"where (product_confusion_pair.left_target_id=f.id or "
      f"product_confusion_pair.right_target_id=f.id) "
      f"and product_confusion_pair.target_level='family' and f.name_zh like '{PREFIX}%'")
    q(f"delete from product_onboarding_review using product_family f "
      f"where product_onboarding_review.family_id=f.id and f.name_zh like '{PREFIX}%'")
    q(f"delete from product_reference_asset using product_family f "
      f"where product_reference_asset.family_id=f.id and f.name_zh like '{PREFIX}%'")
    q(f"delete from product_attribute_value using product_family f "
      f"where product_attribute_value.family_id=f.id and f.name_zh like '{PREFIX}%'")
    q(f"delete from product_attribute_definition where name_zh like '{PREFIX}%'")
    q(f"delete from product_readiness_policy where name like '{PREFIX}%'")
    q(f"delete from product_sku where name_zh like '{PREFIX}%'")
    q(f"delete from product_variant where name_zh like '{PREFIX}%'")
    q(f"delete from product_family where name_zh like '{PREFIX}%'")
    q(f"delete from product_category where name_zh like '{PREFIX}%'")
    print(f"cleaned synthetic PR-A2B rows with prefix {PREFIX}")


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
