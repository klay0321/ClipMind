"""PR-03A AI 分析 API 测试（需要 TEST_DATABASE_URL；入队被 monkeypatch，不连 Celery）。"""

from __future__ import annotations

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import AIShotAnalysis, Asset, Shot, SourceDirectory
from clipmind_shared.models.enums import AIShotAnalysisStatus, AssetStatus, ShotStatus


async def _seed_asset(session, *, status=AssetStatus.SHOT_SPLIT) -> Asset:
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id, relative_path="v.mp4", normalized_relative_path="v.mp4",
        filename="v.mp4", extension="mp4", file_size=1, status=status,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


async def _seed_shot(session, asset) -> Shot:
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=1,
        start_time=0.0, end_time=1.0, duration=1.0,
        detector_type="fixed", status=ShotStatus.READY,
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    return shot


async def test_analyze_asset_enqueues(client, session):
    asset = await _seed_asset(session)
    r = await client.post(f"/api/assets/{asset.id}/analyze")
    assert r.status_code == 202
    body = r.json()
    assert body["asset_id"] == asset.id
    assert body["status"] == "queued"
    assert body["celery_task_id"] == f"aitask-{body['run_id']}"


async def test_analyze_missing_asset_404(client):
    r = await client.post("/api/assets/999999/analyze")
    assert r.status_code == 404


async def test_analyze_source_missing_409(client, session):
    asset = await _seed_asset(session, status=AssetStatus.SOURCE_MISSING)
    r = await client.post(f"/api/assets/{asset.id}/analyze")
    assert r.status_code == 409


async def test_active_run_is_idempotent(client, session):
    asset = await _seed_asset(session)
    r1 = await client.post(f"/api/assets/{asset.id}/analyze")
    r2 = await client.post(f"/api/assets/{asset.id}/analyze")
    assert r1.json()["run_id"] == r2.json()["run_id"]


async def test_ai_analysis_status_no_run(client, session):
    asset = await _seed_asset(session)
    r = await client.get(f"/api/assets/{asset.id}/ai-analysis")
    assert r.status_code == 200
    body = r.json()
    assert body["has_run"] is False
    assert body["analyzed_total"] == 0


async def test_ai_analysis_status_after_enqueue(client, session):
    asset = await _seed_asset(session)
    await client.post(f"/api/assets/{asset.id}/analyze")
    body = (await client.get(f"/api/assets/{asset.id}/ai-analysis")).json()
    assert body["has_run"] is True
    assert body["status"] == "queued"


async def test_shot_analyze_and_no_result_yet(client, session):
    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset)
    r = await client.post(f"/api/shots/{shot.id}/analyze")
    assert r.status_code == 202
    assert r.json()["celery_task_id"] == f"aishot-{r.json()['run_id']}-{shot.id}"
    g = (await client.get(f"/api/shots/{shot.id}/ai")).json()
    assert g["has_analysis"] is False


async def test_shot_ai_with_result(client, session):
    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset)
    session.add(
        AIShotAnalysis(
            shot_id=shot.id, asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
            provider="fake", model="m", confidence=0.8,
            parsed_result={"one_line": "x", "needs_human_review": True},
        )
    )
    await session.commit()
    body = (await client.get(f"/api/shots/{shot.id}/ai")).json()
    assert body["has_analysis"] is True
    assert body["status"] == "completed"
    assert body["needs_human_review"] is True
    assert body["result"]["one_line"] == "x"


async def test_shot_ai_missing_404(client):
    r = await client.get("/api/shots/999999/ai")
    assert r.status_code == 404


async def test_provider_health(client):
    r = await client.get("/api/ai/provider/health")
    assert r.status_code == 200
    assert "configured" in r.json()
