"""PR-03B Gate B：产品库 / 别名 / 参考图安全 / 素材产品 / 候选 / 标签 / 汇总 / 筛选 测试。"""

from __future__ import annotations

import base64

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIShotAnalysis,
    Asset,
    Shot,
    ShotTag,
    SourceDirectory,
    Tag,
)
from clipmind_shared.models.enums import (
    AIShotAnalysisStatus,
    AssetStatus,
    ShotStatus,
    TagSource,
)
from clipmind_shared.review import normalize_name, projected_tags
from sqlalchemy import select

from app.config import Settings
from app.services import product_service
from app.services.product_service import ProductError

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class _Stream:
    def __init__(self, data: bytes):
        self._data = data
        self._i = 0

    async def read(self, n: int) -> bytes:
        chunk = self._data[self._i : self._i + n]
        self._i += len(chunk)
        return chunk


async def _seed_shot(session, *, scene="室内", risk=None, product_name=None):
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id, relative_path="v.mp4", normalized_relative_path="v.mp4",
        filename="v.mp4", extension="mp4", file_size=1, status=AssetStatus.SHOT_SPLIT,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=1, start_time=0.0, end_time=1.0,
        duration=1.0, detector_type="fixed", status=ShotStatus.READY,
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    parsed = {"scene": scene, "risk_flags": risk or [], "product": {"name": product_name or ""}}
    ai = AIShotAnalysis(
        shot_id=shot.id, asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
        provider="fake", model="m", input_fingerprint="fp", parsed_result=parsed,
    )
    session.add(ai)
    await session.commit()
    await session.refresh(ai)
    # 模拟 worker 的 AI 标签投影（projection-first 筛选/统计的事实来源）
    for tag_type, tag_name in projected_tags(parsed):
        norm = normalize_name(tag_name)
        tag = (
            await session.execute(
                select(Tag).where(Tag.tag_type == tag_type, Tag.normalized_name == norm)
            )
        ).scalars().first()
        if tag is None:
            tag = Tag(tag_type=tag_type, tag_name=tag_name, normalized_name=norm)
            session.add(tag)
            await session.commit()
            await session.refresh(tag)
        session.add(
            ShotTag(
                shot_id=shot.id, tag_id=tag.id, source=TagSource.AI,
                source_ai_analysis_id=ai.id, active=True,
            )
        )
    await session.commit()
    return asset, shot


# ---- 产品 CRUD + 别名 ----

