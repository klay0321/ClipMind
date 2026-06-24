"""测试辅助：用 FFmpeg 现场生成微型合成视频（避免提交任何真实视频）。

仅供测试使用。生成的片段为数十 KB 的合成画面/正弦音，不含任何真实素材。
"""

from __future__ import annotations

import os
import subprocess


def ffmpeg_available() -> bool:
    try:
        proc = subprocess.run(  # noqa: S603, S607
            ["ffmpeg", "-version"], capture_output=True, timeout=10, check=False
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def make_test_video(
    path: str,
    *,
    duration: int = 1,
    width: int = 320,
    height: int = 240,
    fps: int = 10,
    with_audio: bool = True,
) -> str:
    """生成一个合成 mp4（H.264 + 可选 AAC），返回路径。需要 ffmpeg。"""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size={width}x{height}:rate={fps}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [str(path)]
    subprocess.run(cmd, capture_output=True, check=True)  # noqa: S603
    return str(path)


def make_corrupt_video(path: str) -> str:
    """写入随机字节，模拟损坏/不可解析的视频文件。"""
    with open(path, "wb") as f:
        f.write(os.urandom(4096))
    return str(path)
