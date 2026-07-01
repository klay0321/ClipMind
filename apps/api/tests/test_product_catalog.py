"""PR-A1 通用产品目录 API 测试。

全部使用**中性测试名**（非公司真实产品），证明新增任意产品无需改代码。
需要 TEST_DATABASE_URL（迁移到 0013）。
"""

from __future__ import annotations

import uuid

import pytest


def _u() -> str:
    return uuid.uuid4().hex[:8]


async def _mk_category(client, name="测试类别") -> dict:
    r = await client.post("/api/product-categories", json={"name_zh": f"{name}-{_u()}"})
    assert r.status_code == 201, r.text
    return r.json()


async def _mk_family(client, category_id=None, name="测试族") -> dict:
    body = {"name_zh": f"{name}-{_u()}"}
    if category_id is not None:
        body["category_id"] = category_id
    r = await client.post("/api/product-families", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------- CRUD + 层级 ---------------------------


@pytest.mark.asyncio
async def test_full_hierarchy_crud(client):
    cat = await _mk_category(client)
    assert cat["status"] == "draft" and cat["code"]
    fam = await _mk_family(client, cat["id"])
    assert fam["category_id"] == cat["id"]
    # variant
    rv = await client.post(
        "/api/product-variants", json={"family_id": fam["id"], "name_zh": f"变体甲-{_u()}"}
    )
    assert rv.status_code == 201, rv.text
    var = rv.json()
    # sku（属于 variant）
    rs = await client.post(
        "/api/product-skus",
        json={"family_id": fam["id"], "variant_id": var["id"], "name_zh": f"SKU甲-{_u()}",
              "sku_code": f"SK-{_u()}"},
    )
    assert rs.status_code == 201, rs.text
    sku = rs.json()
    assert sku["family_id"] == fam["id"] and sku["variant_id"] == var["id"]
    # tree 包含该层级
    rt = await client.get("/api/product-catalog/tree", params={"include_archived": True})
    assert rt.status_code == 200
    codes = _all_codes(rt.json())
    assert cat["code"] in codes and fam["code"] in codes and var["code"] in codes


def _all_codes(nodes) -> set[str]:
    out = set()
    for n in nodes:
        out.add(n["code"])
        out |= _all_codes(n.get("children", []))
    return out


@pytest.mark.asyncio
async def test_sku_can_attach_directly_to_family(client):
    fam = await _mk_family(client)
    r = await client.post(
        "/api/product-skus", json={"family_id": fam["id"], "name_zh": f"直挂SKU-{_u()}"}
    )
    assert r.status_code == 201
    assert r.json()["variant_id"] is None


@pytest.mark.asyncio
async def test_sku_variant_must_be_same_family(client):
    fam1 = await _mk_family(client)
    fam2 = await _mk_family(client)
    rv = await client.post(
        "/api/product-variants", json={"family_id": fam2["id"], "name_zh": f"变体乙-{_u()}"}
    )
    var2 = rv.json()
    # sku 属 fam1 但 variant 属 fam2 -> 422
    r = await client.post(
        "/api/product-skus",
        json={"family_id": fam1["id"], "variant_id": var2["id"], "name_zh": f"X-{_u()}"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_zh_name_required(client):
    r = await client.post("/api/product-families", json={"name_zh": "   "})
    assert r.status_code == 422


# --------------------------- 更名保 ID/code ---------------------------


@pytest.mark.asyncio
async def test_rename_preserves_id_and_code(client):
    fam = await _mk_family(client)
    old_id, old_code = fam["id"], fam["code"]
    r = await client.patch(
        f"/api/product-families/{old_id}", json={"name_zh": f"改名后-{_u()}"}
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["id"] == old_id and updated["code"] == old_code
    assert updated["name_zh"] != fam["name_zh"]


# --------------------------- 生命周期 / 归档 / 恢复 ---------------------------


@pytest.mark.asyncio
async def test_lifecycle_archive_restore(client):
    fam = await _mk_family(client)
    fid = fam["id"]
    # draft -> active
    r = await client.post(f"/api/product-families/{fid}/status", json={"status": "active"})
    assert r.status_code == 200 and r.json()["status"] == "active"
    # active -> paused
    r = await client.post(f"/api/product-families/{fid}/status", json={"status": "paused"})
    assert r.status_code == 200 and r.json()["status"] == "paused"
    # archive
    r = await client.post(f"/api/product-families/{fid}/archive")
    assert r.status_code == 200 and r.json()["status"] == "archived"
    assert r.json()["archived_at"] is not None
    # 默认列表不含归档
    r = await client.get("/api/product-families", params={"q": fam["name_zh"]})
    assert all(it["id"] != fid for it in r.json()["items"])
    # include_archived 可见
    r = await client.get(
        "/api/product-families", params={"q": fam["name_zh"], "include_archived": True}
    )
    assert any(it["id"] == fid for it in r.json()["items"])
    # restore
    r = await client.post(f"/api/product-families/{fid}/restore")
    assert r.status_code == 200 and r.json()["status"] == "active"


@pytest.mark.asyncio
async def test_invalid_transition_rejected(client):
    fam = await _mk_family(client)  # draft
    # draft -> paused 非法
    r = await client.post(
        f"/api/product-families/{fam['id']}/status", json={"status": "paused"}
    )
    assert r.status_code == 422


# --------------------------- 合并 / 重定向 / 防环 ---------------------------


@pytest.mark.asyncio
async def test_merge_and_redirect_resolve(client):
    a = await _mk_family(client, name="源族")
    b = await _mk_family(client, name="目标族")
    # 给 a 加历史别名，供 resolve
    alias_name = f"历史名-{_u()}"
    ra = await client.post(
        "/api/product-aliases",
        json={"target_level": "family", "target_id": a["id"], "alias": alias_name,
              "alias_type": "historical_name"},
    )
    assert ra.status_code == 201
    # 合并 a -> b
    rm = await client.post(
        f"/api/product-families/{a['id']}/merge", json={"target_id": b["id"]}
    )
    assert rm.status_code == 200
    assert rm.json()["status"] == "merged" and rm.json()["merged_into_id"] == b["id"]
    # a 仍存在（非物理删除）
    rg = await client.get(f"/api/product-families/{a['id']}")
    assert rg.status_code == 200 and rg.json()["status"] == "merged"
    # resolve 历史别名 -> 重定向到 b
    rr = await client.get("/api/product-catalog/resolve", params={"value": alias_name})
    assert rr.status_code == 200
    node = rr.json()
    assert node is not None and node["id"] == b["id"] and node["redirected"] is True


@pytest.mark.asyncio
async def test_self_merge_rejected(client):
    fam = await _mk_family(client)
    r = await client.post(
        f"/api/product-families/{fam['id']}/merge", json={"target_id": fam["id"]}
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_merge_cycle_rejected(client):
    a = await _mk_family(client)
    b = await _mk_family(client)
    # a -> b
    r1 = await client.post(
        f"/api/product-families/{a['id']}/merge", json={"target_id": b["id"]}
    )
    assert r1.status_code == 200
    # b -> a 会形成环 -> 422
    r2 = await client.post(
        f"/api/product-families/{b['id']}/merge", json={"target_id": a["id"]}
    )
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_variant_merge_cross_family_rejected(client):
    fam1 = await _mk_family(client)
    fam2 = await _mk_family(client)
    v1 = (await client.post(
        "/api/product-variants", json={"family_id": fam1["id"], "name_zh": f"v1-{_u()}"}
    )).json()
    v2 = (await client.post(
        "/api/product-variants", json={"family_id": fam2["id"], "name_zh": f"v2-{_u()}"}
    )).json()
    r = await client.post(
        f"/api/product-variants/{v1['id']}/merge", json={"target_id": v2["id"]}
    )
    assert r.status_code == 422


# --------------------------- 别名 冲突/唯一 ---------------------------


@pytest.mark.asyncio
async def test_alias_dup_within_target_conflict(client):
    fam = await _mk_family(client)
    name = f"别名-{_u()}"
    r1 = await client.post(
        "/api/product-aliases",
        json={"target_level": "family", "target_id": fam["id"], "alias": name},
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/product-aliases",
        json={"target_level": "family", "target_id": fam["id"], "alias": name},
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_alias_case_insensitive_conflict(client):
    fam = await _mk_family(client)
    base = f"Alias{_u()}"
    r1 = await client.post(
        "/api/product-aliases",
        json={"target_level": "family", "target_id": fam["id"], "alias": f"  {base}  "},
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/product-aliases",
        json={"target_level": "family", "target_id": fam["id"], "alias": base.upper()},
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_alias_bad_type_rejected(client):
    fam = await _mk_family(client)
    r = await client.post(
        "/api/product-aliases",
        json={"target_level": "family", "target_id": fam["id"], "alias": "x",
              "alias_type": "bogus_type"},
    )
    assert r.status_code == 422


# --------------------------- SKU 唯一 ---------------------------


@pytest.mark.asyncio
async def test_sku_code_unique(client):
    fam = await _mk_family(client)
    code = f"SKU-{_u()}"
    r1 = await client.post(
        "/api/product-skus",
        json={"family_id": fam["id"], "name_zh": f"s1-{_u()}", "sku_code": code},
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/product-skus",
        json={"family_id": fam["id"], "name_zh": f"s2-{_u()}", "sku_code": code},
    )
    assert r2.status_code == 409


# --------------------------- 解析 / 搜索 ---------------------------


@pytest.mark.asyncio
async def test_resolve_by_code_and_unknown(client):
    fam = await _mk_family(client)
    # by code
    r = await client.get("/api/product-catalog/resolve", params={"value": fam["code"]})
    assert r.status_code == 200 and r.json()["id"] == fam["id"]
    # unknown -> null（不强制猜测）
    r = await client.get(
        "/api/product-catalog/resolve", params={"value": f"根本不存在-{_u()}"}
    )
    assert r.status_code == 200 and r.json() is None


@pytest.mark.asyncio
async def test_search_and_pagination(client):
    cat = await _mk_category(client)
    marker = _u()
    for _ in range(3):
        await _mk_family(client, cat["id"], name=f"分页{marker}")
    # 按 category 过滤 + 分页
    r = await client.get(
        "/api/product-families",
        params={"category_id": cat["id"], "limit": 2, "offset": 0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3 and len(body["items"]) == 2
    # search
    rs = await client.get("/api/product-catalog/search", params={"q": marker})
    assert rs.status_code == 200 and len(rs.json()) >= 3


# --------------------------- 兼容：旧 /api/products 不受影响 ---------------------------


@pytest.mark.asyncio
async def test_legacy_products_api_unaffected(client):
    # 旧扁平产品 API 仍工作
    r = await client.post("/api/products", json={"name": f"旧产品-{_u()}"})
    assert r.status_code == 201, r.text
    legacy = r.json()
    r = await client.get("/api/products")
    assert r.status_code == 200 and any(p["id"] == legacy["id"] for p in r.json())
    # 新目录 family 可通过兼容桥引用旧产品
    rf = await client.post(
        "/api/product-families",
        json={"name_zh": f"桥接族-{_u()}", "legacy_product_id": legacy["id"]},
    )
    assert rf.status_code == 201 and rf.json()["legacy_product_id"] == legacy["id"]


@pytest.mark.asyncio
async def test_not_found_404(client):
    r = await client.get("/api/product-families/999999999")
    assert r.status_code == 404
