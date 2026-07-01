"""PR-A1 合并前加固测试：四层生命周期、更名历史别名、歧义解析、code 作用域、归档/合并保护。

全部中性测试名（非公司产品）。需 TEST_DATABASE_URL（迁移到修订 0013）。
"""

from __future__ import annotations

import uuid

import pytest
from clipmind_shared.review import normalize_name

CAT = "/api/product-categories"
FAM = "/api/product-families"
VAR = "/api/product-variants"
SKU = "/api/product-skus"
ALIAS = "/api/product-aliases"
RESOLVE = "/api/product-catalog/resolve"


def _u() -> str:
    return uuid.uuid4().hex[:8]


async def _set(client, base, oid, s):
    """POST {base}/{id}/status。返回 Response。"""
    return await client.post(f"{base}/{oid}/status", json={"status": s})


async def _resolve(client, value):
    return (await client.get(RESOLVE, params={"value": value})).json()


async def _cat(client, active=False):
    r = await client.post(CAT, json={"name_zh": f"类别-{_u()}"})
    assert r.status_code == 201, r.text
    c = r.json()
    if active:
        r = await _set(client, CAT, c["id"], "active")
        assert r.status_code == 200, r.text
        c = r.json()
    return c


async def _fam(client, category_id=None, active=False, name="产品"):
    body = {"name_zh": f"{name}-{_u()}"}
    if category_id is not None:
        body["category_id"] = category_id
    r = await client.post(FAM, json=body)
    assert r.status_code == 201, r.text
    f = r.json()
    if active:
        r = await _set(client, FAM, f["id"], "active")
        assert r.status_code == 200, r.text
        f = r.json()
    return f


async def _active_fam(client):
    cat = await _cat(client, active=True)
    return await _fam(client, cat["id"], active=True)


async def _var(client, family_id, active=False, code=None):
    body = {"family_id": family_id, "name_zh": f"变体-{_u()}"}
    if code:
        body["code"] = code
    r = await client.post(VAR, json=body)
    assert r.status_code == 201, r.text
    v = r.json()
    if active:
        r = await _set(client, VAR, v["id"], "active")
        assert r.status_code == 200, r.text
        v = r.json()
    return v


async def _sku(client, family_id, **kw):
    body = {"family_id": family_id, "name_zh": f"s-{_u()}", **kw}
    return await client.post(SKU, json=body)


async def _aliases(client, level, oid):
    r = await client.get(ALIAS, params={"target_level": level, "target_id": oid})
    return r.json()


async def _add_alias(client, level, oid, alias):
    return await client.post(
        ALIAS, json={"target_level": level, "target_id": oid, "alias": alias}
    )


# ============================ §二 生命周期 ============================


@pytest.mark.asyncio
async def test_category_lifecycle(client):
    cid = (await _cat(client))["id"]
    assert (await _set(client, CAT, cid, "paused")).status_code == 422  # draft->paused 非法
    assert (await _set(client, CAT, cid, "active")).json()["status"] == "active"
    assert (await _set(client, CAT, cid, "paused")).json()["status"] == "paused"
    assert (await _set(client, CAT, cid, "active")).json()["status"] == "active"
    assert (await client.post(f"{CAT}/{cid}/archive")).json()["status"] == "archived"
    assert (await client.post(f"{CAT}/{cid}/restore")).json()["status"] == "active"


@pytest.mark.asyncio
async def test_family_activation_requires_active_category(client):
    f0 = await _fam(client)  # 无 category
    assert (await _set(client, FAM, f0["id"], "active")).status_code == 422
    cat = await _cat(client)  # draft category
    f1 = await _fam(client, cat["id"])
    assert (await _set(client, FAM, f1["id"], "active")).status_code == 422
    await _set(client, CAT, cat["id"], "active")
    assert (await _set(client, FAM, f1["id"], "active")).status_code == 200


