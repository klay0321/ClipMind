"""媒体派生/检测的真实 ffmpeg 集成测试（无 DB）。

使用合成视频，绝不提交真实素材。无 ffmpeg 时整体跳过。
"""

from __future__ import annotations

import os

import pytest
from clipmind_shared.ffprobe import probe_video
from clipmind_shared.testing import (
    ffmpeg_available,
    make_multi_scene_video,
    make_test_video,
)

from clipmind_worker.media import ffmpeg
from clipmind_worker.media.derive import (
    MediaConfig,
    derive_shot,
    strip_frame_name,
    strip_timestamps,
)
from clipmind_worker.media.detector import (
    ShotBoundary,
    ShotConfig,
    detect_shots,
)

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="需要 ffmpeg")

CFG = MediaConfig(proxy_preset="ultrafast", ffmpeg_timeout=120.0, ffprobe_timeout=30.0)


def test_strip_timestamps_pure():
    # 0 帧 → 空
    assert strip_timestamps(ShotBoundary(0.0, 5.0), 0) == []
    # n 帧：有序、落在 [start, end-0.05] 内
    ts = strip_timestamps(ShotBoundary(2.0, 6.0), 4)
    assert len(ts) == 4
    assert ts == sorted(ts)
    assert ts[0] >= 2.0 and ts[-1] <= 6.0 - 0.05 + 1e-9
    # 极短镜头不越界
    short = strip_timestamps(ShotBoundary(0.0, 0.2), 3)
    assert len(short) == 3
    assert all(0.0 <= t <= max(0.2 - 0.05, 0.0) + 1e-9 for t in short)


@needs_ffmpeg
def test_derive_shot_generates_keyframe_strip(tmp_path):
    src = make_test_video(str(tmp_path / "strip.mp4"), duration=4, width=320, height=240, fps=15)
    staging = str(tmp_path / "stage_strip")
    cfg = MediaConfig(
        proxy_preset="ultrafast", ffmpeg_timeout=120.0, ffprobe_timeout=30.0, aux_keyframes=4
    )
    out = derive_shot(src, ShotBoundary(0.0, 4.0), staging, has_audio=True, config=cfg)
    assert len(out.strip) == 4
    for k, p in enumerate(out.strip):
        assert os.path.basename(p) == strip_frame_name(k)
        assert os.path.isfile(p) and os.path.getsize(p) > 0


def test_derive_shot_strip_partial_failure_best_effort(tmp_path, monkeypatch):
    """关键帧条尽力而为：部分帧失败时整镜头不失败，strip 仅含成功帧（无需真实 ffmpeg）。"""
    from clipmind_worker.media import derive as derive_mod

    def fake_extract(src, ts, dest, **kw):  # noqa: ANN001
        # 模拟第 1、3 帧（strip 索引 1/3）失败；其余写出占位文件
        if dest.endswith(strip_frame_name(1)) or dest.endswith(strip_frame_name(3)):
            raise ffmpeg.FFmpegError("boom", "模拟关键帧失败")
        with open(dest, "wb") as f:
            f.write(b"img")

    def fake_thumb(keyframe, thumbnail, **kw):  # noqa: ANN001
        with open(thumbnail, "wb") as f:
            f.write(b"th")

    def fake_proxy(src, start, end, proxy, **kw):  # noqa: ANN001
        with open(proxy, "wb") as f:
            f.write(b"px")

    monkeypatch.setattr(derive_mod.ffmpeg, "extract_keyframe", fake_extract)
    monkeypatch.setattr(derive_mod.ffmpeg, "make_thumbnail", fake_thumb)
    monkeypatch.setattr(derive_mod.ffmpeg, "make_proxy", fake_proxy)
    monkeypatch.setattr(derive_mod.ffmpeg, "validate_media", lambda *a, **k: None)

    cfg = MediaConfig(aux_keyframes=4)
    out = derive_shot(
        "/src.mp4", ShotBoundary(0.0, 4.0), str(tmp_path / "s"), has_audio=False, config=cfg
    )
    # 4 帧中 2 帧失败 → strip 仅含 2 个成功帧；主帧/缩略图/代理仍在
    assert len(out.strip) == 2
    for p in out.strip:
        assert os.path.isfile(p) and os.path.getsize(p) > 0
    for p in (out.keyframe, out.thumbnail, out.proxy):
        assert os.path.isfile(p) and os.path.getsize(p) > 0


