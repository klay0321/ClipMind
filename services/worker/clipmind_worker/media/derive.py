"""单个镜头的派生文件生成（关键帧 / 缩略图 / 代理）。

所有文件先写入 run 的 staging 目录；由上层任务在完整成功后再原子搬入 active。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from clipmind_worker.media import ffmpeg
from clipmind_worker.media.detector import ShotBoundary

logger = logging.getLogger(__name__)

KEYFRAME_NAME = "keyframe.webp"
THUMBNAIL_NAME = "thumbnail.webp"
PROXY_NAME = "proxy.mp4"


def strip_frame_name(index: int) -> str:
    """关键帧条第 index 帧的文件名（active 与 staging 同名）。"""
    return f"keyframe_strip_{index}.webp"


@dataclass(frozen=True)
class MediaConfig:
    """派生参数（来自 WorkerSettings）。"""

    keyframe_max_width: int = 640
    thumbnail_max_width: int = 320
    proxy_max_height: int = 720
    proxy_crf: int = 28
    proxy_preset: str = "veryfast"
    proxy_keep_audio: bool = True
    proxy_audio_bitrate: str = "96k"
    aux_keyframes: int = 0
    ffmpeg_timeout: float = 300.0
    ffprobe_timeout: float = 30.0


@dataclass
class DerivedFiles:
    keyframe: str
    thumbnail: str
    proxy: str
    # 关键帧条各帧绝对路径（按时间有序）；可能为空（aux_keyframes=0 或全部失败）
    strip: list[str] = field(default_factory=list)


def _midpoint(boundary: ShotBoundary) -> float:
    """镜头中点；对极短镜头做安全收敛，避免落在末尾无帧处。"""
    mid = boundary.start + (boundary.duration / 2.0)
    upper = max(boundary.end - 0.05, boundary.start)
    return min(max(mid, boundary.start), upper)


def strip_timestamps(boundary: ShotBoundary, n: int) -> list[float]:
    """沿镜头时间在 [start, end) 内均匀取 n 个采样点（用于关键帧条）。

    收敛到 [start+5%span, end-5%span] 避免落在切点边缘；并夹到 end-0.05 之前。
    """
    if n <= 0:
        return []
    span = max(boundary.end - boundary.start, 0.0)
    lo = boundary.start + span * 0.05
    hi = boundary.end - span * 0.05
    upper = max(boundary.end - 0.05, boundary.start)
    if hi < lo:
        lo = hi = boundary.start
    if n == 1:
        pts = [(lo + hi) / 2.0]
    else:
        pts = [lo + (hi - lo) * k / (n - 1) for k in range(n)]
    return [min(max(p, boundary.start), upper) for p in pts]


def derive_shot(
    src: str,
    boundary: ShotBoundary,
    staging_shot_dir: str,
    *,
    has_audio: bool,
    config: MediaConfig,
) -> DerivedFiles:
    """为单个镜头在 staging_shot_dir 生成关键帧/缩略图/代理，返回三者绝对路径。"""
    os.makedirs(staging_shot_dir, exist_ok=True)

    keyframe = os.path.join(staging_shot_dir, KEYFRAME_NAME)
    thumbnail = os.path.join(staging_shot_dir, THUMBNAIL_NAME)
    proxy = os.path.join(staging_shot_dir, PROXY_NAME)

    # 主关键帧（镜头中点）
    ffmpeg.extract_keyframe(
        src,
        _midpoint(boundary),
        keyframe,
        max_width=config.keyframe_max_width,
        timeout=config.ffmpeg_timeout,
    )
    if not os.path.isfile(keyframe) or os.path.getsize(keyframe) == 0:
        raise ffmpeg.FFmpegError("keyframe_missing", "关键帧未生成")

    # 缩略图（由关键帧缩放，省去重复 seek）
    ffmpeg.make_thumbnail(
        keyframe,
        thumbnail,
        max_width=config.thumbnail_max_width,
        timeout=config.ffmpeg_timeout,
    )
    if not os.path.isfile(thumbnail) or os.path.getsize(thumbnail) == 0:
        raise ffmpeg.FFmpegError("thumbnail_missing", "缩略图未生成")

    # 代理视频（浏览器可播放，需 ffprobe 校验）
    ffmpeg.make_proxy(
        src,
        boundary.start,
        boundary.end,
        proxy,
        max_height=config.proxy_max_height,
        crf=config.proxy_crf,
        preset=config.proxy_preset,
        keep_audio=config.proxy_keep_audio,
        audio_bitrate=config.proxy_audio_bitrate,
        has_audio=has_audio,
        timeout=config.ffmpeg_timeout,
    )
    ffmpeg.validate_media(proxy, ffprobe_timeout=config.ffprobe_timeout)

    # 关键帧条（辅助预览，尽力而为：单帧失败不致整镜头失败）
    strip: list[str] = []
    for idx, ts in enumerate(strip_timestamps(boundary, config.aux_keyframes)):
        dest = os.path.join(staging_shot_dir, strip_frame_name(idx))
        try:
            ffmpeg.extract_keyframe(
                src, ts, dest, max_width=config.keyframe_max_width, timeout=config.ffmpeg_timeout
            )
            if os.path.isfile(dest) and os.path.getsize(dest) > 0:
                strip.append(dest)
        except ffmpeg.FFmpegError as exc:
            logger.warning("关键帧条第 %d 帧生成失败（已跳过）：%s", idx, exc)

    return DerivedFiles(keyframe=keyframe, thumbnail=thumbnail, proxy=proxy, strip=strip)