@pytest.mark.asyncio
async def test_variant_activation_requires_active_family(client):
    cat = await _cat(client, active=True)
    fam = await _fam(client, cat["id"])  # draft family
    v = await _var(client, fam["id"])
    assert (await _set(client, VAR, v["id"], "active")).status_code == 422
    await _set(client, FAM, fam["id"], "active")
    assert (await _set(client, VAR, v["id"], "active")).status_code == 200


@pytest.mark.asyncio
async def test_sku_activation_requires_active_parent(client):
    fam = await _active_fam(client)
    var = await _var(client, fam["id"])  # draft variant
    sku = (await _sku(client, fam["id"], variant_id=var["id"])).json()
    assert (await _set(client, SKU, sku["id"], "active")).status_code == 422
    await _set(client, VAR, var["id"], "active")
    assert (await _set(client, SKU, sku["id"], "active")).status_code == 200


@pytest.mark.asyncio
async def test_all_levels_status_api(client):
    fam = await _active_fam(client)
    var = await _var(client, fam["id"], active=True)
    sku = (await _sku(client, fam["id"], variant_id=var["id"])).json()
    assert (await _set(client, SKU, sku["id"], "active")).status_code == 200
    assert (await _set(client, SKU, sku["id"], "paused")).status_code == 200
    assert (await _set(client, VAR, var["id"], "paused")).status_code == 200
    assert (await _set(client, FAM, fam["id"], "paused")).status_code == 200


@pytest.mark.asyncio
async def test_merged_node_cannot_reactivate(client):
    a, b = await _fam(client), await _fam(client)
    r = await client.post(f"{FAM}/{a['id']}/merge", json={"target_id": b["id"]})
    assert r.status_code == 200
    assert (await _set(client, FAM, a["id"], "active")).status_code == 422
    assert (await client.post(f"{FAM}/{a['id']}/restore")).status_code == 422


# ============================ §三 更名历史别名 ============================


@pytest.mark.asyncio
async def test_rename_creates_historical_alias(client):
    f = await _fam(client)
    old = f["name_zh"]
    await client.patch(f"{FAM}/{f['id']}", json={"name_zh": f"新名-{_u()}"})
    aliases = await _aliases(client, "family", f["id"])
    assert any(a["alias_type"] == "historical_name" and a["alias"] == old for a in aliases)


@pytest.mark.asyncio
async def test_old_zh_name_resolves_after_rename(client):
    f = await _fam(client)
    old = f["name_zh"]
    await client.patch(f"{FAM}/{f['id']}", json={"name_zh": f"新-{_u()}"})
    r = await _resolve(client, old)
    assert r["status"] == "resolved" and r["canonical"]["id"] == f["id"]


@pytest.mark.asyncio
async def test_old_en_name_resolves_after_rename(client):
    en = f"OldEn{_u()}"
    f = (await client.post(FAM, json={"name_zh": f"产品-{_u()}", "name_en": en})).json()
    await client.patch(f"{FAM}/{f['id']}", json={"name_en": f"NewEn{_u()}"})
    r = await _resolve(client, en)
    assert r["status"] == "resolved" and r["canonical"]["id"] == f["id"]


@pytest.mark.asyncio
async def test_repeated_rename_does_not_duplicate_alias(client):
    f = await _fam(client, name="N1")
    n1 = f["name_zh"]
    await client.patch(f"{FAM}/{f['id']}", json={"name_zh": f"N2-{_u()}"})
    n2 = (await client.get(f"{FAM}/{f['id']}")).json()["name_zh"]
    await client.patch(f"{FAM}/{f['id']}", json={"name_zh": n1})  # alias n2
    await client.patch(f"{FAM}/{f['id']}", json={"name_zh": n2})  # alias n1 again -> 幂等
    aliases = await _aliases(client, "family", f["id"])
    hits = [a for a in aliases if a["normalized_alias"] == normalize_name(n1)]
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_rename_transaction_rolls_back_on_conflict(client):
    f = await _fam(client)
    old = f["name_zh"]
    # 非法空名 -> 422，名称不变、无历史别名（失败不部分持久化）
    r = await client.patch(f"{FAM}/{f['id']}", json={"name_zh": "   "})
    assert r.status_code == 422
    assert (await client.get(f"{FAM}/{f['id']}")).json()["name_zh"] == old
    aliases = await _aliases(client, "family", f["id"])
    assert not any(a["alias_type"] == "historical_name" for a in aliases)


