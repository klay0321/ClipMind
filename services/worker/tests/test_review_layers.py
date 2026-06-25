"""PR-03B 四层分离的 DB 集成测试（需要 TEST_DATABASE_URL）。

坐实：AI 重新分析（更新 ai_shot_analysis）**不触碰** shot_review_state（人工层），
且 (shot_id, shot_generation) 唯一。
"""

from __future__ import annotations

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIShotAnalysis,
    Asset,
    Shot,
    ShotReviewState,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AIShotAnalysisStatus,
    AssetStatus,
    ReviewStatus,
    ShotStatus,
)
from clipmind_shared.review import effective_result
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


def _seed(session):
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    session.commit()
    session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id, relative_path="v.mp4", normalized_relative_path="v.mp4",
        filename="v.mp4", extension="mp4", file_size=1, status=AssetStatus.SHOT_SPLIT,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=1, start_time=0.0, end_time=1.0,
        duration=1.0, detector_type="fixed", status=ShotStatus.READY,
    )
    session.add(shot)
    session.commit()
    session.refresh(shot)
    ai = AIShotAnalysis(
        shot_id=shot.id, asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
        provider="fake", model="m", input_fingerprint="fp1",
        parsed_result={"one_line": "AI v1"}, confidence=0.6,
    )
    session.add(ai)
    session.commit()
    session.refresh(ai)
    return asset, shot, ai


def test_human_review_survives_ai_reanalysis(session):
    asset, shot, ai = _seed(session)
    # 人工已确认（修改后）
    review = ShotReviewState(
        shot_id=shot.id, shot_generation=shot.generation, source_ai_analysis_id=ai.id,
        source_input_fingerprint="fp1", review_status=ReviewStatus.MODIFIED,
        confirmed_result={"one_line": "人工确认结果"}, reviewer_label="local", reviewed_at=utcnow(),
    )
    session.add(review)
    session.commit()

    # AI 重新分析（同 generation）：仅更新 ai_shot_analysis
    ai.parsed_result = {"one_line": "AI v2 重分析"}
    ai.input_fingerprint = "fp2"
    session.commit()

    # 人工层未被触碰
    r = session.execute(
        select(ShotReviewState).where(ShotReviewState.shot_id == shot.id)
    ).scalar_one()
    assert r.review_status == ReviewStatus.MODIFIED
    assert r.confirmed_result == {"one_line": "人工确认结果"}

    eff = effective_result(
        ai.parsed_result, review_status=r.review_status.value,
        confirmed_result=r.confirmed_result,
    )
    assert eff.source == "human"
    assert eff.result["one_line"] == "人工确认结果"  # 人工优先，不被 AI v2 覆盖


def test_shot_review_unique_per_generation(session):
    asset, shot, ai = _seed(session)
    session.add(ShotReviewState(shot_id=shot.id, shot_generation=1))
    session.commit()
    session.add(ShotReviewState(shot_id=shot.id, shot_generation=1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
