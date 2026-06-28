"""PR-06A 素材集合 API 测试（需要 TEST_DATABASE_URL）。

覆盖：集合 CRUD、乐观锁、归档项目守卫、镜头成员（批量/移除/重排）、
同一 Shot 进多集合、删除集合不删 Shot。
"""

from __future__ import annotations

import os

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Asset, Shot, SourceDirectory
from clipmind_shared.models.enums import AssetStatus, ShotStatus

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


async def _seed_asset(session, *, filename="c.mp4") -> Asset:
    sd = SourceDirectory(
        name="d",
        mount_path="/app/source",
        include_extensions=["mp4"],
        exclude_patterns=[],
        recursive=True,
        read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id,
        relative_path=filename,
        normalized_relative_path=filename,
        filename=filename,
        extension="mp4",
        file_size=1,
        duration=5.0,
        status=AssetStatus.INDEXED,
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


async def _seed_shot(session, asset, *, seq=1) -> Shot:
    shot = Shot(
        asset_id=asset.id,
        generation=1,
        sequence_no=seq,
        start_time=0.0,
        end_time=1.0,
        duration=1.0,
        detector_type="fixed",
        status=ShotStatus.READY,
        keyframe_path=f"k/{asset.id}-{seq}.jpg",
        proxy_path=f"p/{asset.id}-{seq}.mp4",
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    return shot


async def _project(client, name="项目"):
    r = await client.post("/api/projects", json={"name": name})
    return r.json()["id"]


async def _collection(client, pid, name="集合"):
    r = await client.post(f"/api/projects/{pid}/collections", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------- 集合 CRUD ----------------


async def test_create_collection(client):
    pid = await _project(client)
    c = await _collection(client, pid, name="  Hook  ")
    assert c["name"] == "Hook"
    assert c["project_id"] == pid
    assert c["lock_version"] == 1
    assert c["shot_count"] == 0


async def test_create_collection_missing_project_404(client):
    r = await client.post("/api/projects/999999/collections", json={"name": "X"})
    assert r.status_code == 404


async def test_create_collection_archived_project_409(client):
    pid = await _project(client)
    await client.post(f"/api/projects/{pid}/archive", json={"lock_version": 1})
    r = await client.post(f"/api/projects/{pid}/collections", json={"name": "X"})
    assert r.status_code == 409


async def test_duplicate_collection_names_allowed(client):
    pid = await _project(client)
    a = await _collection(client, pid, name="同名")
    b = await _collection(client, pid, name="同名")
    assert a["id"] != b["id"]


async def test_update_collection_optimistic_lock(client):
    pid = await _project(client)
    cid = (await _collection(client, pid))["id"]
    r = await client.patch(
        f"/api/collections/{cid}", json={"lock_version": 1, "name": "新集合"}
    )
    assert r.status_code == 200
    assert r.json()["lock_version"] == 2
    r2 = await client.patch(f"/api/collections/{cid}", json={"lock_version": 1, "name": "X"})
    assert r2.status_code == 409


async def test_update_collection_rejects_unknown_field(client):
    pid = await _project(client)
    cid = (await _collection(client, pid))["id"]
    r = await client.patch(
        f"/api/collections/{cid}", json={"lock_version": 1, "project_id": 999}
    )
    assert r.status_code == 422


async def test_get_collection_404(client):
    r = await client.get("/api/collections/999999")
    assert r.status_code == 404


# ---------------- 成员 / 删除安全 ----------------


async def test_delete_collection_keeps_shot(client, session):
    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset)
    pid = await _project(client)
    cid = (await _collection(client, pid))["id"]
    await client.post(f"/api/collections/{cid}/shots/batch", json={"ids": [shot.id]})
    d = await client.delete(f"/api/collections/{cid}")
    assert d.status_code == 204
    # 集合没了，但 Shot 仍在
    assert (await client.get(f"/api/collections/{cid}")).status_code == 404
    assert await session.get(Shot, shot.id) is not None


async def test_same_shot_in_multiple_collections(client, session):
    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset)
    pid = await _project(client)
    c1 = (await _collection(client, pid, name="C1"))["id"]
    c2 = (await _collection(client, pid, name="C2"))["id"]
    r1 = await client.post(f"/api/collections/{c1}/shots/batch", json={"ids": [shot.id]})
    r2 = await client.post(f"/api/collections/{c2}/shots/batch", json={"ids": [shot.id]})
    assert r1.json()["completed"] == [shot.id]
    assert r2.json()["completed"] == [shot.id]
    assert (await client.get(f"/api/collections/{c1}/shots")).json()["total"] == 1
    assert (await client.get(f"/api/collections/{c2}/shots")).json()["total"] == 1


async def test_batch_add_shots_partial_and_dup(client, session):
    asset = await _seed_asset(session)
    s1 = await _seed_shot(session, asset, seq=1)
    s2 = await _seed_shot(session, asset, seq=2)
    pid = await _project(client)
    cid = (await _collection(client, pid))["id"]
    r = await client.post(
        f"/api/collections/{cid}/shots/batch",
        json={"ids": [s1.id, s2.id, 999999]},
    )
    assert set(r.json()["completed"]) == {s1.id, s2.id}
    assert r.json()["failed"][0]["id"] == 999999
    # 重复 → skipped
    r2 = await client.post(f"/api/collections/{cid}/shots/batch", json={"ids": [s1.id]})
    assert r2.json()["skipped"] == [s1.id]
    # 集合成员数
    g = await client.get(f"/api/collections/{cid}")
    assert g.json()["shot_count"] == 2


async def test_remove_shot_keeps_shot(client, session):
    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset)
    pid = await _project(client)
    cid = (await _collection(client, pid))["id"]
    await client.post(f"/api/collections/{cid}/shots/batch", json={"ids": [shot.id]})
    d = await client.delete(f"/api/collections/{cid}/shots/{shot.id}")
    assert d.status_code == 204
    assert (await client.delete(f"/api/collections/{cid}/shots/{shot.id}")).status_code == 404
    assert await session.get(Shot, shot.id) is not None


