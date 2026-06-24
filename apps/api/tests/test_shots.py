"""PR-02 镜头分析 / 镜头 / 导出 / 文件服务 API 测试（需要 TEST_DATABASE_URL）。"""

from __future__ import annotations

import os

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Asset, Export, MediaProcessingRun, Shot, SourceDirectory
from clipmind_shared.models.enums import (
    AssetStatus,
    ExportStatus,
    MediaRunStatus,
    ShotStatus,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


async def _seed_asset(session, *, filename="片段 A.mp4", status=AssetStatus.INDEXED) -> Asset:
    sd = SourceDirectory(
        name="d",
        mount_path="/app/source",
        include_extensions=["mp4"],
        exclude_patterns=[],
        recursive=True,
        read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id,
        relative_path=filename,
        normalized_relative_path=filename,
        filename=filename,
        extension="mp4",
        file_size=1000,
        duration=10.0,
        width=1920,
        height=1080,
        video_codec="h264",
        audio_codec="aac",
        status=status,
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


async def _seed_shot(session, asset, *, seq=1, status=ShotStatus.READY, paths=None) -> Shot:
    p = paths or {}
    shot = Shot(
        asset_id=asset.id,
        generation=1,
        sequence_no=seq,
        start_time=0.0,
        end_time=2.0,
        duration=2.0,
        detector_type="fixed",
        status=status,
        keyframe_path=p.get("keyframe"),
        thumbnail_path=p.get("thumbnail"),
        proxy_path=p.get("proxy"),
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    return shot


# ---------------- 分析触发 / 状态 / 重试 ----------------


async def test_analyze_shots_dispatch_and_idempotent(client, session):
    asset = await _seed_asset(session)
    r1 = await client.post(f"/api/assets/{asset.id}/analyze-shots")
    assert r1.status_code == 202
    body = r1.json()
    assert body["status"] == "queued"
    assert body["celery_task_id"] == f"mtask-{body['run_id']}"
    # 幂等：已有活动运行 → 返回同一 run
    r2 = await client.post(f"/api/assets/{asset.id}/analyze-shots")
    assert r2.status_code == 202
    assert r2.json()["run_id"] == body["run_id"]


async def test_analyze_404_and_source_missing(client, session):
    r = await client.post("/api/assets/99999/analyze-shots")
    assert r.status_code == 404
    asset = await _seed_asset(session, status=AssetStatus.SOURCE_MISSING)
    r2 = await client.post(f"/api/assets/{asset.id}/analyze-shots")
    assert r2.status_code == 409


async def test_shot_analysis_status(client, session):
    asset = await _seed_asset(session)
    # 无运行
    r0 = await client.get(f"/api/assets/{asset.id}/shot-analysis")
    assert r0.status_code == 200
    assert r0.json()["has_run"] is False
    assert r0.headers.get("cache-control") == "no-store"
    # 有运行
    await client.post(f"/api/assets/{asset.id}/analyze-shots")
    r1 = await client.get(f"/api/assets/{asset.id}/shot-analysis")
    j = r1.json()
    assert j["has_run"] is True
    assert j["status"] == "queued"


async def test_retry_endpoint(client, session):
    asset = await _seed_asset(session)
    r = await client.post(f"/api/assets/{asset.id}/shot-analysis/retry")
    assert r.status_code == 202


# ---------------- 镜头列表 / 详情 ----------------


async def test_list_asset_shots_only_ready(client, session):
    asset = await _seed_asset(session)
    await _seed_shot(session, asset, seq=1, status=ShotStatus.READY)
    await _seed_shot(session, asset, seq=2, status=ShotStatus.PROCESSING)
    r = await client.get(f"/api/assets/{asset.id}/shots")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1  # 仅 ready
    assert body["items"][0]["sequence_no"] == 1


async def test_shot_detail_and_404(client, session):
    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset)
    r = await client.get(f"/api/shots/{shot.id}")
    assert r.status_code == 200
    j = r.json()
    assert j["asset_filename"] == asset.filename
    assert j["asset_video_codec"] == "h264"
    assert j["has_keyframe"] is False
    r404 = await client.get("/api/shots/999999")
    assert r404.status_code == 404


async def test_asset_list_includes_shot_count(client, session):
    asset = await _seed_asset(session)
    await _seed_shot(session, asset, seq=1, status=ShotStatus.READY)
    await _seed_shot(session, asset, seq=2, status=ShotStatus.READY)
    r = await client.get("/api/assets")
    item = next(a for a in r.json()["items"] if a["id"] == asset.id)
    assert item["shot_count"] == 2


# ---------------- 文件服务（含 Range）----------------


def _patch_data_dir(monkeypatch, root: str) -> None:
    from app.config import Settings

    monkeypatch.setattr(
        "app.services.files.get_settings", lambda: Settings(data_dir=root)
    )


async def _shot_with_files(session, asset, tmp_path, monkeypatch) -> tuple[Shot, str]:
    root = os.path.realpath(str(tmp_path / "data"))
    rel = f"assets/{asset.id}/active/shots/X"
    abs_dir = os.path.join(root, "assets", str(asset.id), "active", "shots", "X")
    os.makedirs(abs_dir, exist_ok=True)
    for name in ("thumbnail.webp", "keyframe.webp", "proxy.mp4"):
        with open(os.path.join(abs_dir, name), "wb") as f:
            f.write(b"0123456789")  # 10 字节，便于 Range 断言
    shot = await _seed_shot(
        session,
        asset,
        paths={
            "thumbnail": f"{rel}/thumbnail.webp",
            "keyframe": f"{rel}/keyframe.webp",
            "proxy": f"{rel}/proxy.mp4",
        },
    )
    _patch_data_dir(monkeypatch, root)
    return shot, root


async def test_serve_thumbnail_and_keyframe(client, session, tmp_path, monkeypatch):
    asset = await _seed_asset(session)
    shot, _ = await _shot_with_files(session, asset, tmp_path, monkeypatch)
    r = await client.get(f"/api/shots/{shot.id}/thumbnail")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    assert "immutable" in r.headers.get("cache-control", "")
    assert r.content == b"0123456789"
    rk = await client.get(f"/api/shots/{shot.id}/keyframe")
    assert rk.status_code == 200


async def test_preview_supports_range(client, session, tmp_path, monkeypatch):
    asset = await _seed_asset(session)
    shot, _ = await _shot_with_files(session, asset, tmp_path, monkeypatch)
    # 无 Range → 完整
    full = await client.get(f"/api/shots/{shot.id}/preview")
    assert full.status_code == 200
    assert full.headers["content-type"] == "video/mp4"
    assert full.headers.get("accept-ranges") == "bytes"
    # 部分 Range → 206 + Content-Range
    part = await client.get(
        f"/api/shots/{shot.id}/preview", headers={"Range": "bytes=2-5"}
    )
    assert part.status_code == 206
    assert part.headers["content-range"] == "bytes 2-5/10"
    assert part.content == b"2345"
    # 非法 Range → 416
    bad = await client.get(
        f"/api/shots/{shot.id}/preview", headers={"Range": "bytes=999-1000"}
    )
    assert bad.status_code == 416


async def test_serve_missing_file_404(client, session, tmp_path, monkeypatch):
    asset = await _seed_asset(session)
    # 镜头无派生路径
    shot = await _seed_shot(session, asset)
    r = await client.get(f"/api/shots/{shot.id}/thumbnail")
    assert r.status_code == 404


async def test_derived_path_traversal_blocked(client, session, tmp_path, monkeypatch):
    asset = await _seed_asset(session)
    _patch_data_dir(monkeypatch, os.path.realpath(str(tmp_path / "data")))
    shot = await _seed_shot(
        session, asset, paths={"thumbnail": "../../../../etc/passwd"}
    )
    r = await client.get(f"/api/shots/{shot.id}/thumbnail")
    assert r.status_code == 422  # PathTraversal → 全局 422


# ---------------- 导出 ----------------


async def test_export_dispatch_and_status(client, session):
    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset)
    r = await client.post(f"/api/shots/{shot.id}/export")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["celery_task_id"] == f"etask-{body['export_id']}"
    # 状态查询
    rs = await client.get(f"/api/exports/{body['export_id']}")
    assert rs.status_code == 200
    assert rs.json()["mode"] == "reencode"


async def test_export_download_not_ready_409(client, session):
    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset)
    r = await client.post(f"/api/shots/{shot.id}/export")
    eid = r.json()["export_id"]
    rd = await client.get(f"/api/exports/{eid}/download")
    assert rd.status_code == 409


