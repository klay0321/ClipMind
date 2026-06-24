import pytest

from clipmind_shared.ffprobe import ProbeError, parse_fps, probe_video
from clipmind_shared.testing import ffmpeg_available, make_corrupt_video, make_test_video

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="需要 ffmpeg")


def test_parse_fps():
    assert parse_fps("30000/1001") == pytest.approx(29.97, abs=0.01)
    assert parse_fps("25/1") == 25.0
    assert parse_fps(None) is None
    assert parse_fps("0/0") is None
    assert parse_fps("invalid") is None


@needs_ffmpeg
def test_probe_landscape(tmp_path):
    p = make_test_video(str(tmp_path / "land.mp4"), width=320, height=240)
    r = probe_video(p)
    assert r.width == 320
    assert r.height == 240
    assert r.orientation == "landscape"
    assert r.video_codec == "h264"
    assert r.audio_codec == "aac"
    assert r.has_audio is True
    assert r.duration is not None and r.duration > 0.5


@needs_ffmpeg
def test_probe_portrait(tmp_path):
    p = make_test_video(str(tmp_path / "port.mp4"), width=240, height=320)
    r = probe_video(p)
    assert r.orientation == "portrait"


@needs_ffmpeg
def test_probe_no_audio(tmp_path):
    p = make_test_video(str(tmp_path / "noaudio.mp4"), with_audio=False)
    r = probe_video(p)
    assert r.has_audio is False
    assert r.audio_codec is None


@needs_ffmpeg
def test_probe_corrupt_raises(tmp_path):
    p = make_corrupt_video(str(tmp_path / "corrupt.mp4"))
    with pytest.raises(ProbeError):
        probe_video(p)