async def test_reorder_collection_shots(client, session):
    asset = await _seed_asset(session)
    s1 = await _seed_shot(session, asset, seq=1)
    s2 = await _seed_shot(session, asset, seq=2)
    s3 = await _seed_shot(session, asset, seq=3)
    pid = await _project(client)
    cid = (await _collection(client, pid))["id"]
    await client.post(
        f"/api/collections/{cid}/shots/batch", json={"ids": [s1.id, s2.id, s3.id]}
    )
    r = await client.post(
        f"/api/collections/{cid}/shots/reorder",
        json={"ids": [s3.id, s2.id, s1.id], "lock_version": 1},
    )
    assert r.status_code == 200
    assert r.json()["lock_version"] == 2
    lst = await client.get(f"/api/collections/{cid}/shots")
    assert [s["id"] for s in lst.json()["items"]] == [s3.id, s2.id, s1.id]
    # 不完整 → 422
    assert (
        await client.post(
            f"/api/collections/{cid}/shots/reorder",
            json={"ids": [s1.id], "lock_version": 2},
        )
    ).status_code == 422
    # 过期 lock → 409
    assert (
        await client.post(
            f"/api/collections/{cid}/shots/reorder",
            json={"ids": [s1.id, s2.id, s3.id], "lock_version": 1},
        )
    ).status_code == 409


async def test_archived_project_blocks_collection_mutations(client, session):
    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset)
    pid = await _project(client)
    cid = (await _collection(client, pid))["id"]
    await client.post(f"/api/collections/{cid}/shots/batch", json={"ids": [shot.id]})
    # 归档项目
    await client.post(f"/api/projects/{pid}/archive", json={"lock_version": 1})
    # 集合写操作全部 409；读仍可
    assert (await client.get(f"/api/collections/{cid}")).status_code == 200
    assert (
        await client.patch(f"/api/collections/{cid}", json={"lock_version": 1, "name": "x"})
    ).status_code == 409
    assert (
        await client.post(f"/api/collections/{cid}/shots/batch", json={"ids": [shot.id]})
    ).status_code == 409
    assert (
        await client.delete(f"/api/collections/{cid}/shots/{shot.id}")
    ).status_code == 409
    assert (await client.delete(f"/api/collections/{cid}")).status_code == 409
