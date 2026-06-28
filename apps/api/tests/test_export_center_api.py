"""PR-06B 统一导出中心 API 测试（需 TEST_DATABASE_URL）。

覆盖：三类聚合 + 筛选 + 稳定排序 + 分页；retry（仅 failed）；delete（仅 completed/failed，
删派生文件 + 安全拒绝穿越，绝不碰源）；download_log。
"""

from __future__ import annotations

import os

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    BundleExport,
    Export,
    ScriptExport,
    ScriptProject,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import AssetStatus, ExportStatus, ScriptStatus, ShotStatus

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


async def _asset_shot(session):
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id, relative_path="a.mp4", normalized_relative_path="a.mp4",
        filename="a.mp4", extension="mp4", file_size=1, duration=5.0,
        status=AssetStatus.INDEXED, first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    shot = Shot(
        asset_id=asset.id, generation=1, sequence_no=1, start_time=0.0, end_time=2.0,
        duration=2.0, detector_type="fixed", status=ShotStatus.READY,
        keyframe_path="k.jpg", proxy_path="p.mp4",
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    return asset, shot


async def _clip_export(session, asset, shot, *, status=ExportStatus.COMPLETED, output_path=None):
    e = Export(
        export_uuid=f"clip{shot.id}{status.value}", asset_id=asset.id, shot_id=shot.id,
        status=status, mode="reencode", source_asset_id=asset.id, source_shot_id=shot.id,
        source_generation=1, source_sequence_no=1, source_start_time=0.0, source_end_time=2.0,
        source_filename="a.mp4", source_relative_path="a.mp4", output_path=output_path,
        filename="clip.mp4" if output_path else None, queued_at=utcnow(),
    )
    session.add(e)
    await session.commit()
    await session.refresh(e)
    return e


async def _script_export(session, *, status=ExportStatus.COMPLETED, fmt="csv"):
    sp = ScriptProject(
        name="脚本", raw_script="t", source_format="paste", status=ScriptStatus.PARSED,
    )
    session.add(sp)
    await session.commit()
    await session.refresh(sp)
    se = ScriptExport(
        export_uuid=f"se{sp.id}{fmt}", script_project_id=sp.id, status=status,
        export_format=fmt, filename="x.csv", row_count=3, queued_at=utcnow(),
    )
    session.add(se)
    await session.commit()
    await session.refresh(se)
    return se


async def _bundle(session, *, status=ExportStatus.FAILED):
    b = BundleExport(
        export_uuid=f"bn{status.value}", status=status, shot_ids=[1, 2], mode="reencode",
        error_message="boom" if status == ExportStatus.FAILED else None, queued_at=utcnow(),
    )
    session.add(b)
    await session.commit()
    await session.refresh(b)
    return b


async def test_export_center_aggregates_three_kinds(client, session):
    asset, shot = await _asset_shot(session)
    await _clip_export(session, asset, shot)
    await _script_export(session)
    await _bundle(session, status=ExportStatus.COMPLETED)

    r = await client.get("/api/export-center")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    kinds = {it["kind"] for it in data["items"]}
    assert kinds == {"clip", "script", "bundle"}
    # 每类 download_url 形态
    by_kind = {it["kind"]: it for it in data["items"]}
    assert by_kind["clip"]["download_url"].startswith("/api/exports/")
    assert "/exports/bundle/" in by_kind["bundle"]["download_url"]
    assert "/scripts/" in by_kind["script"]["download_url"]


async def test_export_center_filters_and_pagination(client, session):
    asset, shot = await _asset_shot(session)
    await _clip_export(session, asset, shot)
    await _script_export(session, status=ExportStatus.FAILED)

    r = await client.get("/api/export-center", params={"kind": "clip"})
    assert r.json()["total"] == 1
    r = await client.get("/api/export-center", params={"status": "failed"})
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["kind"] == "script"
    r = await client.get("/api/export-center", params={"page": 1, "page_size": 1})
    assert len(r.json()["items"]) == 1
    assert r.json()["total"] == 2


async def test_retry_only_failed(client, session, monkeypatch):
    monkeypatch.setattr(
        "app.services.export_center_service.enqueue_export_clip", lambda eid: f"rt-{eid}"
    )
    asset, shot = await _asset_shot(session)
    failed = await _clip_export(session, asset, shot, status=ExportStatus.FAILED)
    completed = await _clip_export(session, asset, shot, status=ExportStatus.COMPLETED)

    r = await client.post(f"/api/export-center/clip/{failed.id}/retry")
    assert r.status_code == 200
    assert r.json()["status"] == "queued"

    r = await client.post(f"/api/export-center/clip/{completed.id}/retry")
    assert r.status_code == 409


async def test_delete_removes_file_and_row(client, session, tmp_path, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))
    data_dir = str(tmp_path)
    rel = "exports/udel/clip.mp4"
    abs_path = os.path.join(data_dir, "exports", "udel", "clip.mp4")
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(b"x")

    asset, shot = await _asset_shot(session)
    e = await _clip_export(session, asset, shot, status=ExportStatus.COMPLETED, output_path=rel)

    r = await client.delete(f"/api/export-center/clip/{e.id}")
    assert r.status_code == 204
    assert not os.path.exists(abs_path)  # 派生文件已删
    r = await client.get(f"/api/export-center/clip/{e.id}")
    assert r.status_code == 404  # 记录已删


async def test_delete_blocks_running_and_path_traversal(client, session):
    asset, shot = await _asset_shot(session)
    running = await _clip_export(session, asset, shot, status=ExportStatus.RUNNING)
    r = await client.delete(f"/api/export-center/clip/{running.id}")
    assert r.status_code == 409  # queued/running 不可删

    evil = await _clip_export(
        session, asset, shot, status=ExportStatus.COMPLETED,
        output_path="exports/../../../../etc/passwd",
    )
    r = await client.delete(f"/api/export-center/clip/{evil.id}")
    assert r.status_code in (400, 422)  # 拒绝穿越
    # 记录仍在（删除被拒绝，未静默成功）
    assert (await client.get(f"/api/export-center/clip/{evil.id}")).status_code == 200


async def test_download_log_increments(client, session, tmp_path, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))
    data_dir = str(tmp_path)
    rel = "exports/udl/clip.mp4"
    abs_path = os.path.join(data_dir, "exports", "udl", "clip.mp4")
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(b"video")

    asset, shot = await _asset_shot(session)
    e = await _clip_export(session, asset, shot, status=ExportStatus.COMPLETED, output_path=rel)

    assert (await client.get(f"/api/exports/{e.id}/download")).status_code == 200
    r = await client.get("/api/export-center", params={"kind": "clip"})
    item = r.json()["items"][0]
    assert item["download_count"] == 1
