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
from clipmind_worker.media.derive import MediaConfig, derive_shot
from clipmind_worker.media.detector import (
    ShotBoundary,
    ShotConfig,
    detect_shots,
)

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="需要 ffmpeg")

CFG = MediaConfig(proxy_preset="ultrafast", ffmpeg_timeout=120.0, ffprobe_timeout=30.0)


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