async def test_product_crud_and_archive(client):
    r = await client.post("/api/products", json={"name": "充电器", "sku": "PG-X1"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert (await client.get(f"/api/products/{pid}")).json()["sku"] == "PG-X1"
    await client.put(f"/api/products/{pid}", json={"brand": "PowerGo"})
    assert (await client.get(f"/api/products/{pid}")).json()["brand"] == "PowerGo"
    assert (await client.post(f"/api/products/{pid}/archive")).json()["status"] == "archived"
    # 无物理删除：归档后仍可读
    assert (await client.get(f"/api/products/{pid}")).status_code == 200


async def test_alias_dup_rejected_and_delete(client):
    pid = (await client.post("/api/products", json={"name": "p"})).json()["id"]
    a = await client.post(f"/api/products/{pid}/aliases", json={"alias": "小钢炮"})
    assert a.status_code == 201
    # 同产品同名（标准化）别名拒绝
    dup = await client.post(f"/api/products/{pid}/aliases", json={"alias": "小钢炮"})
    assert dup.status_code == 422
    aid = a.json()["id"]
    assert (await client.delete(f"/api/products/{pid}/aliases/{aid}")).status_code == 204


# ---- 参考图安全（service 级，避免容器路径依赖）----

async def test_image_upload_validates_content(session, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.services.product_service.get_settings", lambda: Settings(data_dir=str(tmp_path))
    )
    p = await product_service.create_product(session, {"name": "x"})
    img = await product_service.add_image(session, p.id, filename="a.png", stream=_Stream(_PNG))
    assert img.image_path == f"products/{p.id}/images/{img.image_path.split('/')[-1]}"
    # 非图片内容拒绝（扩展名伪装）
    with pytest.raises(ProductError):
        await product_service.add_image(
            session, p.id, filename="b.png", stream=_Stream(b"not an image")
        )
    # 不支持的扩展名拒绝
    with pytest.raises(ProductError):
        await product_service.add_image(session, p.id, filename="c.txt", stream=_Stream(_PNG))


# ---- 素材产品 + 主产品约束 ----

async def test_asset_products_and_primary_constraint(client, session):
    asset, shot = await _seed_shot(session)
    pid = (await client.post("/api/products", json={"name": "充电器"})).json()["id"]
    # 设主产品前必须先在人工产品关系中
    no_rel = await client.put(
        f"/api/assets/{asset.id}/primary-product", json={"product_id": pid}
    )
    assert no_rel.status_code == 422
    # 设置人工产品关系
    r = await client.put(f"/api/assets/{asset.id}/products", json={"product_ids": [pid]})
    assert r.status_code == 200 and r.json()[0]["product_id"] == pid
    # 现在可设主产品
    r2 = await client.put(f"/api/assets/{asset.id}/primary-product", json={"product_id": pid})
    assert r2.status_code == 200 and r2.json()["id"] == pid


# ---- 候选匹配 ----

async def test_shot_product_candidates(client, session):
    asset, shot = await _seed_shot(session, product_name="充电器")
    p1 = (await client.post("/api/products", json={"name": "充电器", "sku": "X1"})).json()["id"]
    await client.post("/api/products", json={"name": "充电器"})  # 同名歧义
    cands = (await client.get(f"/api/shots/{shot.id}/product-candidates")).json()
    assert len(cands) >= 2  # 同名返回多个候选，不自行选择
    assert cands[0]["match_type"] == "name"
    assert any(c["product_id"] == p1 for c in cands)


# ---- 标签字典 ----

async def test_tag_crud_dup_archive(client):
    r = await client.post("/api/tags", json={"tag_type": "scene", "tag_name": "室内"})
    assert r.status_code == 201
    tid = r.json()["id"]
    # 同类型同名（标准化）拒绝
    dup = await client.post("/api/tags", json={"tag_type": "scene", "tag_name": "室内"})
    assert dup.status_code == 422
    assert (await client.post(f"/api/tags/{tid}/archive")).json()["status"] == "archived"


# ---- 素材汇总 ----

async def test_review_summary_status(client, session):
    asset, shot = await _seed_shot(session, risk=["竞品"])
    body = (await client.get(f"/api/assets/{asset.id}/review-summary")).json()
    assert body["total_shots"] == 1
    assert body["unreviewed_count"] == 1
    assert body["risk_shot_count"] == 1  # 未审核用 AI 风险
    assert body["ai_overall_status"] == "pending_review"
    # 确认后
    await client.post(f"/api/shots/{shot.id}/review/confirm", json={"lock_version": 0})
    body2 = (await client.get(f"/api/assets/{asset.id}/review-summary")).json()
    assert body2["confirmed_count"] == 1
    assert body2["ai_overall_status"] == "completed"


# ---- 镜头后端筛选 ----

async def test_shot_filter_by_scene_and_risk(client, session):
    asset, shot = await _seed_shot(session, scene="室内", risk=["竞品"])
    # 命中
    hit = (await client.get(f"/api/shot-search?asset_id={asset.id}&scene=室内")).json()
    assert hit["total"] == 1
    risk = (await client.get(f"/api/shot-search?asset_id={asset.id}&risk=竞品")).json()
    assert risk["total"] == 1
    # 不命中
    miss = (await client.get(f"/api/shot-search?asset_id={asset.id}&scene=户外")).json()
    assert miss["total"] == 0


async def test_shot_filter_excludes_rejected(client, session):
    asset, shot = await _seed_shot(session, scene="室内")
    # 驳回后默认排除
    await client.post(f"/api/shots/{shot.id}/review/reject", json={"lock_version": 0})
    default = (await client.get(f"/api/shot-search?asset_id={asset.id}")).json()
    assert default["total"] == 0
    incl = (await client.get(f"/api/shot-search?asset_id={asset.id}&include_excluded=true")).json()
    assert incl["total"] == 1


async def test_shot_filter_human_priority(client, session):
    asset, shot = await _seed_shot(session, scene="室内")
    # 人工改为户外
    await client.post(
        f"/api/shots/{shot.id}/review/modify",
        json={"lock_version": 0, "confirmed_result": {"scene": "户外"}},
    )
    # 有效结果筛选：户外命中，室内不命中（人工优先）
    out = (await client.get(f"/api/shot-search?asset_id={asset.id}&scene=户外")).json()
    assert out["total"] == 1
    ind = (await client.get(f"/api/shot-search?asset_id={asset.id}&scene=室内")).json()
    assert ind["total"] == 0
