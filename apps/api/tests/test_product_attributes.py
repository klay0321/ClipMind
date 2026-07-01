"""PR-A2 Gate A 后端测试：动态属性定义 / 受约束的值 / profile 聚合。

全部中性测试名（非公司产品/属性）。需 TEST_DATABASE_URL（迁移到 0014）。
"""

from __future__ import annotations

import uuid

import pytest

CAT = "/api/product-categories"
FAM = "/api/product-families"
VAR = "/api/product-variants"
SKU = "/api/product-skus"
DEF = "/api/product-attribute-definitions"
VAL = "/api/product-attribute-values"


def _u() -> str:
    return uuid.uuid4().hex[:8]


async def _cat(client) -> dict:
    return (await client.post(CAT, json={"name_zh": f"类-{_u()}"})).json()


async def _fam(client, category_id=None) -> dict:
    body = {"name_zh": f"品-{_u()}"}
    if category_id is not None:
        body["category_id"] = category_id
    return (await client.post(FAM, json=body)).json()


async def _mk_def(client, value_type: str, *, category_id=None, **kw):
    body = {"name_zh": f"属性-{_u()}", "value_type": value_type, **kw}
    if category_id is not None:
        body["category_id"] = category_id
    return await client.post(DEF, json=body)


async def _set(client, definition_id, level, target_id, value):
    return await client.put(
        VAL,
        json={"definition_id": definition_id, "target_level": level,
              "target_id": target_id, "value": value},
    )


# ============================ 属性定义 ============================


