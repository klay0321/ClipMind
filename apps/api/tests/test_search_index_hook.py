"""审核动作提交后应入队检索文档重建（PR-04 钩子，需要 TEST_DATABASE_URL）。"""

from __future__ import annotations

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import AIShotAnalysis, Asset, Shot, SourceDirectory
from clipmind_shared.models.enums import AIShotAnalysisStatus, AssetStatus, ShotStatus

pytestmark = pytest.mark.asyncio


async def _seed(session) -> int:
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.flush()
    asset = Asset(
        source_directory_id=sd.id, relative_path="v.mp4", normalized_relative_path="v.mp4",
        filename="v.mp4", extension="mp4", file_size=1, status=AssetStatus.SHOT_SPLIT,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.flush()
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=1, start_time=0.0, end_time=1.0,
        duration=1.0, detector_type="fixed", status=ShotStatus.READY,
    )
    session.add(shot)
    await session.flush()
    session.add(
        AIShotAnalysis(
            shot_id=shot.id, asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
            provider="fake", model="m", input_fingerprint="fp", schema_version=1,
            parsed_result={"one_line": "x", "scene": "桌面"}, confidence=0.7,
        )
    )
    await session.commit()
    return shot.id


async def test_confirm_enqueues_search_rebuild(client, session, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(
        "app.routers.review.enqueue_rebuild_shot_search_doc",
        lambda sid: calls.append(sid) or f"t-{sid}",
    )
    shot_id = await _seed(session)
    resp = await client.post(
        f"/api/shots/{shot_id}/review/confirm", json={"lock_version": 0, "reviewer_label": "t"}
    )
    assert resp.status_code == 200, resp.text
    assert calls == [shot_id]


async def test_reject_enqueues_search_rebuild(client, session, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(
        "app.routers.review.enqueue_rebuild_shot_search_doc",
        lambda sid: calls.append(sid) or f"t-{sid}",
    )
    shot_id = await _seed(session)
    resp = await client.post(
        f"/api/shots/{shot_id}/review/reject", json={"lock_version": 0, "reviewer_label": "t"}
    )
    assert resp.status_code == 200, resp.text
    assert calls == [shot_id]
