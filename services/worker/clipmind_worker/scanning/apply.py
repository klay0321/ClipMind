"""把 FFprobe 结果写入/清空 Asset 的视频信息字段。"""

from __future__ import annotations

from clipmind_shared.ffprobe import ProbeResult
from clipmind_shared.models import Asset


def apply_probe_to_asset(asset: Asset, probe: ProbeResult) -> None:
    asset.duration = probe.duration
    asset.width = probe.width
    asset.height = probe.height
    asset.fps = probe.fps
    asset.video_codec = probe.video_codec
    asset.audio_codec = probe.audio_codec
    asset.orientation = probe.orientation
    asset.has_audio = probe.has_audio


def clear_probe_fields(asset: Asset) -> None:
    asset.duration = None
    asset.width = None
    asset.height = None
    asset.fps = None
    asset.video_codec = None
    asset.audio_codec = None
    asset.orientation = None
    asset.has_audio = None
