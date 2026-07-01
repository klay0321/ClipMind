"""PR-A2 Gate A 后端测试：产品参考图库（上传/校验/去重/主图/归档/删除/文件服务/批量）。

自造有效 1×1 RGB PNG（内容可控、sha256 可区分），不提交任何真实图片。
需 TEST_DATABASE_URL（迁移到 0014）+ 本机 ffmpeg（宽高/缩略；缺失则宽高为空，测试仍通过）。
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


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    """把 data_dir 指向每个测试独立的临时目录（参考图落盘/服务/删除都在此）。"""
    from app.config import get_settings

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _u() -> str:
    return uuid.uuid4().hex[:8]


def _png(r: int, g: int, b: int) -> bytes:
    """构造有效 1×1 RGB PNG；不同颜色 → 不同字节 → 不同 sha256。"""
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + body + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00" + bytes([r, g, b])))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


async def _fam(client) -> dict:
    cat = (await client.post(CAT, json={"name_zh": f"类-{_u()}"})).json()
    return (await client.post(FAM, json={"name_zh": f"品-{_u()}", "category_id": cat["id"]})).json()


async def _upload(client, level, target_id, png: bytes, *, name="a.png", ct="image/png", **form):
    data = {"target_level": level, "target_id": str(target_id)}
    data.update({k: str(v) for k, v in form.items()})
    return await client.post(REF, data=data, files={"files": (name, png, ct)})


# ============================ 上传 / 校验 ============================


@pytest.mark.asyncio
async def test_upload_valid_png(client):
    fam = await _fam(client)
    r = await _upload(client, "family", fam["id"], _png(200, 10, 10), angle="front")
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["created"]) == 1 and not body["errors"]
    a = body["created"][0]
    assert a["media_type"] == "png" and a["angle"] == "front" and a["sha256"]
    # 本机有 ffprobe -> 宽高 1×1；无则为空（best-effort）
    assert a["width"] in (None, 1) and a["height"] in (None, 1)


@pytest.mark.asyncio
async def test_upload_rejects_bad_extension(client):
    fam = await _fam(client)
    r = await _upload(client, "family", fam["id"], b"not an image", name="x.txt", ct="text/plain")
    assert r.status_code == 201
    assert not r.json()["created"] and r.json()["errors"]


@pytest.mark.asyncio
async def test_upload_rejects_magic_mismatch(client):
    fam = await _fam(client)
    # PNG 内容但声明 .jpg -> 魔数校验失败
    r = await _upload(client, "family", fam["id"], _png(1, 2, 3), name="fake.jpg", ct="image/jpeg")
    assert not r.json()["created"] and r.json()["errors"]


@pytest.mark.asyncio
async def test_duplicate_same_target_conflict(client):
    fam = await _fam(client)
    png = _png(50, 60, 70)
    assert len((await _upload(client, "family", fam["id"], png)).json()["created"]) == 1
    dup = await _upload(client, "family", fam["id"], png)
    assert not dup.json()["created"] and dup.json()["errors"]  # 同目标同内容 -> 重复


@pytest.mark.asyncio
async def test_same_image_different_target_ok(client):
    fam1, fam2 = await _fam(client), await _fam(client)
    png = _png(9, 9, 9)
    assert len((await _upload(client, "family", fam1["id"], png)).json()["created"]) == 1
    assert len((await _upload(client, "family", fam2["id"], png)).json()["created"]) == 1


@pytest.mark.asyncio
async def test_batch_upload_partial_failure(client):
    fam = await _fam(client)
    files = [
        ("files", ("ok.png", _png(1, 1, 1), "image/png")),
        ("files", ("bad.txt", b"nope", "text/plain")),
        ("files", ("ok2.png", _png(2, 2, 2), "image/png")),
    ]
    r = await client.post(
        REF, data={"target_level": "family", "target_id": str(fam["id"])}, files=files
    )
    body = r.json()
    assert len(body["created"]) == 2 and len(body["errors"]) == 1  # 单张失败不影响其它


# ============================ 主图唯一 / 更新 / 生命周期 ============================


@pytest.mark.asyncio
async def test_primary_uniqueness(client):
    fam = await _fam(client)
    a = (await _upload(client, "family", fam["id"], _png(10, 0, 0))).json()["created"][0]
    b = (await _upload(client, "family", fam["id"], _png(0, 10, 0))).json()["created"][0]
    await client.post(f"{REF}/{a['id']}/primary")
    await client.post(f"{REF}/{b['id']}/primary")  # 切换主图
    rows = (await client.get(REF, params={"target_level": "family", "target_id": fam["id"]})).json()
    primaries = [x for x in rows if x["is_primary"]]
    assert len(primaries) == 1 and primaries[0]["id"] == b["id"]


@pytest.mark.asyncio
async def test_update_angle_and_quality(client):
    fam = await _fam(client)
    a = (await _upload(client, "family", fam["id"], _png(3, 3, 3))).json()["created"][0]
    r = await client.patch(
        f"{REF}/{a['id']}", json={"angle": "back", "quality_status": "qualified"}
    )
    assert r.status_code == 200 and r.json()["angle"] == "back"
    assert r.json()["quality_status"] == "qualified"
    # 未知角度 -> 422
    assert (await client.patch(f"{REF}/{a['id']}", json={"angle": "sideways"})).status_code == 422


@pytest.mark.asyncio
async def test_archive_restore_hides_from_list(client):
    fam = await _fam(client)
    a = (await _upload(client, "family", fam["id"], _png(4, 4, 4))).json()["created"][0]
    assert (await client.post(f"{REF}/{a['id']}/archive")).json()["state"] == "archived"
    rows = (await client.get(REF, params={"target_level": "family", "target_id": fam["id"]})).json()
    assert all(x["id"] != a["id"] for x in rows)
    assert (await client.post(f"{REF}/{a['id']}/restore")).json()["state"] == "active"


@pytest.mark.asyncio
async def test_delete_removes_record(client):
    fam = await _fam(client)
    a = (await _upload(client, "family", fam["id"], _png(6, 6, 6))).json()["created"][0]
    assert (await client.delete(f"{REF}/{a['id']}")).status_code == 204
    assert (await client.get(f"{REF}/{a['id']}")).status_code == 404
    assert (await client.get(f"{REF}/{a['id']}/file")).status_code == 404


# ============================ 文件服务 / 批量 / profile ============================


@pytest.mark.asyncio
async def test_serve_file_and_thumbnail(client):
    fam = await _fam(client)
    a = (await _upload(client, "family", fam["id"], _png(7, 8, 9))).json()["created"][0]
    rf = await client.get(f"{REF}/{a['id']}/file")
    assert rf.status_code == 200 and rf.content[:4] == b"\x89PNG"
    rt = await client.get(f"{REF}/{a['id']}/thumbnail")
    assert rt.status_code == 200 and len(rt.content) > 0  # 缩略或回退原图


@pytest.mark.asyncio
async def test_batch_angle_and_archive(client):
    fam = await _fam(client)
    ids = [
        (await _upload(client, "family", fam["id"], _png(i, i, i))).json()["created"][0]["id"]
        for i in (11, 12, 13)
    ]
    r = await client.post(f"{REF}/batch-angle", json={"ids": ids, "angle": "detail"})
    assert r.status_code == 200 and all(x["angle"] == "detail" for x in r.json())
    r2 = await client.post(f"{REF}/batch-archive", json={"ids": ids})
    assert r2.status_code == 200 and all(x["state"] == "archived" for x in r2.json())


@pytest.mark.asyncio
async def test_profile_counts_references(client):
    fam = await _fam(client)
    up = await _upload(client, "family", fam["id"], _png(21, 0, 0), angle="front")
    a = up.json()["created"][0]
    await _upload(client, "family", fam["id"], _png(0, 21, 0), angle="back")
    await client.post(f"{REF}/{a['id']}/primary")
    p = (await client.get(f"/api/product-catalog/family/{fam['id']}/profile")).json()
    assert p["reference_total"] == 2
    assert p["reference_by_angle"].get("front") == 1 and p["reference_by_angle"].get("back") == 1
    assert p["reference_primary_id"] == a["id"]


@pytest.mark.asyncio
async def test_reference_binds_variant_and_sku(client):
    fam = await _fam(client)
    var = (await client.post(VAR, json={"family_id": fam["id"], "name_zh": f"变-{_u()}"})).json()
    sku = (await client.post(SKU, json={"family_id": fam["id"], "name_zh": f"s-{_u()}"})).json()
    assert len((await _upload(client, "variant", var["id"], _png(31, 1, 1))).json()["created"]) == 1
    assert len((await _upload(client, "sku", sku["id"], _png(32, 2, 2))).json()["created"]) == 1
