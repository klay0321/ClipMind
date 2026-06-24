"""数据库层约束集成测试（需要 TEST_DATABASE_URL）。

证明"同一素材至多一个活动镜头分析运行"是 **数据库部分唯一索引** 强制的，
而非仅靠 API 代码判断。用同步会话以干净处理 IntegrityError。
"""

from __future__ import annotations

import uuid

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    Export,
    MediaProcessingRun,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AssetStatus,
    ExportStatus,
    MediaRunStatus,
    ShotStatus,
)
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError


def _make_asset(session) -> Asset:
    sd = SourceDirectory(
        name="c",
        mount_path="/app/source",
        include_extensions=["mp4"],
        exclude_patterns=[],
        recursive=True,
        read_only=True,
    )
    session.add(sd)
    session.commit()
    session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id,
        relative_path="v.mp4",
        normalized_relative_path="v.mp4",
        filename="v.mp4",
        extension="mp4",
        file_size=1,
        status=AssetStatus.INDEXED,
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def _run(asset_id: int, status: MediaRunStatus) -> MediaProcessingRun:
    return MediaProcessingRun(
        run_uuid=uuid.uuid4().hex,
        asset_id=asset_id,
        status=status,
        queued_at=utcnow(),
    )


def test_partial_unique_index_exists_in_db(session):
    """uq_active_media_run 必须实际存在于 PostgreSQL。"""
    names = {ix["name"] for ix in inspect(session.bind).get_indexes("media_processing_run")}
    assert "uq_active_media_run" in names


def test_second_active_run_rejected_by_db(session):
    asset = _make_asset(session)
    session.add(_run(asset.id, MediaRunStatus.QUEUED))
    session.commit()

    # 第二个活动运行（running）→ 数据库唯一约束拒绝
    session.add(_run(asset.id, MediaRunStatus.RUNNING))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_export_survives_asset_deletion(session):
    """删除 Asset（级联删 Shot）后：export.asset_id/shot_id 置空，来源快照与文件名/时间码保留。"""
    asset = _make_asset(session)
    asset_id, filename, relpath = asset.id, asset.filename, asset.relative_path
    shot = Shot(asset_id=asset_id, generation=1, sequence_no=1, start_time=0.0,
                end_time=2.0, duration=2.0, detector_type="fixed", status=ShotStatus.READY)
    session.add(shot)
    session.commit()
    session.refresh(shot)
    exp = Export(
        export_uuid=uuid.uuid4().hex, asset_id=asset_id, shot_id=shot.id,
        status=ExportStatus.COMPLETED, mode="reencode",
        source_asset_id=asset_id, source_shot_id=shot.id, source_generation=1,
        source_sequence_no=1, source_start_time=0.0, source_end_time=2.0,
        source_filename=filename, source_relative_path=relpath,
        output_path="exports/x/clip.mp4", filename="clip.mp4", queued_at=utcnow(),
    )
    session.add(exp)
    session.commit()
    eid = exp.id

    # 删除 Asset：级联删 Shot/MediaProcessingRun；export.asset_id/shot_id 经 FK SET NULL
    session.delete(session.get(Asset, asset_id))
    session.commit()
    session.expire_all()

    e = session.get(Export, eid)
    assert e is not None, "Asset 删除后导出记录仍保留"
    assert e.asset_id is None, "asset_id 置空（SET NULL）"
    assert e.shot_id is None, "shot_id 置空（SET NULL）"
    assert e.source_asset_id == asset_id, "来源 Asset 快照保留"
    assert e.source_filename == filename
    assert e.source_relative_path == relpath
    assert e.source_start_time == 0.0 and e.source_end_time == 2.0


def test_completed_or_failed_do_not_block_new_run(session):
    asset = _make_asset(session)
    r1 = _run(asset.id, MediaRunStatus.QUEUED)
    session.add(r1)
    session.commit()

    # 完成后不再阻止新任务
    r1.status = MediaRunStatus.COMPLETED
    session.commit()
    r2 = _run(asset.id, MediaRunStatus.QUEUED)
    session.add(r2)
    session.commit()  # 不应抛

    # 多个 completed/failed 可共存
    r2.status = MediaRunStatus.FAILED
    session.commit()
    session.add(_run(asset.id, MediaRunStatus.QUEUED))
    session.commit()  # 不应抛

    active = (
        session.query(MediaProcessingRun)
        .filter(
            MediaProcessingRun.asset_id == asset.id,
            MediaProcessingRun.status.in_([MediaRunStatus.QUEUED, MediaRunStatus.RUNNING]),
        )
        .count()
    )
    assert active == 1
