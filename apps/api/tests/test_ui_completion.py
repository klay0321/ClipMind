"""本轮 UI 补全的后端契约测试：封面镜头、镜头来源文件名、网页上传。

需要 TEST_DATABASE_URL。
"""

from __future__ import annotations

import os

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Asset, Shot, SourceDirectory
from clipmind_shared.models.enums import AssetStatus, ShotStatus
from sqlalchemy import select

from app.config import get_settings

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


# ---------------- 封面镜头 ----------------


async def test_asset_list_exposes_cover_shot(client, session):
    asset = await _seed_asset(session, filename="封面片.mp4")
    s1 = await _seed_shot(session, asset, seq=1, paths={"keyframe": "k1", "thumbnail": "t1"})
    await _seed_shot(session, asset, seq=2, paths={"keyframe": "k2", "thumbnail": "t2"})

    resp = await client.get("/api/assets")
    assert resp.status_code == 200
    item = next(a for a in resp.json()["items"] if a["id"] == asset.id)
    # 封面取首个 ready 镜头（按 sequence_no），即 s1
    assert item["cover_shot_id"] == s1.id


async def test_asset_without_ready_shot_has_null_cover(client, session):
    asset = await _seed_asset(session, filename="无镜头.mp4")
    resp = await client.get("/api/assets")
    item = next(a for a in resp.json()["items"] if a["id"] == asset.id)
    assert item["cover_shot_id"] is None


# ---------------- 镜头来源文件名 ----------------


async def test_shots_list_includes_asset_filename(client, session):
    asset = await _seed_asset(session, filename="来源素材.mp4")
    await _seed_shot(session, asset, seq=1, paths={"thumbnail": "t1"})

    resp = await client.get("/api/shots")
    assert resp.status_code == 200
    item = next(s for s in resp.json()["items"] if s["asset_id"] == asset.id)
    assert item["asset_filename"] == "来源素材.mp4"


# ---------------- 网页上传 ----------------


