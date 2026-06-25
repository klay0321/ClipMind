"""PR-03B.1 标签投影测试（worker，需要 TEST_DATABASE_URL）。

坐实：AI/human 投影幂等（重复运行不产生重复 active）、旧 active 投影置 inactive、AI/human 共存。
"""

from __future__ import annotations

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIShotAnalysis,
    Asset,
    Shot,
    ShotTag,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AIShotAnalysisStatus,
    AssetStatus,
    ShotStatus,
    TagSource,
)
from sqlalchemy import func, select

from clipmind_worker.ai.projection import project_ai_tags, project_human_tags

PARSED = {"scene": "室内", "action": "展示", "risk_flags": ["竞品"]}


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
        provider="fake", model="m", input_fingerprint="fp", parsed_result=PARSED,
    )
    session.add(ai)
    session.commit()
    session.refresh(ai)
    return asset, shot, ai


def _count_active(session, shot_id, source):
    return int(
        session.execute(
            select(func.count())
            .select_from(ShotTag)
            .where(
                ShotTag.shot_id == shot_id,
                ShotTag.source == source,
                ShotTag.active.is_(True),
            )
        ).scalar()
    )


def test_project_ai_idempotent(session):
    asset, shot, ai = _seed(session)
    n1 = project_ai_tags(
        session, shot_id=shot.id, parsed=PARSED, ai_analysis_id=ai.id, confidence=0.5
    )
    session.commit()
    assert n1 == 3  # scene + action + risk
    assert _count_active(session, shot.id, TagSource.AI) == 3
    # 重复投影：旧 active 置 inactive 再写新，幂等无重复 active
    project_ai_tags(session, shot_id=shot.id, parsed=PARSED, ai_analysis_id=ai.id, confidence=0.5)
    session.commit()
    assert _count_active(session, shot.id, TagSource.AI) == 3


def test_human_and_ai_coexist(session):
    asset, shot, ai = _seed(session)
    project_ai_tags(session, shot_id=shot.id, parsed=PARSED, ai_analysis_id=ai.id, confidence=0.5)
    session.commit()
    project_human_tags(
        session, shot_id=shot.id, confirmed_result={"scene": "户外"},
        reviewer_label="local", source_ai_analysis_id=ai.id,
    )
    session.commit()
    # AI 与 human 投影共存（各自 active），互不覆盖历史
    assert _count_active(session, shot.id, TagSource.AI) == 3
    assert _count_active(session, shot.id, TagSource.HUMAN) == 1