@pytest.mark.asyncio
async def test_old_name_redirects_after_merge(client):
    a = await _fam(client)
    old = a["name_zh"]
    await client.patch(f"{FAM}/{a['id']}", json={"name_zh": f"改-{_u()}"})
    b = await _fam(client)
    await client.post(f"{FAM}/{a['id']}/merge", json={"target_id": b["id"]})
    r = await _resolve(client, old)
    assert r["status"] == "resolved"
    assert r["canonical"]["id"] == b["id"] and r["canonical"]["redirected"] is True


# ============================ §四 歧义解析 ============================


@pytest.mark.asyncio
async def test_same_alias_on_two_families_is_ambiguous(client):
    a, b = await _fam(client), await _fam(client)
    shared = f"共享{_u()}"
    await _add_alias(client, "family", a["id"], shared)
    await _add_alias(client, "family", b["id"], shared)
    r = await _resolve(client, shared)
    assert r["status"] == "ambiguous" and len(r["candidates"]) == 2


@pytest.mark.asyncio
async def test_same_alias_across_family_and_sku_is_ambiguous(client):
    fam = await _fam(client)
    sku = (await _sku(client, fam["id"])).json()
    shared = f"跨{_u()}"
    await _add_alias(client, "family", fam["id"], shared)
    await _add_alias(client, "sku", sku["id"], shared)
    r = await _resolve(client, shared)
    assert r["status"] == "ambiguous" and len(r["candidates"]) == 2


@pytest.mark.asyncio
async def test_exact_sku_code_precedence(client):
    code = f"PREC{_u()}"
    fam = await _fam(client)
    sku = (await _sku(client, fam["id"], sku_code=code)).json()
    fam2 = await _fam(client)
    await _add_alias(client, "family", fam2["id"], code)  # 同名 alias
    r = await _resolve(client, code)
    assert r["status"] == "resolved"
    assert r["canonical"]["id"] == sku["id"] and r["canonical"]["level"] == "sku"


@pytest.mark.asyncio
async def test_exact_code_precedence(client):
    code = f"CODEPREC{_u()}"
    fam1 = (await client.post(FAM, json={"name_zh": f"n-{_u()}", "code": code})).json()
    await client.post(FAM, json={"name_zh": code})  # 另一 family 正式名恰为该 code
    r = await _resolve(client, code)
    assert r["status"] == "resolved" and r["canonical"]["id"] == fam1["id"]


@pytest.mark.asyncio
async def test_unknown_returns_not_found(client):
    r = await _resolve(client, f"未知{_u()}")
    assert r["status"] == "not_found" and r["canonical"] is None


@pytest.mark.asyncio
async def test_merge_redirect_remains_deterministic(client):
    a, b = await _fam(client), await _fam(client)
    alias = f"det{_u()}"
    await _add_alias(client, "family", a["id"], alias)
    await client.post(f"{FAM}/{a['id']}/merge", json={"target_id": b["id"]})
    r1 = await _resolve(client, alias)
    r2 = await _resolve(client, alias)
    assert r1["status"] == "resolved" and r1 == r2 and r1["canonical"]["id"] == b["id"]


# ============================ §五 code 作用域唯一 ============================


@pytest.mark.asyncio
async def test_variant_code_can_repeat_across_families(client):
    a, b = await _fam(client), await _fam(client)
    body_a = {"family_id": a["id"], "name_zh": f"v-{_u()}", "code": "standard"}
    body_b = {"family_id": b["id"], "name_zh": f"v-{_u()}", "code": "standard"}
    r1 = await client.post(VAR, json=body_a)
    r2 = await client.post(VAR, json=body_b)
    assert r1.status_code == 201 and r2.status_code == 201


