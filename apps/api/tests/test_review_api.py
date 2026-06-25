"""PR-03B 审核 API 集成测试（需要 TEST_DATABASE_URL）。"""

from __future__ import annotations

import os

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIShotAnalysis,
    Asset,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AIShotAnalysisStatus,
    AssetStatus,
    ShotStatus,
)
from sqlalchemy import create_engine, text

AI_RESULT = {"one_line": "AI 描述", "scene": "室内", "risk_flags": ["竞品"], "confidence": 0.6}


async def _seed(session, *, fingerprint="fp1"):
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
    ai = AIShotAnalysis(
        shot_id=shot.id, asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
        provider="fake", model="m", input_fingerprint=fingerprint, parsed_result=AI_RESULT,
        confidence=0.6,
    )
    session.add(ai)
    await session.commit()
    await session.refresh(ai)
    return asset, shot, ai


def _active_human_tag_ids(shot_id: int) -> list[int]:
    """用独立同步连接读取生效的 human 标签（避开 async session 与 ASGI client 共享引擎的坑）。"""
    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "+psycopg")
    eng = create_engine(url)
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id FROM shot_tag "
                    "WHERE shot_id = :s AND source = 'human' AND active = true"
                ),
                {"s": shot_id},
            ).all()
        return [r[0] for r in rows]
    finally:
        eng.dispose()


async def test_effective_defaults_to_ai(client, session):
    asset, shot, ai = await _seed(session)
    body = (await client.get(f"/api/shots/{shot.id}/effective-result")).json()
    assert body["source"] == "ai"
    assert body["result"]["one_line"] == "AI 描述"
    assert body["review_is_stale"] is False


async def test_confirm_flow_and_projection(client, session):
    asset, shot, ai = await _seed(session)
    r = await client.post(f"/api/shots/{shot.id}/review/confirm", json={"lock_version": 0})
    assert r.status_code == 200
    state = r.json()
    assert state["review_status"] == "confirmed" and state["lock_version"] == 1

    eff = (await client.get(f"/api/shots/{shot.id}/effective-result")).json()
    assert eff["source"] == "human" and eff["confirmed"] is True

    # 投影：human 标签生效
    assert _active_human_tag_ids(shot.id)

    events = (await client.get(f"/api/shots/{shot.id}/review-events")).json()
    assert len(events) == 1 and events[0]["action"] == "confirm"


async def test_modify_uses_human_result(client, session):
    asset, shot, ai = await _seed(session)
    edited = {"one_line": "人工修正", "scene": "户外", "confidence": 0.9}
    r = await client.post(
        f"/api/shots/{shot.id}/review/modify",
        json={"lock_version": 0, "confirmed_result": edited},
    )
    assert r.status_code == 200 and r.json()["review_status"] == "modified"
    eff = (await client.get(f"/api/shots/{shot.id}/effective-result")).json()
    assert eff["source"] == "human" and eff["result"]["one_line"] == "人工修正"


async def test_optimistic_lock_conflict(client, session):
    asset, shot, ai = await _seed(session)
    # 先 confirm（lock 0 → 1）
    await client.post(f"/api/shots/{shot.id}/review/confirm", json={"lock_version": 0})
    # 用陈旧 lock_version=0 再 modify → 409
    r = await client.post(
        f"/api/shots/{shot.id}/review/modify",
        json={"lock_version": 0, "confirmed_result": {"one_line": "x"}},
    )
    assert r.status_code == 409


async def test_illegal_transition_409(client, session):
    asset, shot, ai = await _seed(session)
    await client.post(f"/api/shots/{shot.id}/review/confirm", json={"lock_version": 0})
    # confirmed → confirm 非法
    r = await client.post(f"/api/shots/{shot.id}/review/confirm", json={"lock_version": 1})
    assert r.status_code == 409


async def test_modify_requires_result_422(client, session):
    asset, shot, ai = await _seed(session)
    r = await client.post(f"/api/shots/{shot.id}/review/modify", json={"lock_version": 0})
    assert r.status_code == 422


async def test_modify_invalid_schema_422(client, session):
    asset, shot, ai = await _seed(session)
    r = await client.post(
        f"/api/shots/{shot.id}/review/modify",
        json={"lock_version": 0, "confirmed_result": {"confidence": 5}},  # 越界
    )
    assert r.status_code == 422


async def test_reject_not_searchable_and_deactivates_tags(client, session):
    asset, shot, ai = await _seed(session)
    await client.post(f"/api/shots/{shot.id}/review/confirm", json={"lock_version": 0})
    assert _active_human_tag_ids(shot.id)  # 确认后有
    await client.post(f"/api/shots/{shot.id}/review/reject", json={"lock_version": 1})
    eff = (await client.get(f"/api/shots/{shot.id}/effective-result")).json()
    assert eff["source"] == "rejected" and eff["searchable"] is False
    assert _active_human_tag_ids(shot.id) == []  # 驳回后 human 标签置 inactive


async def test_reopen_back_to_ai(client, session):
    asset, shot, ai = await _seed(session)
    await client.post(f"/api/shots/{shot.id}/review/confirm", json={"lock_version": 0})
    r = await client.post(f"/api/shots/{shot.id}/review/reopen", json={"lock_version": 1})
    assert r.json()["review_status"] == "pending_review"
    eff = (await client.get(f"/api/shots/{shot.id}/effective-result")).json()
    assert eff["source"] == "ai"


async def test_reanalysis_does_not_overwrite_and_flags_newer(client, session):
    asset, shot, ai = await _seed(session)
    await client.post(f"/api/shots/{shot.id}/review/modify",
                      json={"lock_version": 0, "confirmed_result": {"one_line": "人工"}})
    # 模拟 AI 重新分析（同 generation，新指纹）：仅改 ai_shot_analysis
    ai.input_fingerprint = "fp2"
    ai.parsed_result = {"one_line": "AI v2"}
    await session.commit()
    eff = (await client.get(f"/api/shots/{shot.id}/effective-result")).json()
    assert eff["has_newer_ai_result"] is True
    assert eff["source"] == "human" and eff["result"]["one_line"] == "人工"  # 人工不被覆盖
