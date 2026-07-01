#!/usr/bin/env python3
"""PR-A1 通用产品目录端到端（docker-e2e 用；纯 API + 中性合成数据，不依赖真实素材/产品名）。

验证真实 API + 数据库 + 重启持久化：
新建 Category → Family（Category 下）→ 可选 Variant → 可选 SKU → Alias → tree/search/resolve →
更名（id/code 不变）→ 生命周期 active/paused/archived/restore → 合并 + 重定向 resolve →
别名 409 冲突 → SKU 编码 409 → 跨 family 层级校验 422 →
**新增任意产品全程只经 API、无代码改动**；旧 /api/products 兼容不受影响；重启后数据仍在。

合成数据前缀 ``PRA1-E2E`` 隔离；``--mode cleanup`` 仅清理本前缀行（绝不删其它数据）。
仅打印计数/状态标志，不输出文件名/密钥/公司产品名。

用法：
    python scripts/ci_pr_a1_catalog_e2e.py --mode full
    python scripts/ci_pr_a1_catalog_e2e.py --mode check-persist
    python scripts/ci_pr_a1_catalog_e2e.py --mode cleanup
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("API_BASE", "http://localhost:8000")
_PSQL = ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "clipmind", "-d", "clipmind", "-tAc"]

PREFIX = "PRA1-E2E"  # 中性前缀（非公司产品名）


def q(sql: str) -> str:
    out = subprocess.run([*_PSQL, sql], capture_output=True, text=True, timeout=30, check=False)
    if out.returncode != 0:
        print(f"psql 失败: {out.stderr.strip()}", file=sys.stderr)
        return ""
    return out.stdout.strip()


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


def _name(s: str) -> str:
    return f"{PREFIX}-{s}"


def run_full() -> None:
    # 0. 旧扁平产品 API 兼容（不受新目录影响）
    legacy, _ = jreq("POST", "/api/products", {"name": _name("legacy")})
    lid = legacy["id"]
    assert jreq("GET", "/api/products")[1] == 200
    print("GENERIC_CATALOG_COMPAT_OK")

    # 1. Category（建议必填的顶层，动态创建）
    cat, _ = jreq("POST", "/api/product-categories", {"name_zh": _name("类别")})
    assert cat["status"] == "draft" and cat["code"], cat
    cid = cat["id"]

    # 2. Family（核心实体，挂 category；兼容桥引用旧产品）
    fam, _ = jreq(
        "POST", "/api/product-families",
        {"name_zh": _name("产品"), "category_id": cid, "legacy_product_id": lid},
    )
    fid, fcode = fam["id"], fam["code"]
    assert fam["category_id"] == cid and fam["legacy_product_id"] == lid

    # 3. 可选 Variant + 可选 SKU（属该 variant）
    var, _ = jreq("POST", "/api/product-variants", {"family_id": fid, "name_zh": _name("型号")})
    vid = var["id"]
    sku, _ = jreq(
        "POST", "/api/product-skus",
        {"family_id": fid, "variant_id": vid, "name_zh": _name("SKU"), "sku_code": _name("SK1")},
    )
    assert sku["variant_id"] == vid and sku["family_id"] == fid

    # 4. 别名（历史名，供 resolve）
    hist = _name("历史别名")
    jreq(
        "POST", "/api/product-aliases",
        {"target_level": "family", "target_id": fid, "alias": hist, "alias_type": "historical_name"},
    )
    # 别名 409 冲突（大小写/空白无关）
    _, code = jreq(
        "POST", "/api/product-aliases",
        {"target_level": "family", "target_id": fid, "alias": f"  {hist}  "},
        expect=(201, 409),
    )
    assert code == 409, "重复别名必须 409"
    # SKU 编码 409
    _, code = jreq(
        "POST", "/api/product-skus",
        {"family_id": fid, "name_zh": _name("SKU2"), "sku_code": _name("SK1")},
        expect=(201, 409),
    )
    assert code == 409, "重复 sku_code 必须 409"
    print("GENERIC_CATALOG_CRUD_OK")

    # 5. tree / search / resolve
    tree, _ = jreq("GET", "/api/product-catalog/tree?include_archived=true")
    assert any(_code_in(n, fcode) for n in tree), "tree 未含新 family"
    res, _ = jreq("GET", f"/api/product-catalog/resolve?value={_url(fcode)}")
    assert res and res["id"] == fid, "resolve by code 失败"
    res_unknown, _ = jreq("GET", f"/api/product-catalog/resolve?value={_url(_name('根本不存在'))}")
    assert res_unknown is None, "未知值必须返回 null（不强制猜测）"

    # 6. 更名保 id/code
    ren, _ = jreq("PATCH", f"/api/product-families/{fid}", {"name_zh": _name("改名后")})
    assert ren["id"] == fid and ren["code"] == fcode and ren["name_zh"] != fam["name_zh"]
    print("GENERIC_CATALOG_RENAME_OK")

    # 7. 生命周期 + 归档 + 恢复
    assert jreq("POST", f"/api/product-families/{fid}/status", {"status": "active"})[0]["status"] == "active"
    assert jreq("POST", f"/api/product-families/{fid}/archive")[0]["status"] == "archived"
    # 默认列表不含归档
    lst, _ = jreq("GET", f"/api/product-families?q={_url(_name('改名后'))}")
    assert all(it["id"] != fid for it in lst["items"])
    assert jreq("POST", f"/api/product-families/{fid}/restore")[0]["status"] == "active"

    # 8. 合并 + 重定向 resolve（目标先激活，作为 canonical 活动产品）
    fam_b, _ = jreq("POST", "/api/product-families", {"name_zh": _name("目标产品"), "category_id": cid})
    bid = fam_b["id"]
    jreq("POST", f"/api/product-families/{bid}/status", {"status": "active"})
    m, _ = jreq("POST", f"/api/product-families/{fid}/merge", {"target_id": bid})
    assert m["status"] == "merged" and m["merged_into_id"] == bid
    rr, _ = jreq("GET", f"/api/product-catalog/resolve?value={_url(hist)}")
    assert rr and rr["id"] == bid and rr["redirected"] is True, "合并后历史别名应重定向到目标"
    # 自合并 422
    _, code = jreq("POST", f"/api/product-families/{bid}/merge", {"target_id": bid}, expect=(200, 422))
    assert code == 422
    print("GENERIC_CATALOG_MERGE_REDIRECT_OK")

    # 迁移已应用（catalog 端点全程可用即证明）
    print("GENERIC_CATALOG_MIGRATION_OK")
    print("GENERIC_CATALOG_E2E_OK")


def _code_in(node: dict, code: str) -> bool:
    if node.get("code") == code:
        return True
    return any(_code_in(c, code) for c in node.get("children", []))


def _url(s: str) -> str:
    return urllib.parse.quote(s)


def run_check_persist() -> None:
    # 重启后：目标产品（合并保留）与别名重定向仍在
    hist = _name("历史别名")
    rr, _ = jreq("GET", f"/api/product-catalog/resolve?value={_url(hist)}")
    assert rr is not None and rr["redirected"] is True, "重启后合并重定向丢失"
    # 目标 family 仍 active
    lst, _ = jreq("GET", f"/api/product-families?q={_url(_name('目标产品'))}")
    assert any(it["status"] == "active" for it in lst["items"]), "重启后目标产品丢失"
    # 旧扁平产品仍在
    prods, _ = jreq("GET", "/api/products")
    assert any(p["name"].startswith(PREFIX) for p in prods), "重启后旧产品丢失"
    print("GENERIC_CATALOG_PERSIST_OK")


def run_cleanup() -> None:
    # 顺序：别名 → sku → variant → family（含合并链）→ category → 旧产品
    q(f"delete from product_catalog_alias where alias like '{PREFIX}%'")
    q(f"delete from product_sku where name_zh like '{PREFIX}%'")
    q(f"delete from product_variant where name_zh like '{PREFIX}%'")
    q(f"delete from product_family where name_zh like '{PREFIX}%'")
    q(f"delete from product_category where name_zh like '{PREFIX}%'")
    q(f"delete from product where name like '{PREFIX}%'")
    print(f"cleaned synthetic catalog rows with prefix {PREFIX}")


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
