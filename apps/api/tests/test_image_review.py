"""IMG-REVIEW 图片审核测试（需要 TEST_DATABASE_URL）。

锁定：查看视图（AI + 审核 + effective 一次取全）；confirm/modify/reject/
reopen 状态机；乐观锁并发冲突 409；modify schema 校验 422；非图片素材 422；
驳回后 effective=rejected；事件审计 object_type=asset_image。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    AssetImageAnalysis,
    ReviewEvent,
    SourceDirectory,
)
from clipmind_shared.models.enums import AIShotAnalysisStatus, AssetStatus
from sqlalchemy import select

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)

AI_RESULT = {
    "one_line": "一块柔性LED屏展示动态图案。",
    "search_keywords": ["LED屏", "动态图案"],
    "confidence": 0.9,
}


async def _seed_image_asset(session, *, with_ai: bool = True) -> Asset:
    tag = uuid.uuid4().hex[:8]
    sd = SourceDirectory(
        name=f"ir-{tag}", mount_path="/app/source", include_extensions=["jpg"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    asset = Asset(
        source_directory_id=sd.id, relative_path=f"{tag}.jpg",
        normalized_relative_path=f"{tag}.jpg", filename=f"{tag}.jpg", extension="jpg",
        file_size=10, media_kind="image", status=AssetStatus.INDEXED,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    if with_ai:
        session.add(
            AssetImageAnalysis(
                asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
                parsed_result=AI_RESULT, input_fingerprint=uuid.uuid4().hex,
            )
        )
        await session.commit()
    return asset


async def test_view_and_confirm_flow(client, session):
    asset = await _seed_image_asset(session)
    # 初始视图：AI 结果生效、未审核
    r = await client.get(f"/api/assets/{asset.id}/image-analysis")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["ai_status"] == "completed"
    assert v["review_status"] == "unreviewed" and v["lock_version"] == 0
    assert v["effective_source"] == "ai"
    assert v["effective_result"]["one_line"] == AI_RESULT["one_line"]

    # 确认 → human 生效
    r2 = await client.post(
        f"/api/assets/{asset.id}/image-review?action=confirm",
        json={"lock_version": 0, "reviewer_label": "测试员"},
    )
    assert r2.status_code == 200, r2.text
    v2 = r2.json()
    assert v2["review_status"] == "confirmed" and v2["lock_version"] == 1
    assert v2["effective_source"] == "human"
    assert v2["effective_result"]["one_line"] == AI_RESULT["one_line"]

    # 审计事件
    events = (
        (await session.execute(
            select(ReviewEvent).where(
                ReviewEvent.object_type == "asset_image",
                ReviewEvent.object_id == asset.id,
            )
        )).scalars().all()
    )
    assert len(events) == 1 and events[0].action.value == "confirm"


async def test_modify_and_reject_effective(client, session):
    asset = await _seed_image_asset(session)
    # modify：人工描述取代 AI
    r = await client.post(
        f"/api/assets/{asset.id}/image-review?action=modify",
        json={
            "lock_version": 0,
            "confirmed_result": {**AI_RESULT, "one_line": "人工修正：车载柔性屏特写。"},
        },
    )
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["review_status"] == "modified"
    assert v["effective_result"]["one_line"].startswith("人工修正")

    # reopen → 回到待审（AI 重新生效）
    r2 = await client.post(
        f"/api/assets/{asset.id}/image-review?action=reopen",
        json={"lock_version": v["lock_version"]},
    )
    assert r2.status_code == 200
    assert r2.json()["effective_source"] == "ai"

    # reject → 无有效结果
    r3 = await client.post(
        f"/api/assets/{asset.id}/image-review?action=reject",
        json={"lock_version": r2.json()["lock_version"]},
    )
    assert r3.status_code == 200
    v3 = r3.json()
    assert v3["review_status"] == "rejected"
    assert v3["effective_source"] == "rejected" and v3["effective_result"] is None


async def test_guards(client, session):
    asset = await _seed_image_asset(session)
    # 乐观锁冲突
    await client.post(
        f"/api/assets/{asset.id}/image-review?action=confirm", json={"lock_version": 0}
    )
    r = await client.post(
        f"/api/assets/{asset.id}/image-review?action=reopen", json={"lock_version": 0}
    )
    assert r.status_code == 409  # 已是 1

    # modify 无 confirmed_result → 422
    r2 = await client.post(
        f"/api/assets/{asset.id}/image-review?action=modify",
        json={"lock_version": 1},
    )
    assert r2.status_code == 422

    # modify schema 非法 → 422
    await client.post(
        f"/api/assets/{asset.id}/image-review?action=reopen", json={"lock_version": 1}
    )
    r3 = await client.post(
        f"/api/assets/{asset.id}/image-review?action=modify",
        json={"lock_version": 2, "confirmed_result": {"confidence": 5}},
    )
    assert r3.status_code == 422

    # 非图片素材 → 422
    tag = uuid.uuid4().hex[:8]
    sd = SourceDirectory(
        name=f"irv-{tag}", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    video = Asset(
        source_directory_id=sd.id, relative_path=f"{tag}.mp4",
        normalized_relative_path=f"{tag}.mp4", filename=f"{tag}.mp4", extension="mp4",
        file_size=10, media_kind="video", status=AssetStatus.INDEXED,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(video)
    await session.commit()
    r4 = await client.get(f"/api/assets/{video.id}/image-analysis")
    assert r4.status_code == 422