@needs_ffmpeg
def test_pyscenedetect_finds_scenes(tmp_path):
    src = make_multi_scene_video(str(tmp_path / "multi.mp4"), scenes=4, seg_duration=2)
    dur = probe_video(src).duration or 8.0
    cfg = ShotConfig(scene_threshold=20.0, min_shot_duration=0.5, max_shot_duration=30.0)
    shots = detect_shots(src, duration=dur, config=cfg)
    assert len(shots) >= 2  # 多场景视频应检出多个镜头
    prev_end = 0.0
    for s in shots:
        assert s.start >= prev_end - 1e-3
        assert s.end <= dur + 1e-2
        prev_end = s.end


@needs_ffmpeg
def test_derive_shot_landscape(tmp_path):
    src = make_test_video(str(tmp_path / "land.mp4"), duration=4, width=640, height=360, fps=15)
    staging = str(tmp_path / "stage")
    out = derive_shot(
        src, ShotBoundary(0.5, 3.5), staging, has_audio=True, config=CFG
    )
    # 三个派生文件均存在且非空
    for p in (out.keyframe, out.thumbnail, out.proxy):
        assert os.path.isfile(p) and os.path.getsize(p) > 0
    # 代理为 H.264，高度不超过上限且未放大
    proxy = probe_video(out.proxy)
    assert proxy.video_codec == "h264"
    assert proxy.height is not None and proxy.height <= 720
    # 代理时长接近镜头时长
    assert proxy.duration is not None and abs(proxy.duration - 3.0) < 1.0


@needs_ffmpeg
def test_derive_shot_portrait_no_audio(tmp_path):
    src = make_test_video(
        str(tmp_path / "port.mp4"), duration=3, width=240, height=426, fps=15, with_audio=False
    )
    staging = str(tmp_path / "stage2")
    out = derive_shot(src, ShotBoundary(0.0, 2.0), staging, has_audio=False, config=CFG)
    proxy = probe_video(out.proxy)
    assert proxy.video_codec == "h264"
    assert proxy.has_audio is False  # 源无音频 → 代理无音频
    # 偶数尺寸（libx264 + yuv420p 要求）
    assert proxy.width is not None and proxy.height is not None
    assert proxy.width % 2 == 0 and proxy.height % 2 == 0


@needs_ffmpeg
def test_proxy_does_not_upscale(tmp_path):
    src = make_test_video(str(tmp_path / "small.mp4"), duration=2, width=160, height=120, fps=10)
    staging = str(tmp_path / "stage3")
    out = derive_shot(src, ShotBoundary(0.0, 2.0), staging, has_audio=True, config=CFG)
    proxy = probe_video(out.proxy)
    assert proxy.height is not None and proxy.height <= 120  # 不放大低分辨率


@needs_ffmpeg
def test_export_clip_reencode_accurate(tmp_path):
    src = make_test_video(str(tmp_path / "exp.mp4"), duration=6, width=320, height=240, fps=15)
    out = str(tmp_path / "clip.mp4")
    ffmpeg.export_clip(src, 1.0, 3.0, out, mode="reencode", has_audio=True, timeout=120.0)
    ffmpeg.validate_media(out)
    clip = probe_video(out)
    assert clip.video_codec == "h264"
    assert clip.duration is not None and abs(clip.duration - 2.0) < 0.4  # 时间边界准确


@needs_ffmpeg
def test_ffmpeg_failure_on_corrupt(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(os.urandom(2048))
    with pytest.raises(ffmpeg.FFmpegError):
        ffmpeg.extract_keyframe(str(bad), 0.5, str(tmp_path / "k.webp"),
                                max_width=320, timeout=30.0)
