"""EVAL：从确认绑定图片提升参考图（建议清单 + 逐张采纳）测试。

需 TEST_DATABASE_URL。自造 1×1 PNG 作为素材源文件（tmp 源目录进白名单），
不提交任何真实图片。锁定：建议只列缺参考图 family 的绑定图片；提升复用
上传守卫（sha 去重 409）；非图片/文件缺失 422；提升行带来源标记。
"""

from __future__ import annotations

import os
import struct
import uuid
import zlib

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Asset, SourceDirectory
from clipmind_shared.models.enums import AssetStatus
from clipmind_shared.models.product_media import ProductMediaLink

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)

CAT = "/api/product-categories"
FAM = "/api/product-families"
REF = "/api/product-reference-assets"
SUGGEST = f"{REF}/promotion/suggestions"
PROMOTE = f"{REF}/promotion/promote"


@pytest.fixture(autouse=True)
def _tmp_dirs(tmp_path, monkeypatch):
    """data_dir 与源根白名单都指向本测试的临时目录。"""
    from app.config import get_settings

    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALLOWED_SOURCE_ROOTS", str(src))
    get_settings.cache_clear()
    yield src
    get_settings.cache_clear()


def _u() -> str:
    return uuid.uuid4().hex[:8]


def _png(r: int, g: int, b: int) -> bytes:
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + body + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00" + bytes([r, g, b])))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


async def _fam(client, session) -> dict:
    """建 family 并置 active（建议清单只覆盖正式运营产品——两轴分离）。"""
    from clipmind_shared.models.product_catalog import ProductFamily
    from sqlalchemy import update

    cat = (await client.post(CAT, json={"name_zh": f"类-{_u()}"})).json()
    fam = (
        await client.post(FAM, json={"name_zh": f"品-{_u()}", "category_id": cat["id"]})
    ).json()
    await session.execute(
        update(ProductFamily).where(ProductFamily.id == fam["id"]).values(status="active")
    )
    await session.commit()
    return fam


async def _seed_linked_image(
    session, src_dir, family_id: int, *, png: bytes | None = None,
    media_kind: str = "image", write_file: bool = True,
) -> Asset:
    tag = _u()
    ext = "png" if media_kind == "image" else "mp4"
    sd = SourceDirectory(
        name=f"promo-{tag}", mount_path=str(src_dir), include_extensions=[ext],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    rel = f"{tag}.{ext}"
    if write_file:
        (src_dir / rel).write_bytes(png if png is not None else _png(9, 9, 9))
    asset = Asset(
        source_directory_id=sd.id, relative_path=rel, normalized_relative_path=rel,
        filename=rel, extension=ext, file_size=64, media_kind=media_kind,
        status=AssetStatus.INDEXED, first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    session.add(ProductMediaLink(asset_id=asset.id, family_id=family_id, role="primary"))
    await session.commit()
    return asset


async def test_suggestions_list_and_saturation(client, session, _tmp_dirs):
    """缺参考图 family 列出绑定图片候选；参考图补足后不再列出。"""
    fam = await _fam(client, session)
    asset = await _seed_linked_image(session, _tmp_dirs, fam["id"], png=_png(1, 2, 3))
    # 视频绑定不进建议
    await _seed_linked_image(session, _tmp_dirs, fam["id"], media_kind="video")

    body = (await client.get(SUGGEST)).json()
    mine = next(x for x in body if x["family_id"] == fam["id"])
    assert mine["active_refs"] == 0
    ids = [c["asset_id"] for c in mine["candidates"]]
    assert ids == [asset.id]  # 只有图片；primary 排前

    # 上传 3 张参考图达到建议阈值 → 该 family 不再出现
    for i in range(3):
        r = await client.post(
            REF,
            data={"target_level": "family", "target_id": str(fam["id"])},
            files={"files": (f"r{i}.png", _png(40 + i, 5, 5), "image/png")},
        )
        assert r.status_code == 201 and r.json()["created"], r.text
    body2 = (await client.get(SUGGEST)).json()
    assert all(x["family_id"] != fam["id"] for x in body2)


async def test_promote_success_then_duplicate_conflict(client, session, _tmp_dirs):
    """提升成功：201 + 来源标记 + 出现在参考图列表；同素材再提升 → sha 重复 409。"""
    fam = await _fam(client, session)
    asset = await _seed_linked_image(session, _tmp_dirs, fam["id"], png=_png(7, 8, 9))

    r = await client.post(
        PROMOTE,
        data={
            "target_level": "family", "target_id": str(fam["id"]),
            "asset_id": str(asset.id), "angle": "front",
        },
    )
    assert r.status_code == 201, r.text
    ref = r.json()
    assert ref["source_type"] == "asset_promote"
    assert f"#{asset.id}" in (ref["description"] or "")
    assert ref["angle"] == "front" and ref["sha256"]

    listing = (
        await client.get(REF, params={"target_level": "family", "target_id": fam["id"]})
    ).json()
    assert any(x["id"] == ref["id"] for x in listing)

    dup = await client.post(
        PROMOTE,
        data={
            "target_level": "family", "target_id": str(fam["id"]),
            "asset_id": str(asset.id),
        },
    )
    assert dup.status_code == 409


async def test_promote_guards(client, session, _tmp_dirs):
    """非图片素材 / 源文件缺失 / 素材不存在 → 422。"""
    fam = await _fam(client, session)
    video = await _seed_linked_image(session, _tmp_dirs, fam["id"], media_kind="video")
    ghost = await _seed_linked_image(
        session, _tmp_dirs, fam["id"], png=_png(3, 3, 3), write_file=False
    )

    for asset_id in (video.id, ghost.id, 999_999):
        r = await client.post(
            PROMOTE,
            data={
                "target_level": "family", "target_id": str(fam["id"]),
                "asset_id": str(asset_id),
            },
        )
        assert r.status_code == 422, (asset_id, r.text)