async def test_upload_writes_file_and_creates_source_dir(client, session, tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(get_settings(), "upload_dir", str(upload_dir))

    resp = await client.post(
        "/api/uploads",
        files={"file": ("我的视频.mp4", b"\x00\x01\x02data", "video/mp4")},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["filename"] == "我的视频.mp4"
    assert body["bytes"] == 7
    assert body["scan_run_id"] > 0

    # 文件确实落盘到上传区
    assert (upload_dir / "我的视频.mp4").exists()

    # 自动创建了「上传素材」源目录，mount_path 指向上传区 realpath
    sd = (
        await session.execute(
            select(SourceDirectory).where(SourceDirectory.id == body["source_directory_id"])
        )
    ).scalar_one()
    assert sd.name == "上传素材"
    assert sd.mount_path == os.path.realpath(str(upload_dir))


async def test_upload_dedupes_same_name(client, session, tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(get_settings(), "upload_dir", str(upload_dir))

    r1 = await client.post("/api/uploads", files={"file": ("dup.mp4", b"a", "video/mp4")})
    r2 = await client.post("/api/uploads", files={"file": ("dup.mp4", b"b", "video/mp4")})
    assert r1.json()["filename"] == "dup.mp4"
    assert r2.json()["filename"] == "dup-1.mp4"
    assert (upload_dir / "dup.mp4").exists()
    assert (upload_dir / "dup-1.mp4").exists()


async def test_upload_rejects_unsupported_extension(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    resp = await client.post(
        "/api/uploads",
        files={"file": ("bad.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 422
    assert "不支持" in resp.json()["detail"]


@pytest.mark.parametrize(
    "evil",
    [
        "../../../../tmp/evil.mp4",
        "..\\..\\evil.mp4",
        "/etc/evil.mp4",
        "....//evil.mp4",
        "a/b/c/evil.mp4",
    ],
)
async def test_upload_filename_cannot_escape_upload_dir(
    client, session, tmp_path, monkeypatch, evil
):
    """安全不变量回归守护：任意恶意文件名仍只能落在上传区之内。"""
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(get_settings(), "upload_dir", str(upload_dir))
    resp = await client.post("/api/uploads", files={"file": (evil, b"data", "video/mp4")})
    assert resp.status_code == 202, resp.text
    name = resp.json()["filename"]
    # 返回的落盘文件名不含任何路径分隔符
    assert "/" not in name and "\\" not in name
    root = os.path.realpath(str(upload_dir))
    landed = os.path.realpath(os.path.join(root, name))
    # 真实落盘点仍位于上传区之内
    assert landed == root + os.sep + name
    assert os.path.commonpath([landed, root]) == root
    assert os.path.isfile(landed)
    # 上传区之外（如临时根）未产生任何文件
    assert not os.path.exists(str(tmp_path / "evil.mp4"))


async def test_upload_rejects_oversize_and_cleans_part(client, session, tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(get_settings(), "upload_dir", str(upload_dir))
    monkeypatch.setattr(get_settings(), "upload_max_mb", 0)  # 任意非空即超限
    resp = await client.post("/api/uploads", files={"file": ("big.mp4", b"xxxx", "video/mp4")})
    assert resp.status_code == 422
    assert "上限" in resp.json()["detail"]
    # 既无目标文件也无 .part 残留，上传区干净
    assert os.path.isdir(str(upload_dir))
    assert os.listdir(str(upload_dir)) == []


class _BoomStream:
    """模拟写入中途失败的上传流：首块正常，之后抛 OSError（磁盘满/连接中断）。"""

    def __init__(self) -> None:
        self.n = 0

    async def read(self, _size: int) -> bytes:
        self.n += 1
        if self.n == 1:
            return b"partial-data"
        raise OSError("disk full")


async def test_upload_write_failure_cleans_part(session, tmp_path, monkeypatch):
    from app.services import upload_service

    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(get_settings(), "upload_dir", str(upload_dir))
    with pytest.raises(OSError):
        await upload_service.save_upload(session, filename="x.mp4", stream=_BoomStream())
    # finally 清理 .part，失败路径不残留半文件
    assert os.path.isdir(str(upload_dir))
    assert os.listdir(str(upload_dir)) == []


# ---------------- 关键帧条 ----------------


def _patch_data_dir(monkeypatch, root: str) -> None:
    from app.config import Settings

    monkeypatch.setattr("app.services.files.get_settings", lambda: Settings(data_dir=root))


async def test_keyframe_strip_count_and_serving(client, session, tmp_path, monkeypatch):
    asset = await _seed_asset(session, filename="条.mp4")
    root = os.path.realpath(str(tmp_path / "data"))
    rel = f"assets/{asset.id}/active/shots/Y"
    abs_dir = os.path.join(root, "assets", str(asset.id), "active", "shots", "Y")
    os.makedirs(abs_dir, exist_ok=True)
    for k in range(3):
        with open(os.path.join(abs_dir, f"keyframe_strip_{k}.webp"), "wb") as f:
            f.write(bytes([k]) * 5)
    shot = await _seed_shot(session, asset, paths={"keyframe": f"{rel}/keyframe.webp"})
    shot.keyframe_paths = [f"{rel}/keyframe_strip_{k}.webp" for k in range(3)]
    await session.commit()
    _patch_data_dir(monkeypatch, root)

    # 列表暴露 keyframe_count
    lst = await client.get("/api/shots")
    item = next(s for s in lst.json()["items"] if s["id"] == shot.id)
    assert item["keyframe_count"] == 3

    # 取第 0/2 帧 200，内容正确；越界 404
    r0 = await client.get(f"/api/shots/{shot.id}/keyframe/0")
    assert r0.status_code == 200
    assert r0.headers["content-type"] == "image/webp"
    assert r0.content == bytes([0]) * 5
    assert (await client.get(f"/api/shots/{shot.id}/keyframe/2")).status_code == 200
    assert (await client.get(f"/api/shots/{shot.id}/keyframe/9")).status_code == 404


async def test_keyframe_strip_absent_is_zero(client, session, tmp_path, monkeypatch):
    asset = await _seed_asset(session, filename="无条.mp4")
    shot = await _seed_shot(session, asset, paths={"keyframe": "a/k.webp"})
    lst = await client.get("/api/shots")
    item = next(s for s in lst.json()["items"] if s["id"] == shot.id)
    assert item["keyframe_count"] == 0
    # 无关键帧条 → 任意索引 404
    assert (await client.get(f"/api/shots/{shot.id}/keyframe/0")).status_code == 404
