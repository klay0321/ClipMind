"""FFmpeg 派生处理封装（关键帧 / 缩略图 / 代理 / 片段导出）。

安全约定（与 clipmind_shared.ffprobe 一致）：
- 一律使用参数数组，绝不 shell=True；用 `--` 阻断文件名选项注入。
- 显式超时；检查退出码；stderr 截断保存；输出文件存在性 + 可被 ffprobe 校验。
- 源文件只读，输出只写 data_dir。
"""

from __future__ import annotations

import logging
import os
import subprocess

from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN
from clipmind_shared.ffprobe import ProbeError, probe_video

logger = logging.getLogger(__name__)


class FFmpegError(Exception):
    """FFmpeg 处理失败。reason 可分类，detail 为截断后的细节。"""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def run_ffmpeg(args: list[str], *, timeout: float, ffmpeg_path: str = "ffmpeg") -> None:
    """运行 ffmpeg（不含可执行名与全局 -y/-nostdin），失败抛 FFmpegError。"""
    cmd = [ffmpeg_path, "-nostdin", "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(  # noqa: S603 - 固定参数列表，无 shell
            cmd, capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError("timeout", f"ffmpeg 超时(>{timeout}s)") from exc
    except FileNotFoundError as exc:
        raise FFmpegError("ffmpeg_not_found", "未找到 ffmpeg 可执行文件") from exc

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise FFmpegError("ffmpeg_failed", stderr[:ERROR_MESSAGE_MAX_LEN])


def validate_media(path: str, *, ffprobe_timeout: float = 30.0) -> None:
    """确认输出文件存在、非空且可被 ffprobe 解析；否则抛 FFmpegError。"""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise FFmpegError("output_missing", f"输出文件缺失或为空: {os.path.basename(path)}")
    try:
        probe_video(path, timeout=ffprobe_timeout)
    except ProbeError as exc:
        raise FFmpegError("output_invalid", f"{exc.reason}: {exc.detail}".strip()) from exc


def _clamp(ts: float, lo: float, hi: float) -> float:
    return max(lo, min(ts, hi))


def extract_keyframe(
    src: str,
    timestamp: float,
    out_path: str,
    *,
    max_width: int,
    timeout: float,
) -> None:
    """在 timestamp 处抽 1 帧，按 max_width 等比缩放（不放大），输出 WebP/JPEG。"""
    ts = max(timestamp, 0.0)
    vf = f"scale='min(iw,{max_width})':-2"
    args = [
        "-ss", f"{ts:.3f}",
        "-i", src,
        "-frames:v", "1",
        "-vf", vf,
        "-an",
        "--", out_path,
    ]
    run_ffmpeg(args, timeout=timeout)


def make_thumbnail(src_image: str, out_path: str, *, max_width: int, timeout: float) -> None:
    """由已生成的关键帧图缩放出更小的缩略图（避免重复 seek 源视频）。"""
    vf = f"scale='min(iw,{max_width})':-2"
    args = ["-i", src_image, "-vf", vf, "--", out_path]
    run_ffmpeg(args, timeout=timeout)


def _proxy_scale_filter(max_height: int) -> str:
    # 高度上限 max_height，不放大；宽高均强制为偶数（libx264 + yuv420p 要求）。
    return f"scale=-2:'min({max_height},ih)',crop=trunc(iw/2)*2:trunc(ih/2)*2"


def make_proxy(
    src: str,
    start: float,
    end: float,
    out_path: str,
    *,
    max_height: int,
    crf: int,
    preset: str,
    keep_audio: bool,
    audio_bitrate: str,
    has_audio: bool,
    timeout: float,
) -> None:
    """生成浏览器可播放的代理片段：H.264 + yuv420p + faststart，高度<=max_height。"""
    duration = max(end - start, 0.04)
    args = [
        "-ss", f"{start:.3f}",
        "-i", src,
        "-t", f"{duration:.3f}",
        "-vf", _proxy_scale_filter(max_height),
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]
    if keep_audio and has_audio:
        args += ["-c:a", "aac", "-b:a", audio_bitrate]
    else:
        args += ["-an"]
    args += ["--", out_path]
    run_ffmpeg(args, timeout=timeout)


def export_clip(
    src: str,
    start: float,
    end: float,
    out_path: str,
    *,
    mode: str,
    has_audio: bool,
    timeout: float,
) -> None:
    """按镜头时间区间导出片段。

    默认 reencode：优先保证时间边界准确与浏览器/剪辑软件兼容（H.264 + yuv420p + AAC + faststart）。
    可选 copy：stream copy（快但非关键帧切点可能不准），非默认。
    """
    duration = max(end - start, 0.04)
    if mode == "copy":
        args = [
            "-ss", f"{start:.3f}",
            "-i", src,
            "-t", f"{duration:.3f}",
            "-c", "copy",
            "-movflags", "+faststart",
            "--", out_path,
        ]
        run_ffmpeg(args, timeout=timeout)
        return

    # reencode（默认）：精确 seek + 原分辨率高质量
    args = [
        "-ss", f"{start:.3f}",
        "-i", src,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]
    if has_audio:
        args += ["-c:a", "aac", "-b:a", "128k"]
    else:
        args += ["-an"]
    args += ["--", out_path]
    run_ffmpeg(args, timeout=timeout)
