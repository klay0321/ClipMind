"""PR-06B 保存搜索 / 收藏 / 动态集合 API 测试（需 TEST_DATABASE_URL）。"""

from __future__ import annotations

import os

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Asset, Shot, SourceDirectory
from clipmind_shared.models.enums import AssetStatus, ShotStatus

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


async def _asset_shot(session):
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id, relative_path="a.mp4", normalized_relative_path="a.mp4",
        filename="a.mp4", extension="mp4", file_size=1, duration=5.0,
        status=AssetStatus.INDEXED, first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=1, start_time=0.0, end_time=2.0,
        duration=2.0, detector_type="fixed", status=ShotStatus.READY,
        keyframe_path="k.jpg", proxy_path="p.mp4",
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    return asset, shot


def _stub_search(monkeypatch, router_module):
    async def _run(*a, **k):
        return {"items": [], "total": 0, "page": 1, "page_size": 24}
    monkeypatch.setattr("app.services.search_service.run_shot_search", _run)
    monkeypatch.setattr("app.services.search_service.run_description_match", _run)
    monkeypatch.setattr(f"{router_module}.get_query_parser_for_settings", lambda s: None)
    monkeypatch.setattr(f"{router_module}.get_query_embedding_provider", lambda s: None)


# ============================ Saved Search ============================


async def test_saved_search_crud_strips_pagination_and_lock(client):
    body = {"name": "我的搜索", "search_kind": "shot_search",
            "query": {"query": "户外 产品", "page": 3, "page_size": 50, "brands": ["A"]}}
    r = await client.post("/api/saved-searches", json=body)
    assert r.status_code == 201
    sid = r.json()["id"]
    assert "page" not in r.json()["query"] and "page_size" not in r.json()["query"]
    assert r.json()["query"]["brands"] == ["A"]

    # 乐观锁更新
    r = await client.patch(f"/api/saved-searches/{sid}", json={"name": "改名", "lock_version": 1})
    assert r.status_code == 200 and r.json()["name"] == "改名"
    r = await client.patch(f"/api/saved-searches/{sid}", json={"name": "x", "lock_version": 1})
    assert r.status_code == 409  # 旧 lock_version

    assert (await client.delete(f"/api/saved-searches/{sid}")).status_code == 204


async def test_saved_search_run(client, monkeypatch):
    _stub_search(monkeypatch, "app.routers.saved_searches")
    r = await client.post("/api/saved-searches", json={
        "name": "s", "search_kind": "shot_search", "query": {"query": "x"}})
    sid = r.json()["id"]
    r = await client.post(f"/api/saved-searches/{sid}/run", params={"page": 1, "page_size": 10})
    assert r.status_code == 200
    assert r.json()["total"] == 0


# ============================ Favorite ============================


async def test_favorite_constraints_and_dedupe(client, session):
    asset, shot = await _asset_shot(session)
    # shot 收藏
    r = await client.post("/api/favorites", json={"target_type": "shot", "shot_id": shot.id})
    assert r.status_code == 201
    fid = r.json()["id"]
    # 去重幂等
    r2 = await client.post("/api/favorites", json={"target_type": "shot", "shot_id": shot.id})
    assert r2.json()["id"] == fid
    # asset 收藏需 asset_id（给 shot_id 报 422）
    r = await client.post("/api/favorites", json={"target_type": "asset", "shot_id": shot.id})
    assert r.status_code == 422
    # search_result 解析到 shot_id
    r = await client.post("/api/favorites", json={
        "target_type": "search_result", "shot_id": shot.id, "context": {"score": 0.9}})
    assert r.status_code == 201

    # 列表 + 类型筛选 + 内嵌 shot
    r = await client.get("/api/favorites", params={"target_type": "shot"})
    assert r.json()["total"] == 1 and r.json()["items"][0]["shot"]["id"] == shot.id

    # 删除收藏不删 shot
    assert (await client.delete(f"/api/favorites/{fid}")).status_code == 204
    assert (await client.get(f"/api/shots/{shot.id}")).status_code == 200


async def test_favorite_context_rejects_paths(client, session):
    asset, shot = await _asset_shot(session)
    r = await client.post("/api/favorites", json={
        "target_type": "shot", "shot_id": shot.id, "context": {"path": "/app/data/x"}})
    assert r.status_code == 422


# ============================ Dynamic Collection ============================


async def test_dynamic_collection_crud_and_archived_guard(client, monkeypatch):
    pid = (await client.post("/api/projects", json={"name": "P"})).json()["id"]
    r = await client.post(f"/api/projects/{pid}/dynamic-collections", json={
        "name": "动态A", "search_kind": "shot_search", "query": {"query": "户外", "page": 2}})
    assert r.status_code == 201
    did = r.json()["id"]
    assert "page" not in r.json()["query"]

    # 乐观锁
    r = await client.patch(f"/api/dynamic-collections/{did}",
                           json={"name": "动态B", "lock_version": 1})
    assert r.status_code == 200
    r = await client.patch(f"/api/dynamic-collections/{did}",
                           json={"name": "x", "lock_version": 1})
    assert r.status_code == 409

    # run（实时计算，stub）
    _stub_search(monkeypatch, "app.routers.dynamic_collections")
    r = await client.get(f"/api/dynamic-collections/{did}/shots", params={"page": 1, "page_size": 5})
    assert r.status_code == 200

    # 归档项目下只读：创建/修改 409
    cur = (await client.get(f"/api/projects/{pid}")).json()["lock_version"]
    assert (await client.post(f"/api/projects/{pid}/archive",
                              json={"lock_version": cur})).status_code == 200
    r = await client.post(f"/api/projects/{pid}/dynamic-collections", json={
        "name": "x", "search_kind": "shot_search", "query": {"query": "y"}})
    assert r.status_code == 409
    # 运行仍允许
    r = await client.get(f"/api/dynamic-collections/{did}/shots")
    assert r.status_code == 200