async def test_export_download_completed(client, session, tmp_path, monkeypatch):
    import uuid

    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset)
    root = os.path.realpath(str(tmp_path / "data"))
    euid = uuid.uuid4().hex
    edir = os.path.join(root, "exports", euid)
    os.makedirs(edir, exist_ok=True)
    with open(os.path.join(edir, "clip.mp4"), "wb") as f:
        f.write(b"VIDEODATA")
    export = Export(
        export_uuid=euid,
        asset_id=asset.id,
        shot_id=shot.id,
        status=ExportStatus.COMPLETED,
        mode="reencode",
        source_asset_id=asset.id,
        source_shot_id=shot.id,
        source_generation=shot.generation,
        source_sequence_no=shot.sequence_no,
        source_start_time=0.0,
        source_end_time=2.0,
        source_filename=asset.filename,
        source_relative_path=asset.relative_path,
        output_path=f"exports/{euid}/clip.mp4",
        filename="片段 A_00m00s-00m02s.mp4",
    )
    session.add(export)
    await session.commit()
    await session.refresh(export)
    _patch_data_dir(monkeypatch, root)
    r = await client.get(f"/api/exports/{export.id}/download")
    assert r.status_code == 200
    assert r.content == b"VIDEODATA"
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "filename*=utf-8''" in cd  # 中文名 RFC5987 编码


