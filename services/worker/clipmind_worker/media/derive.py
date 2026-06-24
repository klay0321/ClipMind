"""单个镜头的派生文件生成（关键帧 / 缩略图 / 代理）。

所有文件先写入 run 的 staging 目录；由上层任务在完整成功后再原子搬入 active。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from clipmind_worker.media import ffmpeg
from clipmind_worker.media.detector import ShotBoundary

KEYFRAME_NAME = "keyframe.webp"
THUMBNAIL_NAME = "thumbnail.webp"
PROXY_NAME = "proxy.mp4"


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
    ffmpeg_timeout: float = 300.0
    ffprobe_timeout: float = 30.0


@dataclass
class DerivedFiles:
    keyframe: str
    thumbnail: str
    proxy: str


def _midpoint(boundary: ShotBoundary) -> float:
    """镜头中点；对极短镜头做安全收敛，避免落在末尾无帧处。"""
    mid = boundary.start + (boundary.duration / 2.0)
    upper = max(boundary.end - 0.05, boundary.start)
    return min(max(mid, boundary.start), upper)


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

    return DerivedFiles(keyframe=keyframe, thumbnail=thumbnail, proxy=proxy)