@pytest.mark.asyncio
async def test_variant_code_conflicts_within_family(client):
    a = await _fam(client)
    r1 = await client.post(VAR, json={"family_id": a["id"], "name_zh": f"v-{_u()}", "code": "dup"})
    r2 = await client.post(VAR, json={"family_id": a["id"], "name_zh": f"v-{_u()}", "code": "DUP"})
    assert r1.status_code == 201 and r2.status_code == 409


@pytest.mark.asyncio
async def test_sku_internal_code_can_repeat_across_families(client):
    a, b = await _fam(client), await _fam(client)
    r1 = await _sku(client, a["id"], code="sc")
    r2 = await _sku(client, b["id"], code="sc")
    assert r1.status_code == 201 and r2.status_code == 201


@pytest.mark.asyncio
async def test_sku_code_case_insensitive_unique(client):
    a, b = await _fam(client), await _fam(client)
    code = f"GTIN{_u()}"
    r1 = await _sku(client, a["id"], sku_code=code)
    r2 = await _sku(client, b["id"], sku_code=f"  {code.lower()}  ")  # 不同 family、大小写/空白
    assert r1.status_code == 201 and r2.status_code == 409


@pytest.mark.asyncio
async def test_code_case_insensitive_unique(client):
    code = f"CAT{_u()}"
    r1 = await client.post(CAT, json={"name_zh": f"c-{_u()}", "code": code})
    r2 = await client.post(CAT, json={"name_zh": f"c-{_u()}", "code": code.lower()})
    assert r1.status_code == 201 and r2.status_code == 409


# ============================ §六 归档/合并保护 ============================


@pytest.mark.asyncio
async def test_category_archive_blocked_with_live_families(client):
    cat = await _cat(client, active=True)
    await _fam(client, cat["id"], active=True)
    r = await client.post(f"{CAT}/{cat['id']}/archive")
    assert r.status_code == 409 and "系列" in r.json()["detail"]


@pytest.mark.asyncio
async def test_category_archive_allowed_when_children_archived(client):
    cat = await _cat(client, active=True)
    fam = await _fam(client, cat["id"], active=True)
    await client.post(f"{FAM}/{fam['id']}/archive")
    assert (await client.post(f"{CAT}/{cat['id']}/archive")).status_code == 200


@pytest.mark.asyncio
async def test_family_merge_blocked_when_variants_exist(client):
    a, b = await _fam(client), await _fam(client)
    await _var(client, a["id"])
    r = await client.post(f"{FAM}/{a['id']}/merge", json={"target_id": b["id"]})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_family_merge_blocked_when_direct_skus_exist(client):
    a, b = await _fam(client), await _fam(client)
    await _sku(client, a["id"])
    r = await client.post(f"{FAM}/{a['id']}/merge", json={"target_id": b["id"]})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_variant_merge_blocked_when_skus_exist(client):
    fam = await _fam(client)
    v1 = await _var(client, fam["id"])
    v2 = await _var(client, fam["id"])
    await _sku(client, fam["id"], variant_id=v1["id"])
    r = await client.post(f"{VAR}/{v1['id']}/merge", json={"target_id": v2["id"]})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_failed_merge_keeps_tree_and_children_unchanged(client):
    a, b = await _fam(client), await _fam(client)
    var = await _var(client, a["id"])
    r = await client.post(f"{FAM}/{a['id']}/merge", json={"target_id": b["id"]})
    assert r.status_code == 409
    assert (await client.get(f"{FAM}/{a['id']}")).json()["status"] != "merged"
    assert (await client.get(f"{VAR}/{var['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_empty_family_merge_redirect_still_works(client):
    a, b = await _fam(client), await _fam(client)
    alias = f"empty{_u()}"
    await _add_alias(client, "family", a["id"], alias)
    r = await client.post(f"{FAM}/{a['id']}/merge", json={"target_id": b["id"]})
    assert r.status_code == 200
    res = await _resolve(client, alias)
    assert res["status"] == "resolved" and res["canonical"]["id"] == b["id"]
