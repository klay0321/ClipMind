"""Gate B：检索文档回填任务选取逻辑测试（worker，需 TEST_DATABASE_URL）。"""

from __future__ import annotations

from clipmind_shared.ai import FakeEmbeddingProvider
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    Shot,
    ShotSearchDocument,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AssetStatus,
    SearchDocumentStatus,
    SearchEmbeddingStatus,
    ShotStatus,
)

from clipmind_worker.search.indexer import rebuild_shot_document
from clipmind_worker.search.tasks import _backfill_shot_ids


def _asset(session):
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    session.commit()
    asset = Asset(
        source_directory_id=sd.id, relative_path="v.mp4", normalized_relative_path="v.mp4",
        filename="v.mp4", extension="mp4", file_size=1, status=AssetStatus.SHOT_SPLIT,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    session.commit()
    return asset


def _shot(session, asset, seq, status=ShotStatus.READY):
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=seq, start_time=0.0, end_time=1.0,
        duration=1.0, detector_type="fixed", status=status,
    )
    session.add(shot)
    session.commit()
    return shot


def test_backfill_all_ready_shots(session):
    asset = _asset(session)
    s1 = _shot(session, asset, 1)
    s2 = _shot(session, asset, 2)
    _shot(session, asset, 3, status=ShotStatus.PENDING)  # 非 ready 不入选
    ids = _backfill_shot_ids(session, only_failed=False, limit=100)
    assert s1.id in ids and s2.id in ids
    assert len(ids) == 2  # 仅 READY


def test_backfill_only_failed(session):
    asset = _asset(session)
    s1 = _shot(session, asset, 1)
    s2 = _shot(session, asset, 2)
    # s1 文档嵌入失败；s2 完成
    session.add(ShotSearchDocument(
        shot_id=s1.id, shot_generation=1, asset_id=asset.id,
        document_status=SearchDocumentStatus.INDEXED,
        embedding_status=SearchEmbeddingStatus.FAILED, is_searchable=True, retry_count=1,
    ))
    rebuild_shot_document(session, s2.id, FakeEmbeddingProvider(dimension=384))
    session.commit()
    ids = _backfill_shot_ids(session, only_failed=True, limit=100)
    assert ids == [s1.id]  # 仅失败文档


def test_backfill_limit(session):
    asset = _asset(session)
    for i in range(1, 6):
        _shot(session, asset, i)
    ids = _backfill_shot_ids(session, only_failed=False, limit=3)
    assert len(ids) == 3  # 有界
