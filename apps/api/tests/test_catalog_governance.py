"""PR-A2 Gate B 后端测试：完整度策略 / readiness / 入驻审核 / 混淆关系 / 变更历史。

全部中性测试名（非公司产品）。需 TEST_DATABASE_URL（迁移到 0015）+ 本机 ffmpeg（参考图缩略，
缺失不影响断言）。参考图用自造 1×1 PNG，不提交真实图片。
"""

from __future__ import annotations

import struct
import uuid
import zlib

import pytest

CAT = "/api/product-categories"
FAM = "/api/product-families"
VAR = "/api/product-variants"
SKU = "/api/product-skus"
REF = "/api/product-reference-assets"
POL = "/api/product-readiness-policies"
DEF = "/api/product-attribute-definitions"
VAL = "/api/product-attribute-values"
PAIR = "/api/product-confusion-pairs"
REV = "/api/catalog-revisions"


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _u() -> str:
    return uuid.uuid4().hex[:8]


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


async def _cat(client, active=True) -> dict:
    c = (await client.post(CAT, json={"name_zh": f"类-{_u()}"})).json()
    if active:
        await client.post(f"{CAT}/{c['id']}/status", json={"status": "active"})
    return c


async def _fam(client, cat_id=None) -> dict:
    body = {"name_zh": f"品-{_u()}"}
    if cat_id is not None:
        body["category_id"] = cat_id
    r = await client.post(FAM, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _upload(client, level, target_id, png, **form):
    data = {"target_level": level, "target_id": str(target_id)}
    data.update({k: str(v) for k, v in form.items()})
    return await client.post(REF, data=data, files={"files": (f"{_u()}.png", png, "image/png")})


async def _readiness(client, level, nid) -> dict:
    r = await client.get(f"/api/product-catalog/{level}/{nid}/readiness")
    assert r.status_code == 200, r.text
    return r.json()


async def _make_complete_family(client) -> tuple[dict, dict]:
    """构造满足系统默认策略的 family：active 分类 + 3 图（1 主图）+ 1 个已填 identity 属性。"""
    cat = await _cat(client, active=True)
    fam = await _fam(client, cat["id"])
    # 3 张不同内容参考图，第一张设主图
    first = None
    for i, color in enumerate(((200, 10, 10), (10, 200, 10), (10, 10, 200))):
        r = await _upload(client, "family", fam["id"], _png(*color), angle="front")
        assert r.status_code == 201, r.text
        if i == 0:
            first = r.json()["created"][0]
    await client.post(f"{REF}/{first['id']}/primary")
    # identity 属性（须 active 才计入 readiness）+ 填值
    d = (await client.post(DEF, json={
        "name_zh": f"身份属性-{_u()}", "category_id": cat["id"],
        "value_type": "text", "identity_relevant": True,
    })).json()
    await client.post(f"{DEF}/{d['id']}/status", json={"status": "active"})
    r = await client.put(VAL, json={
        "definition_id": d["id"], "target_level": "family",
        "target_id": fam["id"], "value": "样例值",
    })
    assert r.status_code == 200, r.text
    return cat, fam


# ============================ 完整度策略 ============================


@pytest.mark.asyncio
async def test_policy_versioning_single_active(client):
    cat = await _cat(client)
    p1 = (await client.post(POL, json={"category_id": cat["id"], "name": "v1"})).json()
    p2 = (await client.post(POL, json={"category_id": cat["id"], "name": "v2"})).json()
    assert (p1["version"], p2["version"]) == (1, 2) and p1["status"] == "draft"
    assert (await client.post(f"{POL}/{p1['id']}/activate")).json()["status"] == "active"
    # 激活 v2 → v1 自动归档，同 Category 仅一个 active
    assert (await client.post(f"{POL}/{p2['id']}/activate")).json()["status"] == "active"
    lst = (await client.get(POL, params={
        "category_id": cat["id"], "include_archived": True,
    })).json()["items"]
    st = {p["version"]: p["status"] for p in lst}
    assert st[1] == "archived" and st[2] == "active"


@pytest.mark.asyncio
async def test_policy_validation(client):
    cat = await _cat(client)
    # 未白名单角度 → 422
    r = await client.post(POL, json={"category_id": cat["id"], "required_angles": ["bogus"]})
    assert r.status_code == 422
    # 越界数值 → 422（pydantic ge/le）
    r = await client.post(POL, json={"category_id": cat["id"], "min_reference_count": 999})
    assert r.status_code == 422
    # 归档策略不可激活
    p = (await client.post(POL, json={"category_id": cat["id"]})).json()
    await client.post(f"{POL}/{p['id']}/archive")
    assert (await client.post(f"{POL}/{p['id']}/activate")).status_code == 422


# ============================ Readiness 计算 ============================


@pytest.mark.asyncio
async def test_readiness_default_policy_incomplete(client):
    cat = await _cat(client, active=True)
    fam = await _fam(client, cat["id"])
    r = await _readiness(client, "family", fam["id"])
    assert r["policy_version"] == 0 and r["policy_id"] is None  # 系统默认策略
    assert r["complete"] is False and 0 <= r["score"] <= 100
    keys = {m["key"] for m in r["missing_items"]}
    assert "minimum_references" in keys and "identity_attributes" in keys
    assert r["ai_recognition_enabled"] is False


@pytest.mark.asyncio
async def test_readiness_deterministic(client):
    cat = await _cat(client, active=True)
    fam = await _fam(client, cat["id"])
    r1 = await _readiness(client, "family", fam["id"])
    r2 = await _readiness(client, "family", fam["id"])
    for k in ("score", "complete", "checks", "missing_items", "blocking_items",
              "policy_version"):
        assert r1[k] == r2[k], f"{k} 不确定"


@pytest.mark.asyncio
async def test_readiness_complete_with_default_policy(client):
    _, fam = await _make_complete_family(client)
    r = await _readiness(client, "family", fam["id"])
    assert r["complete"] is True and r["score"] == 100, r


@pytest.mark.asyncio
async def test_readiness_required_angles_and_custom_policy(client):
    cat = await _cat(client, active=True)
    fam = await _fam(client, cat["id"])
    p = (await client.post(POL, json={
        "category_id": cat["id"], "min_reference_count": 1,
        "min_identity_attribute_count": 0, "require_primary_reference": False,
        "required_angles": ["front", "back"],
    })).json()
    await client.post(f"{POL}/{p['id']}/activate")
    await _upload(client, "family", fam["id"], _png(1, 2, 3), angle="front")
    r = await _readiness(client, "family", fam["id"])
    assert r["policy_version"] == p["version"] and r["policy_id"] == p["id"]
    angles = next(c for c in r["checks"] if c["key"] == "required_angles")
    assert angles["passed"] is False  # 缺 back
    await _upload(client, "family", fam["id"], _png(4, 5, 6), angle="back")
    r2 = await _readiness(client, "family", fam["id"])
    assert next(c for c in r2["checks"] if c["key"] == "required_angles")["passed"] is True


@pytest.mark.asyncio
async def test_readiness_blocking_invalid_reference(client):
    _, fam = await _make_complete_family(client)
    # 追加一张并人工标记为 wrong_product → blocking（高分也不能忽略）
    r = await _upload(client, "family", fam["id"], _png(9, 9, 9))
    bad_id = r.json()["created"][0]["id"]
    await client.patch(f"{REF}/{bad_id}", json={"quality_status": "wrong_product"})
    res = await _readiness(client, "family", fam["id"])
    assert res["complete"] is False
    assert any(b["key"] == "invalid_references" for b in res["blocking_items"])


@pytest.mark.asyncio
async def test_readiness_parent_active_check(client):
    cat = await _cat(client, active=False)  # draft 分类
    fam = await _fam(client, cat["id"])
    r = await _readiness(client, "family", fam["id"])
    parent = next(c for c in r["checks"] if c["key"] == "parent_active")
    assert parent["passed"] is False


# ============================ 入驻审核 ============================


@pytest.mark.asyncio
async def test_submit_guard_rejects_incomplete(client):
    cat = await _cat(client, active=True)
    fam = await _fam(client, cat["id"])
    r = await client.post(f"/api/product-catalog/family/{fam['id']}/submit-review")
    assert r.status_code == 422 and "缺失" in r.json()["detail"]
    # 未提交前查询 onboarding 为 null
    g = await client.get(f"/api/product-catalog/family/{fam['id']}/onboarding")
    assert g.status_code == 200 and g.json() is None


@pytest.mark.asyncio
async def test_submit_approve_flow_with_snapshot(client):
    _, fam = await _make_complete_family(client)
    r = await client.post(
        f"/api/product-catalog/family/{fam['id']}/submit-review",
        json={"actor_label": "运营甲"},
    )
    assert r.status_code == 200, r.text
    ob = r.json()
    assert ob["status"] == "ready_for_review" and ob["readiness_score"] == 100
    assert ob["policy_version"] == 0 and ob["readiness_snapshot"]["score"] == 100
    assert ob["submitted_by"] == "运营甲" and ob["submitted_at"]
    a = await client.post(
        f"/api/product-catalog/family/{fam['id']}/approve",
        json={"note": "资料齐全", "actor_label": "审核乙"},
    )
    assert a.status_code == 200 and a.json()["status"] == "approved"
    assert a.json()["reviewer_note"] == "资料齐全" and a.json()["reviewed_by"] == "审核乙"


@pytest.mark.asyncio
async def test_request_changes_and_resubmit(client):
    _, fam = await _make_complete_family(client)
    await client.post(f"/api/product-catalog/family/{fam['id']}/submit-review")
    r = await client.post(
        f"/api/product-catalog/family/{fam['id']}/request-changes",
        json={"note": "补充英文名"},
    )
    assert r.status_code == 200 and r.json()["status"] == "needs_changes"
    # 可再次提交
    r2 = await client.post(f"/api/product-catalog/family/{fam['id']}/submit-review")
    assert r2.status_code == 200 and r2.json()["status"] == "ready_for_review"


@pytest.mark.asyncio
async def test_approve_requires_ready_state(client):
    _, fam = await _make_complete_family(client)
    # 未提交直接批准 → 422
    r = await client.post(f"/api/product-catalog/family/{fam['id']}/approve")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_block_from_any_state(client):
    _, fam = await _make_complete_family(client)
    await client.post(f"/api/product-catalog/family/{fam['id']}/submit-review")
    await client.post(f"/api/product-catalog/family/{fam['id']}/approve")
    r = await client.post(
        f"/api/product-catalog/family/{fam['id']}/block", json={"note": "资料有误"}
    )
    assert r.status_code == 200 and r.json()["status"] == "blocked"


@pytest.mark.asyncio
async def test_submit_guard_merged_archived(client):
    cat = await _cat(client, active=True)
    a = await _fam(client, cat["id"])
    b = await _fam(client, cat["id"])
    await client.post(f"{FAM}/{a['id']}/merge", json={"target_id": b["id"]})
    r = await client.post(f"/api/product-catalog/family/{a['id']}/submit-review")
    assert r.status_code == 422 and "不可提交" in r.json()["detail"]


@pytest.mark.asyncio
async def test_approved_resubmit_rejected(client):
    _, fam = await _make_complete_family(client)
    await client.post(f"/api/product-catalog/family/{fam['id']}/submit-review")
    await client.post(f"/api/product-catalog/family/{fam['id']}/approve")
    r = await client.post(f"/api/product-catalog/family/{fam['id']}/submit-review")
    assert r.status_code == 422 and "已通过审核" in r.json()["detail"]


@pytest.mark.asyncio
async def test_onboarding_list_filter(client):
    _, fam = await _make_complete_family(client)
    await client.post(f"/api/product-catalog/family/{fam['id']}/submit-review")
    lst = (await client.get(
        "/api/product-onboarding-reviews", params={"status": "ready_for_review"}
    )).json()
    assert any(it["family_id"] == fam["id"] for it in lst["items"])
    assert (await client.get(
        "/api/product-onboarding-reviews", params={"status": "bogus"}
    )).status_code == 422


# ============================ 混淆关系 ============================


@pytest.mark.asyncio
async def test_confusion_self_pair_rejected(client):
    fam = await _fam(client)
    r = await client.post(PAIR, json={
        "target_level": "family",
        "left_target_id": fam["id"], "right_target_id": fam["id"],
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_confusion_reverse_duplicate(client):
    a, b = await _fam(client), await _fam(client)
    r1 = await client.post(PAIR, json={
        "target_level": "family", "left_target_id": a["id"], "right_target_id": b["id"],
        "severity": "high", "reason": "外观相近",
    })
    assert r1.status_code == 201, r1.text
    pair = r1.json()
    assert pair["left_target_id"] < pair["right_target_id"]  # 统一小/大 ID
    assert pair["left"] and pair["right"]  # 两侧展示信息
    # 反向创建 → 409（无方向重复）
    r2 = await client.post(PAIR, json={
        "target_level": "family", "left_target_id": b["id"], "right_target_id": a["id"],
    })
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_confusion_canonical_redirect(client):
    a, b, c = await _fam(client), await _fam(client), await _fam(client)
    await client.post(f"{FAM}/{a['id']}/merge", json={"target_id": c["id"]})
    # 用已合并的 a 创建 → 解析到 canonical c
    r = await client.post(PAIR, json={
        "target_level": "family", "left_target_id": a["id"], "right_target_id": b["id"],
    })
    assert r.status_code == 201
    ids = {r.json()["left_target_id"], r.json()["right_target_id"]}
    assert ids == {c["id"], b["id"]}
    # 合并到同一 canonical 视为自混淆
    r2 = await client.post(PAIR, json={
        "target_level": "family", "left_target_id": a["id"], "right_target_id": c["id"],
    })
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_confusion_features_validation_and_update(client):
    a, b = await _fam(client), await _fam(client)
    # 缺 feature 名 → 422
    r = await client.post(PAIR, json={
        "target_level": "family", "left_target_id": a["id"], "right_target_id": b["id"],
        "distinguishing_features": [{"feature": ""}],
    })
    assert r.status_code == 422
    p = (await client.post(PAIR, json={
        "target_level": "family", "left_target_id": a["id"], "right_target_id": b["id"],
        "distinguishing_features": [{
            "feature": "接口结构", "left_value": "结构A", "right_value": "结构B",
            "visible_in_reference": True, "identity_relevant": True,
        }],
    })).json()
    assert p["distinguishing_features"][0]["feature"] == "接口结构"
    u = await client.patch(f"{PAIR}/{p['id']}", json={"severity": "low"})
    assert u.status_code == 200 and u.json()["severity"] == "low"
    # 归档 → 默认列表隐藏 → 恢复
    await client.post(f"{PAIR}/{p['id']}/archive")
    lst = (await client.get(
        f"/api/product-catalog/family/{a['id']}/confusions"
    )).json()
    assert all(it["id"] != p["id"] for it in lst["items"])
    assert (await client.post(f"{PAIR}/{p['id']}/restore")).json()["status"] == "active"


@pytest.mark.asyncio
async def test_confusion_archived_target_rejected(client):
    cat = await _cat(client, active=True)
    a = await _fam(client, cat["id"])
    b = await _fam(client, cat["id"])
    await client.post(f"{FAM}/{a['id']}/archive")
    r = await client.post(PAIR, json={
        "target_level": "family", "left_target_id": a["id"], "right_target_id": b["id"],
    })
    assert r.status_code == 422


# ============================ 变更历史（append-only）============================


@pytest.mark.asyncio
async def test_revision_recorded_and_monotonic(client):
    fam = await _fam(client)
    await client.patch(f"{FAM}/{fam['id']}", json={"name_zh": f"改-{_u()}"})
    revs = (await client.get(
        f"/api/product-catalog/family/{fam['id']}/revisions"
    )).json()["items"]
    actions = [r["action"] for r in revs]
    assert "create" in actions and "update" in actions
    nums = [r["revision_number"] for r in revs]
    assert nums == sorted(nums, reverse=True) and len(set(nums)) == len(nums)
    upd = next(r for r in revs if r["action"] == "update")
    assert upd["before_data"]["name_zh"] != upd["after_data"]["name_zh"]


@pytest.mark.asyncio
async def test_revision_rename_shares_correlation_with_alias(client):
    fam = await _fam(client)
    old = fam["name_zh"]
    await client.patch(f"{FAM}/{fam['id']}", json={"name_zh": f"新-{_u()}"})
    upd = (await client.get(REV, params={
        "entity_type": "family", "entity_id": fam["id"], "action": "update",
    })).json()["items"][0]
    alias_revs = (await client.get(REV, params={"entity_type": "alias"})).json()["items"]
    same_corr = [r for r in alias_revs if r["correlation_id"] == upd["correlation_id"]]
    assert same_corr and same_corr[0]["after_data"]["alias"] == old


@pytest.mark.asyncio
async def test_revision_sanitized_no_path_no_filename(client):
    fam = await _fam(client)
    r = await _upload(client, "family", fam["id"], _png(7, 7, 7), angle="front")
    ref_id = r.json()["created"][0]["id"]
    revs = (await client.get(REV, params={
        "entity_type": "reference_asset", "entity_id": ref_id,
    })).json()["items"]
    assert revs, "参考图创建须有 revision"
    after = revs[-1]["after_data"]
    # 受控元数据在；路径/原始文件名绝不在
    assert after["angle"] == "front" and "sha256" in after
    for banned in ("image_path", "thumbnail_path", "original_filename"):
        assert banned not in after


@pytest.mark.asyncio
async def test_revision_tx_consistency_on_failure(client):
    fam = await _fam(client)
    total_before = (await client.get(REV, params={"limit": 1})).json()["total"]
    # 失败的业务操作（重复 code → 409）不得留下 revision
    r = await client.post(FAM, json={"name_zh": f"x-{_u()}", "code": fam["code"]})
    assert r.status_code == 409
    total_after = (await client.get(REV, params={"limit": 1})).json()["total"]
    assert total_after == total_before


@pytest.mark.asyncio
async def test_revision_filters_and_pagination(client):
    fam = await _fam(client)
    for i in range(3):
        await client.patch(f"{FAM}/{fam['id']}", json={"description": f"d{i}"})
    page = (await client.get(REV, params={
        "entity_type": "family", "entity_id": fam["id"], "action": "update",
        "limit": 2, "offset": 0,
    })).json()
    assert page["total"] >= 3 and len(page["items"]) == 2
    assert all(r["action"] == "update" for r in page["items"])


@pytest.mark.asyncio
async def test_revision_readonly_no_mutation_routes(client):
    fam = await _fam(client)
    rev = (await client.get(REV, params={"limit": 1})).json()["items"][0]
    # 无修改历史接口（405 Method Not Allowed）
    assert (await client.patch(f"{REV}/{rev['id']}", json={})).status_code == 405
    assert (await client.delete(f"{REV}/{rev['id']}")).status_code == 405
    assert fam["id"]  # 静默使用


@pytest.mark.asyncio
async def test_governance_events_recorded(client):
    """策略/审核/混淆 的关键事件均落 revision。"""
    _, fam = await _make_complete_family(client)
    await client.post(f"/api/product-catalog/family/{fam['id']}/submit-review")
    await client.post(f"/api/product-catalog/family/{fam['id']}/approve")
    other = await _fam(client)
    await client.post(PAIR, json={
        "target_level": "family",
        "left_target_id": fam["id"], "right_target_id": other["id"],
    })
    for etype, action in (
        ("onboarding_review", "submit_review"),
        ("onboarding_review", "approve"),
        ("confusion_pair", "create"),
        ("attribute_value", "update"),
        ("reference_asset", "create"),
    ):
        lst = (await client.get(REV, params={"entity_type": etype, "action": action})).json()
        assert lst["total"] >= 1, f"缺少 {etype}/{action} 事件"
