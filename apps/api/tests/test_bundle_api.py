"""PR-06B 多镜头 ZIP 打包 API 测试（需 TEST_DATABASE_URL）：校验与限制。"""

from __future__ import annotations

import os

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Asset, Shot, SourceDirectory
from clipmind_shared.models.enums import AssetStatus, ShotStatus

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


async def _shot(session, seq, *, status=ShotStatus.READY, dur=2.0):
    sd = SourceDirectory(
        name=f"d{seq}", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id, relative_path=f"a{seq}.mp4",
        normalized_relative_path=f"a{seq}.mp4", filename=f"a{seq}.mp4", extension="mp4",
        file_size=1, duration=10.0, status=AssetStatus.INDEXED,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=seq, start_time=0.0, end_time=dur,
        duration=dur, detector_type="fixed", status=status,
        keyframe_path="k.jpg", proxy_path="p.mp4",
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    return shot


async def test_bundle_create_valid(client, session, monkeypatch):
    monkeypatch.setattr(
        "app.services.bundle_service.enqueue_export_bundle", lambda bid: f"bt-{bid}"
    )
    s1 = await _shot(session, 1)
    s2 = await _shot(session, 2)
    r = await client.post("/api/exports/bundle", json={"shot_ids": [s1.id, s2.id, s1.id]})
    assert r.status_code == 202
    assert r.json()["shot_count"] == 2  # 去重
    assert r.json()["status"] == "queued"
    # 进入导出中心
    r = await client.get("/api/export-center", params={"kind": "bundle"})
    assert r.json()["total"] == 1


async def test_bundle_rejects_missing_and_not_ready(client, session, monkeypatch):
    monkeypatch.setattr(
        "app.services.bundle_service.enqueue_export_bundle", lambda bid: f"bt-{bid}"
    )
    ready = await _shot(session, 1)
    pending = await _shot(session, 2, status=ShotStatus.PENDING)
    # 不存在
    r = await client.post("/api/exports/bundle", json={"shot_ids": [ready.id, 99999]})
    assert r.status_code == 422
    # 未就绪
    r = await client.post("/api/exports/bundle", json={"shot_ids": [ready.id, pending.id]})
    assert r.status_code == 422


async def test_bundle_rejects_over_limit(client, session, monkeypatch):
    monkeypatch.setattr(
        "app.services.bundle_service.enqueue_export_bundle", lambda bid: f"bt-{bid}"
    )
    s1 = await _shot(session, 1)
    r = await client.post("/api/exports/bundle", json={"shot_ids": [s1.id] * 1, "mode": "reencode"})
    # 单个有效；超上限用伪造 id 列表触发数量校验
    big = list(range(1, 60))
    r = await client.post("/api/exports/bundle", json={"shot_ids": big})
    assert r.status_code == 422