async def test_export_dispatch_writes_source_snapshot(client, session):
    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset, seq=3)
    r = await client.post(f"/api/shots/{shot.id}/export")
    eid = r.json()["export_id"]
    j = (await client.get(f"/api/exports/{eid}")).json()
    assert j["asset_id"] == asset.id
    assert j["source_asset_id"] == asset.id
    assert j["source_shot_id"] == shot.id
    assert j["source_generation"] == shot.generation
    assert j["source_sequence_no"] == 3
    assert j["source_filename"] == asset.filename
    assert j["source_relative_path"] == asset.relative_path


async def test_export_traceable_after_shot_deleted(client, session, tmp_path, monkeypatch):
    import uuid

    from clipmind_shared.models import Shot

    asset = await _seed_asset(session)
    shot = await _seed_shot(session, asset, seq=1)
    r = await client.post(f"/api/shots/{shot.id}/export")
    eid = r.json()["export_id"]

    # 模拟 worker 完成导出：写文件 + 标 completed
    root = os.path.realpath(str(tmp_path / "data"))
    euid = uuid.uuid4().hex
    edir = os.path.join(root, "exports", euid)
    os.makedirs(edir, exist_ok=True)
    with open(os.path.join(edir, "clip.mp4"), "wb") as f:
        f.write(b"CLIPBYTES")
    exp = await session.get(Export, eid)
    exp.status = ExportStatus.COMPLETED
    exp.output_path = f"exports/{euid}/clip.mp4"
    exp.filename = "片段_00m00s-00m02s.mp4"
    await session.commit()
    _patch_data_dir(monkeypatch, root)

    # 模拟重分析删除旧镜头（FK SET NULL）
    sh = await session.get(Shot, shot.id)
    await session.delete(sh)
    await session.commit()

    # 导出记录仍可查询，shot_id 置空；asset 仍存在故 asset_id 保留；来源快照完整
    j = (await client.get(f"/api/exports/{eid}")).json()
    assert j["shot_id"] is None
    assert j["asset_id"] == asset.id  # Asset 未删 → asset_id 仍指向
    assert j["source_asset_id"] == asset.id
    assert j["source_shot_id"] == shot.id
    assert j["source_filename"] == asset.filename
    assert j["source_relative_path"] == asset.relative_path
    assert j["source_start_time"] == 0.0 and j["source_end_time"] == 2.0
    # 已生成文件仍可下载
    rd = await client.get(f"/api/exports/{eid}/download")
    assert rd.status_code == 200
    assert rd.content == b"CLIPBYTES"


async def test_concurrent_analysis_deduped(client, session):
    """同一素材并发/重复发起 → 仅一个活动运行（部分唯一索引 + 幂等返回）。"""
    from sqlalchemy import func, select

    asset = await _seed_asset(session)
    run_ids = set()
    for _ in range(3):
        r = await client.post(f"/api/assets/{asset.id}/analyze-shots")
        assert r.status_code == 202
        run_ids.add(r.json()["run_id"])
    assert len(run_ids) == 1  # 始终返回同一活动运行
    active = (
        await session.execute(
            select(func.count())
            .select_from(MediaProcessingRun)
            .where(
                MediaProcessingRun.asset_id == asset.id,
                MediaProcessingRun.status.in_(
                    [MediaRunStatus.QUEUED, MediaRunStatus.RUNNING]
                ),
            )
        )
    ).scalar_one()
    assert active == 1