@pytest.mark.asyncio
async def test_create_definition_basic_types(client):
    for vt in ("text", "number", "boolean", "date"):
        r = await _mk_def(client, vt)
        assert r.status_code == 201, r.text
        assert r.json()["value_type"] == vt and r.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_unknown_value_type_rejected(client):
    r = await _mk_def(client, "bogus_type")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_enum_requires_allowed_values(client):
    assert (await _mk_def(client, "enum")).status_code == 422
    r = await _mk_def(client, "enum", allowed_values=["a", "b", "c"])
    assert r.status_code == 201 and r.json()["allowed_values"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_multi_enum_requires_allowed_values(client):
    assert (await _mk_def(client, "multi_enum")).status_code == 422
    r = await _mk_def(client, "multi_enum", allowed_values=["x", "y"])
    assert r.status_code == 201 and r.json()["multi_value"] is True


@pytest.mark.asyncio
async def test_measurement_requires_unit(client):
    assert (await _mk_def(client, "measurement")).status_code == 422
    r = await _mk_def(client, "measurement", unit="mm")
    assert r.status_code == 201 and r.json()["unit"] == "mm"


@pytest.mark.asyncio
async def test_allowed_values_only_for_enum(client):
    r = await _mk_def(client, "text", allowed_values=["a"])
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_validation_rules_whitelist(client):
    assert (await _mk_def(client, "number", validation_rules={"evil": 1})).status_code == 422
    r = await _mk_def(client, "number", validation_rules={"min": 0, "max": 10})
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_key_scope_unique_within_category(client):
    cat = await _cat(client)
    key = f"k{_u()}"
    assert (await _mk_def(client, "text", category_id=cat["id"], key=key)).status_code == 201
    # 同 Category 内重复 key -> 409
    assert (await _mk_def(client, "text", category_id=cat["id"], key=key)).status_code == 409
    # 另一 Category 可复用 key -> 201
    cat2 = await _cat(client)
    assert (await _mk_def(client, "text", category_id=cat2["id"], key=key)).status_code == 201


@pytest.mark.asyncio
async def test_global_key_unique(client):
    key = f"g{_u()}"
    assert (await _mk_def(client, "text", key=key)).status_code == 201
    assert (await _mk_def(client, "text", key=key)).status_code == 409


@pytest.mark.asyncio
async def test_list_filter_searchable(client):
    cat = await _cat(client)
    await _mk_def(client, "text", category_id=cat["id"], searchable=True)
    await _mk_def(client, "text", category_id=cat["id"], searchable=False)
    r = await client.get(DEF, params={"category_id": cat["id"], "searchable": True,
                                      "include_global": False})
    items = r.json()["items"]
    assert items and all(it["searchable"] for it in items)


@pytest.mark.asyncio
async def test_archive_restore_definition(client):
    d = (await _mk_def(client, "text")).json()
    assert (await client.post(f"{DEF}/{d['id']}/archive")).json()["status"] == "archived"
    # 默认列表不含归档
    r = await client.get(DEF, params={"q": d["name_zh"]})
    assert all(it["id"] != d["id"] for it in r.json()["items"])
    assert (await client.post(f"{DEF}/{d['id']}/restore")).json()["status"] == "active"


# ============================ 属性值 ============================


@pytest.mark.asyncio
async def test_set_value_each_type(client):
    fam = await _fam(client)
    cases = [
        ("text", "你好世界", "value_text"),
        ("number", 42, "value_number"),
        ("boolean", True, "value_boolean"),
        ("date", "2026-07-01", "value_date"),
    ]
    for vt, val, col in cases:
        d = (await _mk_def(client, vt)).json()
        r = await _set(client, d["id"], "family", fam["id"], val)
        assert r.status_code == 200, r.text
        assert r.json()[col] is not None


@pytest.mark.asyncio
async def test_number_validation_rules(client):
    fam = await _fam(client)
    d = (await _mk_def(client, "number", validation_rules={"min": 0, "max": 10})).json()
    assert (await _set(client, d["id"], "family", fam["id"], 5)).status_code == 200
    assert (await _set(client, d["id"], "family", fam["id"], 99)).status_code == 422
    assert (await _set(client, d["id"], "family", fam["id"], "not-a-number")).status_code == 422


@pytest.mark.asyncio
async def test_enum_value_must_be_allowed(client):
    fam = await _fam(client)
    d = (await _mk_def(client, "enum", allowed_values=["red", "green"])).json()
    assert (await _set(client, d["id"], "family", fam["id"], "red")).status_code == 200
    assert (await _set(client, d["id"], "family", fam["id"], "purple")).status_code == 422


@pytest.mark.asyncio
async def test_multi_enum_value_subset(client):
    fam = await _fam(client)
    d = (await _mk_def(client, "multi_enum", allowed_values=["a", "b", "c"])).json()
    r = await _set(client, d["id"], "family", fam["id"], ["a", "c"])
    assert r.status_code == 200 and r.json()["value_json"] == ["a", "c"]
    assert (await _set(client, d["id"], "family", fam["id"], ["a", "z"])).status_code == 422


@pytest.mark.asyncio
async def test_measurement_snapshots_unit(client):
    fam = await _fam(client)
    d = (await _mk_def(client, "measurement", unit="g")).json()
    r = await _set(client, d["id"], "family", fam["id"], 12.5)
    assert r.status_code == 200 and r.json()["unit"] == "g"


@pytest.mark.asyncio
async def test_cross_category_rejected(client):
    cat_a, cat_b = await _cat(client), await _cat(client)
    d = (await _mk_def(client, "text", category_id=cat_a["id"])).json()
    fam_b = await _fam(client, cat_b["id"])
    # 定义属 A，目标属 B -> 跨 Category 拒绝
    assert (await _set(client, d["id"], "family", fam_b["id"], "x")).status_code == 422


@pytest.mark.asyncio
async def test_global_definition_applies_any_category(client):
    d = (await _mk_def(client, "text")).json()  # category_id 空 = 全局
    fam = await _fam(client, (await _cat(client))["id"])
    assert (await _set(client, d["id"], "family", fam["id"], "ok")).status_code == 200


@pytest.mark.asyncio
async def test_value_upsert_keeps_history(client):
    fam = await _fam(client)
    d = (await _mk_def(client, "text")).json()
    await _set(client, d["id"], "family", fam["id"], "v1")
    await _set(client, d["id"], "family", fam["id"], "v2")
    active = (await client.get(
        VAL, params={"target_level": "family", "target_id": fam["id"]}
    )).json()
    assert len([v for v in active if v["definition_id"] == d["id"]]) == 1
    assert active[-1]["value_text"] == "v2"
    with_hist = (await client.get(
        VAL, params={"target_level": "family", "target_id": fam["id"], "include_archived": True}
    )).json()
    assert len([v for v in with_hist if v["definition_id"] == d["id"]]) == 2


@pytest.mark.asyncio
async def test_value_binds_variant_and_sku(client):
    fam = await _fam(client, (await _cat(client))["id"])
    var = (await client.post(VAR, json={"family_id": fam["id"], "name_zh": f"变-{_u()}"})).json()
    sku = (await client.post(SKU, json={"family_id": fam["id"], "name_zh": f"s-{_u()}"})).json()
    d = (await _mk_def(client, "text")).json()
    assert (await _set(client, d["id"], "variant", var["id"], "vv")).status_code == 200
    assert (await _set(client, d["id"], "sku", sku["id"], "ss")).status_code == 200


@pytest.mark.asyncio
async def test_delete_value_soft(client):
    fam = await _fam(client)
    d = (await _mk_def(client, "text")).json()
    v = (await _set(client, d["id"], "family", fam["id"], "x")).json()
    assert (await client.delete(f"{VAL}/{v['id']}")).status_code == 204
    active = (await client.get(
        VAL, params={"target_level": "family", "target_id": fam["id"]}
    )).json()
    assert all(it["id"] != v["id"] for it in active)
    # 历史仍在
    hist = (await client.get(
        VAL, params={"target_level": "family", "target_id": fam["id"], "include_archived": True}
    )).json()
    assert any(it["id"] == v["id"] for it in hist)


# ============================ profile 聚合 ============================


@pytest.mark.asyncio
async def test_profile_completeness_and_missing(client):
    cat = await _cat(client)
    d1 = (await _mk_def(client, "text", category_id=cat["id"], required=True)).json()
    d2 = (await _mk_def(client, "number", category_id=cat["id"], required=True)).json()
    # 激活定义（profile 只计 active 定义）
    for d in (d1, d2):
        await client.post(f"{DEF}/{d['id']}/status", json={"status": "active"})
    fam = await _fam(client, cat["id"])
    await _set(client, d1["id"], "family", fam["id"], "filled")
    p = (await client.get(f"/api/product-catalog/family/{fam['id']}/profile")).json()
    assert p["required_total"] == 2 and p["required_filled"] == 1
    assert abs(p["completeness"] - 0.5) < 1e-6
    assert len(p["missing_required"]) == 1 and p["missing_required"][0]["definition_id"] == d2["id"]
    assert p["ai_recognition_enabled"] is False
